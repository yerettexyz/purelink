import asyncio
import os
import re
import json
import discord
import time
import aiohttp
from prometheus_client import Counter, Gauge
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

load_dotenv()

# --- Metrics ---
LINKS_CLEANED = Counter('purelink_links_cleaned_total', 'Total links sanitized')
LINKS_DETECTED = Counter('purelink_links_detected_total', 'Total links found')
BOT_UPTIME = Gauge('purelink_uptime_seconds', 'Bot uptime in seconds')
START_TIME = time.time()

def log(msg):
    print(f"[BOT] {msg}", flush=True)

# Try to load private API plugin if exists
API_PLUGIN = None
if os.path.exists('api_plugin.py'):
    try:
        import api_plugin
        API_PLUGIN = api_plugin
    except: pass

TOKEN = os.getenv('TOKEN')
# Retrieve ALL configurations strictly from data.json
try:
    with open('data.json', 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
except Exception as e:
    log(f"FATAL ERROR: Could not load data.json - {e}")
    CONFIG = {"unwrap_domains": [], "tracking_keywords": [], "banned_domains": [], "unsupported_domains": []}


intents = discord.Intents.default()
intents.message_content = True

class PurelinkBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.processed_cache = {} # msg_id: timestamp
        self.session = None

    async def setup_hook(self):
        log(f"SUCCESS: Logged in as {self.user}")
        self.session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        if API_PLUGIN:
            metrics = {
                'LINKS_CLEANED': LINKS_CLEANED,
                'LINKS_DETECTED': LINKS_DETECTED,
                'LINKS_NUKED': Counter('dummy_nuke', 'nuke'),
                'HOPS_TOTAL': Counter('dummy_hops', 'hops'),
                'ERRORS_TOTAL': Counter('dummy_err', 'err'),
                'START_TIME': START_TIME,
                'PORT_PROM': 8000
            }
            try: self.loop.run_in_executor(None, API_PLUGIN.initialize_monitoring, metrics)
            except: pass
        self.loop.create_task(self.update_uptime())

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for tracking links"))
        log("STATUS: Bot is ready.")

    async def update_uptime(self):
        while not self.is_closed():
            BOT_UPTIME.set(time.time() - START_TIME)
            await asyncio.sleep(15)

    def unwrap_link(self, url):
        # STRTICT: If it's not a URL, return original
        if not url or not str(url).startswith("http"): return url
        try:
            p = urlparse(url)
            qs = parse_qs(p.query)
            clean_qs = {}
            for k, v in qs.items():
                if not any(kw.rstrip('=') in k.lower() for kw in CONFIG["tracking_keywords"]):
                    clean_qs[k] = v
            
            clean_path = p.path
            if "amazon" in p.netloc.lower():
                clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)
                
            new_query = urlencode(clean_qs, doseq=True)
            return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), p.params, new_query, p.fragment))
        except: return url

    async def _resolve_chain(self, url):
        if not self.session: return url
        try:
            async with self.session.get(url, allow_redirects=True, timeout=5) as resp:
                final_url = str(resp.url)
                # Shield: If too short or not HTTP, it's garbage. 
                if not final_url or len(final_url) < 15 or not final_url.startswith("http"):
                    return url
                return final_url
        except:
            return url

    async def on_message(self, message):
        if message.author.bot: return
        if message.id in self.processed_cache: return
        self.processed_cache[message.id] = time.time()

        urls = re.findall(r'https?://[^\s<>"]+', message.content)
        if not urls: return
        LINKS_DETECTED.inc(len(urls))

        cleaned_content = message.content
        any_cleaned = False
        log(f"TRACE: Processing message: {message.content[:50]}...")

        for url in urls:
            u_clean = url.rstrip('.,!?;:)]}>')
            domain = urlparse(u_clean).netloc.lower()
            log(f"TRACE: Found URL: {url} -> {u_clean}")
            
            if any(d in domain for d in CONFIG["unsupported_domains"]):
                log(f"TRACE: Skipping unsupported domain: {domain}")
                continue

            new_url = u_clean
            if any(d in domain for d in CONFIG["unwrap_domains"]) or any(kw in u_clean for kw in CONFIG["tracking_keywords"]):
                log(f"TRACE: Resolving {u_clean}...")
                new_url = await self._resolve_chain(u_clean)
                new_url = self.unwrap_link(new_url)
                log(f"TRACE: Resolved result: {new_url}")

            # STRICT REGEX SHIELD: Must be a valid URL
            if new_url and re.match(r'^https?://[^\s<>"]+$', str(new_url)) and new_url != u_clean:
                log(f"TRACE: APPLYING REPLACE: {url} -> {new_url}")
                cleaned_content = cleaned_content.replace(url, new_url, 1)
                any_cleaned = True
                LINKS_CLEANED.inc()
            else:
                log(f"TRACE: REJECTED: {new_url} (Matches http: {bool(re.match(r'^https?://', str(new_url)))}, Different: {new_url != u_clean})")

        if any_cleaned:
            if not cleaned_content.strip(): return
            try:
                await message.delete()
                webhooks = await message.channel.webhooks()
                webhook = discord.utils.get(webhooks, name="Purelink Cleaner")
                if not webhook: webhook = await message.channel.create_webhook(name="Purelink Cleaner")
                await webhook.send(
                    content=cleaned_content + "\n\n-# *Link cleaned by Purelink*",
                    username=message.author.display_name,
                    avatar_url=message.author.display_avatar.url if message.author.display_avatar else None,
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except:
                try: await message.channel.send(f"**Cleaned link(s) (PID {os.getpid()}):**\n{cleaned_content}")
                except: pass

if __name__ == '__main__':
    bot = PurelinkBot(intents=intents)
    bot.run(TOKEN)
