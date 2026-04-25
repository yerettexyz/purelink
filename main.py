import asyncio
import os
import re
import httpx
import discord
import random
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dotenv import load_dotenv
from unalix import clear_url
from prometheus_client import start_http_server, Summary, Counter, Gauge

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
}

intents = discord.Intents.all()
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Follows redirects with multiple failovers for tough-to-crack affiliate links."""
    
    is_mavely = any(d in url for d in ["mavely.app", "mavelylife.com"])
    
    if is_mavely:
        # Multi-Stage Failover for Mavely (Bypasses IP blocks)
        # Service 1: unshorten.me
        # Service 2: expandurl.net (Scraped)
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as unshorten_client:
                # Attempt 1: unshorten.me
                resp = await unshorten_client.get(f"https://unshorten.me/s/{url}")
                if resp.status_code == 200 and "Unknown Error" not in resp.text and "unshorten.me" not in resp.text:
                    decoded = resp.text.strip()
                    if "http" in decoded:
                        print(f"[DEBUG] Failover 1 (unshorten.me) Success")
                        return await finalize_url(decoded)

                # Attempt 2: expandurl.net (Scraping the result)
                resp = await unshorten_client.get(f"https://www.expandurl.net/expand?url={url}")
                if resp.status_code == 200:
                    # Look for the long URL in the page source
                    match = re.search(r'id="longest-url"[^>]*>(?P<url>https?://[^<]+)</a>', resp.text)
                    if match:
                        print(f"[DEBUG] Failover 2 (expandurl.net) Success")
                        return await finalize_url(match.group("url"))
        except Exception as e:
            print(f"[DEBUG] Failover failed: {e}")

    # Standard resolution for everything else (Amazon, etc.)
    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=15, 
        headers=HEADERS, 
        cookies=httpx.Cookies(),
        http2=False,
        timeout=15.0
    ) as httpx_client:
        hops = 0
        current_url = url
        while hops < 15:
            try:
                response = await httpx_client.get(current_url)
                current_url = str(response.url)
                
                # Check for Meta Refresh
                meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', response.text, re.I)
                if meta_match:
                    current_url = meta_match.group("url")
                    hops += 1
                    continue

                if response.status_code != 200:
                    break
                
                parsed_final = urlparse(current_url)
                if not any(d in parsed_final.netloc for d in UNWRAP_DOMAINS):
                    break
            except Exception:
                break
            hops += 1
        return await finalize_url(current_url)

async def finalize_url(url: str) -> str:
    """Applies smart purity logic to the final resolved URL."""
    p = urlparse(url)
    if p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query:
        return clear_url(url)
    else:
        if p.scheme and p.netloc:
            return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        return url

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
