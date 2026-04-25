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

# High-fidelity Human Headers
HUMAN_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

intents = discord.Intents.all()
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Follows redirects with deep stealth and advanced regex scraping for 403 bypass."""
    
    final_url = url
    # We explicitly DISABLE http2 here as some Cloudflare configs block the httpx http2 fingerprint
    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=15, 
        cookies=httpx.Cookies(),
        http2=False, 
        timeout=15.0
    ) as httpx_client:
        hops = 0
        current_url = url
        last_url = url
        
        while hops < 15:
            try:
                headers = {
                    "User-Agent": random.choice(HUMAN_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                }
                if hops > 0:
                    headers["Referer"] = last_url
                
                response = await httpx_client.get(current_url, headers=headers)
                
                # Check for Meta Refresh / JS redirectors even if 200 or 403
                # (Some bot-blocks still include the target URL in a JS variable)
                patterns = [
                    r'window\.location\.replace\(["\'](?P<url>https?://[^"\']+)["\']\)',
                    r'window\.location\.href\s*=\s*["\'](?P<url>https?://[^"\']+)["\']',
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
                    print(f"[DEBUG] Stop at {current_url} (Status {response.status_code})")
                    break

                last_url = current_url
                current_url = str(response.url)
                
                parsed_final = urlparse(current_url)
                is_still_shortener = any(d in parsed_final.netloc for d in UNWRAP_DOMAINS)
                if not is_still_shortener:
                    break
                    
            except Exception as e:
                print(f"[DEBUG] Error: {e}")
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
