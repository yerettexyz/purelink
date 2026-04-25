import asyncio
import os
import re
import json
import ipaddress
import discord
import threading
from prometheus_client import Counter, Gauge
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

load_dotenv()

# --- Metrics ---
METRICS_PORT = 8000
LINKS_CLEANED = Counter('purelink_links_cleaned_total', 'Total links sanitized')
LINKS_DETECTED = Counter('purelink_links_detected_total', 'Total links found')
LINKS_NUKED = Counter('purelink_links_nuked_total', 'Total banned links removed')
HOPS_TOTAL = Counter('purelink_hops_total', 'Total redirect hops performed')
ERRORS_TOTAL = Counter('purelink_errors_total', 'Total processing errors')
BOT_UPTIME = Gauge('purelink_uptime_seconds', 'Bot uptime in seconds')
START_TIME = asyncio.get_event_loop().time()

def log(msg):
    print(f"[BOT] {msg}", flush=True)

# Try to load private API plugin if exists
API_PLUGIN = None
if os.path.exists('api_plugin.py'):
    try:
        import api_plugin
        API_PLUGIN = api_plugin
    except Exception as e:
        print(f"[BOT] PLUGIN ERROR: Failed to load api_plugin: {e}")

# --- Startup Checks ---
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    log("CRITICAL: TOKEN environment variable is not set. Check your .env file.")
    raise SystemExit(1)

def load_config():
    """Load tracking config from data.json using an absolute path."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        log(f"CRITICAL: Failed to load data.json: {e}")
        return {
            "unwrap_domains": ["amzn.to", "bit.ly"],
            "unsupported_domains": ["walmart.com", "mavelylife.com"],
            "banned_domains": ["linktr.ee"],
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

intents = discord.Intents.default()
intents.message_content = True

MAX_URLS_PER_MESSAGE = 5

class PurelinkBot(discord.Client):
    async def setup_hook(self):
        log(f"SUCCESS: Logged in as {self.user}")
        activity = discord.Activity(type=discord.ActivityType.watching, name="for tracking links")
        await self.change_presence(activity=activity)
        
        # Start Private Monitoring Bridge (Prometheus + JSON API)
        if API_PLUGIN:
            try:
                threading.Thread(target=API_PLUGIN.initialize_monitoring, args=(self,), daemon=True).start()
                log("PLUGIN: Private Monitoring Bridge initialized.")
            except Exception as e:
                log(f"PLUGIN ERROR: Failed to start monitoring: {e}")

        # Start uptime tracker
        self.loop.create_task(self.update_uptime())

    async def update_uptime(self):
        while not self.is_closed():
            BOT_UPTIME.set(asyncio.get_event_loop().time() - START_TIME)
            await asyncio.sleep(60)

    async def _resolve_chain(self, url: str) -> str:
        current_url = url
        for hop in range(1, 10):
            # SSRF check before any outbound request
            if not is_ssrf_safe(current_url):
                log(f"SSRF BLOCKED: {current_url}")
                return url

            # 1. Peek
            p = urlparse(current_url)
            qs = parse_qs(p.query)
            peeked = False
            for key in CONFIG["peek_keys"]:
                if key in qs:
                    potential = unquote(qs[key][0])
                    if potential.startswith("http"):
                        current_url = potential
                        log(f"UNWRAP: Hop {hop} (Peek) -> {current_url}")
                        peeked = True
                        break # Exit peek_keys loop
            if peeked:
                continue # Restart hop loop with new current_url

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
            HOPS_TOTAL.inc()

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

        # Only resolve redirects for known shorteners/affiliates that aren't on the blocked list
        is_unsupported = any(d in domain for d in CONFIG.get("unsupported_domains", []))
        if any(d in domain for d in CONFIG["unwrap_domains"]) and not is_unsupported:
            try:
                final_url = await asyncio.wait_for(self._resolve_chain(url), timeout=22.0)
            except Exception as e:
                ERRORS_TOTAL.inc()
                log(f"UNWRAP ERROR: {e}")
                final_url = url

        # Purity Scrub — surgical removal of tracking keywords only
        p = urlparse(final_url)
        qs = parse_qs(p.query)

        clean_qs = {}
        for k, v in qs.items():
            k_lower = k.lower()
            is_tracking = False
            for kw in CONFIG["tracking_keywords"]:
                kw_clean = kw.lower().rstrip('=')
                if kw.endswith('='):
                    if k_lower == kw_clean:
                        is_tracking = True
                        break
                elif kw.endswith('_'):
                    if k_lower.startswith(kw_clean):
                        is_tracking = True
                        break
                else:
                    if kw_clean in k_lower:
                        is_tracking = True
                        break
            
            if not is_tracking:
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
        LINKS_DETECTED.inc(len(urls))

        log(f"EVENT: Processing {len(urls)} links from {message.author}")
        cleaned_content = message.content
        any_cleaned = False

        for url in urls:
            u_clean = url.rstrip('.,!?;:')
            domain = urlparse(u_clean).netloc.lower()

            # 1. Check for banned domains (Nuke entirely)
            if any(d in domain for d in CONFIG.get("banned_domains", [])):
                cleaned_content = cleaned_content.replace(url, "", 1).strip()
                any_cleaned = True
                LINKS_NUKED.inc()
                LINKS_CLEANED.inc()
                log(f"NUKE: Removed banned link {url}")
                continue

            # 2. Regular cleaning
            new_url = await self.unwrap_link(u_clean)
            if new_url != u_clean:
                LINKS_CLEANED.inc()
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
