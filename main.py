import asyncio
import os
import re
import json
import discord
import time
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
    import api_plugin
    API_PLUGIN = api_plugin

TOKEN = os.getenv('TOKEN')
CONFIG = {
    "unwrap_domains": ["bit.ly", "t.co", "tinyurl.com", "amzn.to", "a.co"],
    "tracking_keywords": ["aff_", "utm_", "ref_", "click_id", "tag="],
    "banned_domains": ["discord.gg", "discord.com/invite"]
}

intents = discord.Intents.default()
intents.message_content = True

class PurelinkBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.processed_cache = {} # msg_id: timestamp

    async def setup_hook(self):
        log(f"SUCCESS: Logged in as {self.user}")
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
            self.loop.run_in_executor(None, API_PLUGIN.initialize_monitoring, metrics)
            log("PLUGIN: Private Monitoring Bridge initialized.")
        self.loop.create_task(self.update_uptime())

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for tracking links"))
        log("STATUS: Bot is ready.")

    async def update_uptime(self):
        while not self.is_closed():
            BOT_UPTIME.set(time.time() - START_TIME)
            await asyncio.sleep(15)

    def unwrap_link(self, url):
        p = urlparse(url)
        qs = parse_qs(p.query)
        clean_qs = {}
        for k, v in qs.items():
            if not any(kw in k.lower() for kw in CONFIG["tracking_keywords"]):
                clean_qs[k] = v
        
        clean_path = p.path
        if "amazon" in p.netloc.lower():
            clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)
            
        new_query = urlencode(clean_qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), p.params, new_query, p.fragment))

    async def _resolve_chain(self, url):
        current_url = url
        for _ in range(5):
            cmd = ["curl", "-sI", "-L", "-m", "5", "-w", "%{url_effective}", current_url]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            stdout, _ = await proc.communicate()
            if not stdout: break
            new_url = stdout.decode().strip().split('\n')[-1]
            if new_url == current_url: break
            current_url = new_url
        return current_url

    async def on_message(self, message):
        if message.author.bot: return
        
        # Anti-Triple Response Protection
        if message.id in self.processed_cache: return
        self.processed_cache[message.id] = time.time()

        urls = re.findall(r'https?://[^\s<>"]+', message.content)
        if not urls: return
        LINKS_DETECTED.inc(len(urls))

        cleaned_content = message.content
        any_cleaned = False

        for url in urls:
            u_clean = url.rstrip('.,!?;:)]}>')
            domain = urlparse(u_clean).netloc.lower()
            
            # Simple resolve and clean
            new_url = u_clean
            if any(d in domain for d in CONFIG["unwrap_domains"]) or any(kw in u_clean for kw in CONFIG["tracking_keywords"]):
                new_url = await self._resolve_chain(u_clean)
                new_url = self.unwrap_link(new_url)

            if new_url != u_clean:
                cleaned_content = cleaned_content.replace(url, new_url, 1)
                any_cleaned = True
                LINKS_CLEANED.inc()

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
                await message.channel.send(f"**Cleaned link(s):**\n{cleaned_content}")

if __name__ == '__main__':
    bot = PurelinkBot()
    bot.run(TOKEN)
