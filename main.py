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

# --- Instance Lock ---
PID_FILE = "bot.pid"
if os.path.exists(PID_FILE):
    try:
        with open(PID_FILE, "r") as f:
            old_pid = int(f.read().strip())
        os.kill(old_pid, 0) # Check if process exists
        print(f"FATAL ERROR: Another instance is running (PID {old_pid}). Exit.", flush=True)
        os._exit(1)
    except (ProcessLookupError, ValueError):
        pass # Process is dead, continue
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

# --- Metrics ---
LINKS_CLEANED = Counter('purelink_links_cleaned_total', 'Total links sanitized')
LINKS_DETECTED = Counter('purelink_links_detected_total', 'Total links found')
LINKS_NUKED = Counter('purelink_links_nuked_total', 'Total links removed (banned)')
HOPS_TOTAL = Counter('purelink_hops_total', 'Total URL redirects resolved')
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
                'LINKS_NUKED': LINKS_NUKED,
                'HOPS_TOTAL': HOPS_TOTAL,
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
        if not url or not str(url).startswith("http"): return url
        try:
            p = urlparse(url)
            qs = parse_qs(p.query)
            clean_qs = {}
            for k, v in qs.items():
                if not any(kw.lower() in k.lower() for kw in CONFIG.get("tracking_keywords", [])):
                    clean_qs[k] = v
            
            clean_path = p.path
            if "amazon" in p.netloc.lower():
                clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)
                
            new_query = urlencode(clean_qs, doseq=True)
            return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), p.params, new_query, p.fragment))
        except: return url

    async def _resolve_chain(self, url):
        def _fetch(u):
            import urllib.request
            import urllib.error
            from urllib.parse import urljoin
            
            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            
            opener = urllib.request.build_opener(NoRedirectHandler)
            curr_url = u
            visited = {u}
            hops = 0
            
            for _ in range(15): # Max 15 hops
                if not any(curr_url.startswith(p) for p in ['http://', 'https://']):
                    return curr_url, hops
                
                # Fast-exit ONLY for banned domains
                if any(bd in curr_url.lower() for bd in self.banned_domains):
                    return curr_url, hops

                try:
                    req = urllib.request.Request(curr_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with opener.open(req, timeout=4) as response:
                        if response.status in [301, 302, 303, 307, 308]:
                            new_url = response.headers.get('Location')
                            if not new_url: return curr_url, hops
                            if new_url.startswith('/'):
                                new_url = urljoin(curr_url, new_url)
                            if new_url in visited: return curr_url, hops
                            curr_url = new_url
                            visited.add(curr_url)
                            hops += 1
                        else:
                            return curr_url, hops
                except urllib.error.HTTPError as e:
                    if e.code in [301, 302, 303, 307, 308]:
                        new_url = e.headers.get('Location')
                        if not new_url: return curr_url, hops
                        if new_url.startswith('/'):
                            new_url = urljoin(curr_url, new_url)
                        if new_url in visited: return curr_url, hops
                        curr_url = new_url
                        visited.add(curr_url)
                        hops += 1
                    else:
                        return curr_url, hops
                except:
                    return curr_url, hops
            return curr_url, hops

        try:
            res_url, hop_count = await self.loop.run_in_executor(None, _fetch, url)
            if hop_count > 0:
                HOPS_TOTAL.inc(hop_count)
            return res_url
        except: return url

    async def on_message(self, message):
        if message.author.bot: return
        if message.id in self.processed_cache: return
        self.processed_cache[message.id] = time.time()

        urls = re.findall(r'https?://[^\s<>"]+', message.content)
        if not urls: return
        log(f"[DEBUG] Processing {len(urls)} URLs from {message.author.name}")
        LINKS_DETECTED.inc(len(urls))

        cleaned_content = message.content
        any_cleaned = False

        for url in urls:
            u_clean = url.rstrip('.,!?;:)]}>')
            domain = urlparse(u_clean).netloc.lower()
            log(f"[DEBUG] Checking domain: {domain}")
            
            if any(d in domain for d in CONFIG.get("unsupported_domains", [])):
                log(f"[DEBUG] Skipping unsupported domain: {domain}")
                continue

            # 1. Resolve redirects
            target_url = u_clean
            if any(d in domain for d in CONFIG.get("unwrap_domains", [])) or any(kw in u_clean for kw in CONFIG.get("tracking_keywords", [])):
                target_url = await self._resolve_chain(u_clean)
            
            # 2. Strip tracking from final link
            new_url = self.unwrap_link(target_url)

            # 3. Check for Banned Domains (Total Nuke)
            is_banned = any(d in target_url.lower() or d in domain for d in CONFIG.get("banned_domains", []))

            # 4. Apply change if cleaned or unwrapped
            if is_banned:
                continue # Skip banned domains, leave them in the original text
            
            if new_url and new_url != u_clean:
                cleaned_content = cleaned_content.replace(url, new_url, 1)
                any_cleaned = True
                LINKS_CLEANED.inc()

        if any_cleaned:
            # Clean up whitespace if we removed a whole link
            cleaned_content = re.sub(r' +', ' ', cleaned_content).strip()
            if not cleaned_content: 
                # If nothing is left, just delete the original and don't repost
                try: await message.delete()
                except: pass
                return

            try:
                # Nuke and Repost
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
            except Exception as e:
                # Fallback if nuke/webhook fails
                try: await message.channel.send(f"**Cleaned link(s):**\n{cleaned_content}")
                except: pass



if __name__ == '__main__':
    bot = PurelinkBot(intents=intents)
    bot.run(TOKEN)
