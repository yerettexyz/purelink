import asyncio
import os
import re
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dotenv import load_dotenv
from unalix import clear_url
from prometheus_client import start_http_server, Summary, Counter, Gauge

# Import curl_cffi for the ultimate Cloudflare bypass
try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import httpx

# Purelink Discord Bot
# Original Copyright (c) Daniel Ting
# Modifications Copyright (c) 2024 psalm2517 (Purelink Team)
# Licensed under LGPL-3.0

# Configuration
UNWRAP_DOMAINS = [
    "mavely.app", "joinmavely.com", "mavelylife.com", 
    "mavely.app.link", "go.mavely.app", 
    "amzn.to", "a.co", "bit.ly", "tinyurl.com"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "ref=", "aff_", "mc_cid", "mc_eid", "tag="]
SEARCH_KEEPERS = ['k', 'q', 'query', 'srs', 'bbn', 'rh', 'i', 'p_36']
URL_REGEX = re.compile(r'(?P<url>https?://[^\s]+)')

intents = discord.Intents.all()
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Follows redirects using curl_cffi to spoof TLS fingerprints and bypass Cloudflare."""
    
    final_url = url
    
    if HAS_CURL_CFFI:
        # ULTIMATE STEALTH: Spoofing Chrome 120 TLS fingerprint
        async with AsyncSession(impersonate="chrome120") as s:
            try:
                print(f"[DEBUG] Impersonating Chrome for: {url}")
                resp = await s.get(url, follow_redirects=True, timeout=15)
                final_url = str(resp.url)
                
                # Check for Meta Refresh in the stealth response
                meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', resp.text, re.I)
                if meta_match:
                    final_url = await unwrap_link(meta_match.group("url"))
            except Exception as e:
                print(f"[DEBUG] Stealth resolution failed: {e}")
    else:
        # Fallback to standard httpx if library is missing
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as httpx_client:
            try:
                resp = await httpx_client.get(url)
                final_url = str(resp.url)
            except:
                pass

    # Smart Purity Logic
    p = urlparse(final_url)
    if p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query:
        return clear_url(final_url)
    else:
        if p.scheme and p.netloc:
            return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        return final_url

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))
    print(f'Purelink is logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

    urls = URL_REGEX.findall(message.content)
    if not urls:
        return

    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        should_unwrap = any(domain in url for domain in UNWRAP_DOMAINS)
        is_tracking_kw = any(kw in url.lower() for kw in TRACKING_KEYWORDS)
        
        if should_unwrap or is_tracking_kw:
            print(f"[DEBUG] Processing: {url}")
            new_url = await unwrap_link(url)
            
            if new_url != url or should_unwrap:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True
                print(f"[DEBUG] -> Final: {new_url}")

    if any_cleaned:
        try:
            webhooks = await message.channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Purelink Cleaner")
            if not webhook:
                webhook = await message.channel.create_webhook(name="Purelink Cleaner")

            await webhook.send(
                content=cleaned_content + "\n\n*Link cleaned by Purelink*",
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await message.delete()
        except Exception as e:
            await message.reply(f"Link cleaned by Purelink:\n{cleaned_content}", mention_author=False)
            print(f"[DEBUG] Webhook error: {e}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')
    start_http_server(int(os.getenv('METRICS_PORT', 8000)))
    client.run(token)
