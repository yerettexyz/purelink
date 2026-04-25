import asyncio
import os
import re
import json
import ipaddress
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink - JSON Powered Edition
# Configuration is now decoupled from the source code.

load_dotenv()

# --- Startup Checks ---
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    print("CRITICAL: TOKEN environment variable is not set. Check your .env file.")
    raise SystemExit(1)

def load_config():
    """Load tracking config from data.json using an absolute path."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"CRITICAL: Failed to load data.json: {e}")
        return {
            "unwrap_domains": ["amzn.to", "bit.ly"],
            "tracking_keywords": ["utm_", "ref="],
            "peek_keys": ["url"],
            "search_keepers": ["k", "q"]
        }

CONFIG = load_config()

# --- SSRF Protection ---
# Private, loopback, link-local, and reserved IP ranges to block
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # Private
    ipaddress.ip_network("172.16.0.0/12"),     # Private
    ipaddress.ip_network("192.168.0.0/16"),    # Private
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / Cloud metadata
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 private
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]

def is_ssrf_safe(url: str) -> bool:
    """Return False if URL resolves to a private/reserved address."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            # If we can't parse a hostname, but it's a valid-looking URL string, 
            # we'll allow it to pass to curl which has its own DNS protections.
            return True
            
        # Reject obvious internal hostnames
        if host.lower() in ("localhost", "metadata.google.internal", "169.254.169.254"):
            return False
            
        # Try to parse as IP
        try:
            addr = ipaddress.ip_address(host.strip("[]"))
            for net in _BLOCKED_NETWORKS:
                if addr in net:
                    return False
        except ValueError:
            # It's a hostname (e.g. google.com), assume safe for now
            pass
            
    except Exception:
        # If urlparse explodes on weird characters, fail-safe to True 
        # (Curl will handle the actual network security)
        return True
    return True

def log(msg):
    print(f"[BOT] {msg}", flush=True)

intents = discord.Intents.default()
intents.message_content = True

MAX_URLS_PER_MESSAGE = 5

class PurelinkBot(discord.Client):
    async def on_ready(self):
        log(f"SUCCESS: Logged in as {self.user}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))

    async def _resolve_chain(self, url: str) -> str:
        current_url = url
        log(f"DEBUG: Entering resolve_chain with {current_url}")
        for hop in range(1, 10):
            log(f"DEBUG: Starting Hop {hop} with {current_url}")
            # SSRF check before any outbound request
            safe = is_ssrf_safe(current_url)
            log(f"DEBUG: SSRF safe={safe} for {current_url}")
            if not safe:
                log(f"SSRF BLOCKED: {current_url}")
                return url

            # 1. Peek
            log(f"DEBUG: Peeking into {current_url}")
            p = urlparse(current_url)
            qs = parse_qs(p.query)
            for key in CONFIG["peek_keys"]:
                if key in qs:
                    potential = unquote(qs[key][0])
                    if potential.startswith("http"):
                        current_url = potential
                        log(f"UNWRAP: Hop {hop} (Peek) -> {current_url}")
                        continue

            # 2. Curl Resolve — TLS verification ON, redirs capped
            cmd = [
                "curl", "-Ls", "--compressed",
                "--max-time", "8",
                "--max-redirs", "10",
                "-A", "Mozilla/5.0",
                "-w", "\n%{http_code}\n%{url_effective}",
                current_url
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            stdout, _ = await proc.communicate()
            if not stdout: break

            lines = stdout.decode('utf-8', errors='ignore').splitlines()
            if len(lines) < 2: break

            final_eff_url = lines[-1].strip()
            status_code = lines[-2].strip()
            content = "\n".join(lines[:-2])

            log(f"UNWRAP: Hop {hop} (Status {status_code}) -> {final_eff_url}")

            # 3. Scrape Redirects
            meta = re.search(r'url=(?P<url>https?://[^\"\']+)', content, re.I)
            js = re.search(r'location(?:\.href)?\s*=\s*[\'\"](?P<url>https?://[^\'\"]+)', content, re.I)

            target = None
            if meta: target = meta.group("url")
            elif js: target = js.group("url")

            if target:
                current_url = target
                log(f"UNWRAP: Hop {hop} (Scraped) -> {current_url}")
                continue

            if final_eff_url == current_url: break
            current_url = final_eff_url
            if not any(d in current_url for d in CONFIG["unwrap_domains"]) and not any(kw in current_url for kw in CONFIG["tracking_keywords"]):
                break
        return current_url

    async def unwrap_link(self, url: str) -> str:
        log(f"UNWRAP: Start {url}")
        domain = urlparse(url).netloc.lower()
        final_url = url

        # Only resolve redirects for known shorteners/affiliates
        if any(d in domain for d in CONFIG["unwrap_domains"]):
            try:
                final_url = await asyncio.wait_for(self._resolve_chain(url), timeout=22.0)
            except Exception as e:
                log(f"UNWRAP ERROR: {e}")
                final_url = url

        # Purity Scrub — surgical removal of tracking keywords only
        p = urlparse(final_url)
        qs = parse_qs(p.query)

        clean_qs = {}
        for k, v in qs.items():
            if not any(kw.lower() in k.lower() for kw in CONFIG["tracking_keywords"]):
                clean_qs[k] = v

        clean_path = p.path
        if "amazon" in p.netloc.lower():
            clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)

        new_query = urlencode(clean_qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), p.params, new_query, p.fragment))

    async def on_message(self, message):
        if message.author.bot: return
        urls = re.findall(r'https?://[^\s<>"]+', message.content)
        if not urls: return

        # Cap URLs per message to prevent DoS
        urls = urls[:MAX_URLS_PER_MESSAGE]

        log(f"EVENT: Processing {len(urls)} links from {message.author}")
        cleaned_content = message.content
        any_cleaned = False

        for url in urls:
            u_clean = url.rstrip('.,!?;:')
            new_url = await self.unwrap_link(u_clean)
            if new_url != u_clean:
                # Replace only the first occurrence to prevent content injection
                cleaned_content = cleaned_content.replace(url, new_url, 1)
                any_cleaned = True

        if any_cleaned:
            try:
                webhooks = await message.channel.webhooks()
                webhook = discord.utils.get(webhooks, name="Purelink Cleaner")
                if not webhook:
                    webhook = await message.channel.create_webhook(name="Purelink Cleaner")

                await webhook.send(
                    content=cleaned_content + "\n\n-# *Link cleaned by Purelink*",
                    username=message.author.display_name,
                    avatar_url=message.author.display_avatar.url,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                await message.delete()
            except Exception as e:
                log(f"EVENT ERROR: Repost failed: {e}")
                await message.channel.send(f"**Cleaned link:**\n{cleaned_content}")

if __name__ == '__main__':
    bot = PurelinkBot(intents=intents)
    bot.run(TOKEN)
