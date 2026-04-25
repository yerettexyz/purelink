import asyncio
import os
import re
import sys
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink - Global Resolve Edition
# Enhanced curl handling with status code tracking and compression.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely", "joinmavely", "mavelyinfluencer.com", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "lordofsavings", "tdgdeals", "pricedoffers", "ojrq.net", "sjv.io", "rstyle.me",
    "link.profitlounge.us", "howl.link", "jdoqocy.com", "sylikes.com", "bizrate.com", 
    "pricingerrors.com", "t.co", "amazon.com", "ebay.com", "walmart.com"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag=", "linkId=", "ref="]
PEEK_KEYS = ["return", "url", "dest", "destination", "u", "q", "redirect", "redirect_url", "murl"]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price', 'sprefix']

def log(msg):
    print(f"[BOT] {msg}", flush=True)

intents = discord.Intents.default()
intents.message_content = True

class PurelinkBot(discord.Client):
    async def on_ready(self):
        log(f"SUCCESS: Logged in as {self.user}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))

    async def unwrap_link(self, url: str) -> str:
        current_url = url
        log(f"UNWRAP: Start {url}")
        
        try:
            async with asyncio.timeout(15.0):
                for hop in range(1, 10):
                    # 1. Peek
                    p = urlparse(current_url)
                    qs = parse_qs(p.query)
                    for key in PEEK_KEYS:
                        if key in qs:
                            potential = unquote(qs[key][0])
                            if potential.startswith("http"):
                                current_url = potential
                                log(f"UNWRAP: Hop {hop} (Peek) -> {current_url}")
                                continue
                    
                    # 2. Curl Resolve (Stealth)
                    cmd = [
                        "curl", "-Ls", "--compressed", "--max-time", "8", "-k",
                        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
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

                    # Check Meta Refresh
                    meta = re.search(r'url=(?P<url>https?://[^"\']+)', content, re.I)
                    if meta:
                        current_url = meta.group("url")
                        continue
                        
                    if final_eff_url == current_url: break
                    current_url = final_eff_url
                    
                    if not any(d in current_url for d in UNWRAP_DOMAINS) and not any(kw in current_url for kw in TRACKING_KEYWORDS):
                        break
        except Exception as e:
            log(f"UNWRAP ERROR: {e}")
            
        # Purity Scrub
        p = urlparse(current_url)
        clean_path = p.path
        if "amazon" in p.netloc.lower():
            clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)
            
        if any(k in clean_path for k in ['/s', '/search']) or 'k=' in p.query:
            qs = parse_qs(p.query)
            clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
            return urlunparse((p.scheme, p.netloc, clean_path, '', urlencode(clean_qs, doseq=True), ''))
        else:
            return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), '', '', ''))

    async def on_message(self, message):
        if message.author.bot: return
        
        urls = re.findall(r'https?://[^\s<>"]+', message.content)
        if not urls: return

        log(f"EVENT: Processing {len(urls)} links from {message.author}")
        cleaned_content = message.content
        any_cleaned = False

        for url in urls:
            u_clean = url.rstrip('.,!?;:')
            is_track = any(k in u_clean.lower() for k in TRACKING_KEYWORDS)
            is_aff = any(d in u_clean.lower() for d in UNWRAP_DOMAINS)

            if is_track or is_aff:
                new_url = await self.unwrap_link(u_clean)
                # Important: Repost if the link changed OR it's a known affiliate domain
                if new_url != u_clean or is_aff:
                    cleaned_content = cleaned_content.replace(url, new_url)
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
    token = os.getenv('TOKEN')
    bot.run(token)
