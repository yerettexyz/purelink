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
    """Follows redirects with a backup to third-party unshorteners if blocked."""
    
    # Check if it's a known problematic Mavely link
    is_mavely = any(d in url for d in ["mavely.app", "mavelylife.com"])
    
    if is_mavely:
        # FAILOVER: Use a third-party unshortener to bypass IP blocks on Oracle Cloud
        # unshorten.me is a reliable public API for this
        try:
            async with httpx.AsyncClient(timeout=15.0) as unshorten_client:
                print(f"[DEBUG] Using failover for Mavely link: {url}")
                resp = await unshorten_client.get(f"https://unshorten.me/s/{url}")
                if resp.status_code == 200 and "unshorten.me" not in resp.text:
                    url = resp.text.strip()
                    print(f"[DEBUG] Failover Success: {url}")
                    # If we got the store URL, go to purity logic immediately
                    p = urlparse(url)
                    if any(d in p.netloc for d in UNWRAP_DOMAINS):
                        pass # Keep resolving if it's still an affiliate domain
                    else:
                        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        except Exception as e:
            print(f"[DEBUG] Failover error: {e}")

    # Standard resolution for everything else
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
        last_url = url
        
        while hops < 15:
            try:
                response = await httpx_client.get(current_url)
                
                # Check for Meta Refresh / JS
                patterns = [
                    r'window\.location\.replace\(["\'](?P<url>https?://[^"\']+)["\']\)',
                    r'content=["\']\d+;\s*url=(?P<url>https?://[^"\']+)["\']',
                ]
                
                found_hidden = False
                for pattern in patterns:
                    match = re.search(pattern, response.text, re.I)
                    if match:
                        current_url = match.group("url")
                        found_hidden = True
                        break
                
                if found_hidden:
                    hops += 1
                    continue

                if response.status_code != 200 and response.status_code != 301 and response.status_code != 302:
                    break

                last_url = current_url
                current_url = str(response.url)
                
                parsed_final = urlparse(current_url)
                if not any(d in parsed_final.netloc for d in UNWRAP_DOMAINS):
                    break
                    
            except Exception:
                break
            hops += 1
        
        final_url = current_url

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
    print(f"[DEBUG] Heartbeat: Message from {message.author}")
    if message.author.bot:
        return

    urls = URL_REGEX.findall(message.content)
    if not urls:
        return

    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        standard_cleaned = clear_url(url).strip('&')
        should_unwrap = any(domain in url for domain in UNWRAP_DOMAINS)
        is_tracking_kw = any(kw in url.lower() for kw in TRACKING_KEYWORDS)
        
        if standard_cleaned != url.strip('&') or should_unwrap or is_tracking_kw:
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
