import asyncio
import os
import re
import httpx
import discord
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

# High-fidelity Mobile Headers (often bypasses stricter bot filters)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

intents = discord.Intents.all()
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Follows redirects with deep stealth and error handling for 403s."""
    
    final_url = url
    # Use a session-like client to maintain cookies
    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=15, 
        headers=HEADERS, 
        cookies=httpx.Cookies(),
        http2=True,
        timeout=15.0
    ) as httpx_client:
        hops = 0
        current_url = url
        last_url = url
        
        while hops < 15:
            try:
                # Add Referer for every hop to look like a real user chain
                custom_headers = HEADERS.copy()
                if hops > 0:
                    custom_headers["Referer"] = last_url
                
                response = await httpx_client.get(current_url, headers=custom_headers)
                
                # Check for 403 - try to scrape the target from the body if possible
                if response.status_code == 403:
                    print(f"[DEBUG] Mavely Blocked (403) at {current_url}")
                    # Some sites include the target as a JS variable even on blocked/wait pages
                    js_match = re.search(r'window\.location\.replace\(["\'](?P<url>https?://[^"\']+)["\']\)', response.text)
                    if js_match:
                        current_url = js_match.group("url")
                        hops += 1
                        continue
                    break

                last_url = current_url
                current_url = str(response.url)
                
                # Check for Meta Refresh in body
                meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', response.text, re.I)
                if meta_match:
                    current_url = meta_match.group("url")
                    hops += 1
                    continue 

                # If no more redirects and no more meta-refreshes, we're likely at the store
                parsed_final = urlparse(current_url)
                is_still_shortener = any(d in parsed_final.netloc for d in UNWRAP_DOMAINS)
                if not is_still_shortener:
                    break
                    
            except Exception as e:
                print(f"[DEBUG] Resolution error at hop {hops}: {e}")
                break
            hops += 1
        
        final_url = current_url

    # Smart Purity Logic
    p = urlparse(final_url)
    if p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query:
        return clear_url(final_url)
    else:
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))

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
            print(f"[DEBUG] Processing Link: {url}")
            new_url = await unwrap_link(url)
            
            if new_url != url or should_unwrap:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True
                print(f"[DEBUG] -> Cleaned to: {new_url}")

    if any_cleaned:
        permissions = message.channel.permissions_for(message.guild.me)
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
            # Fallback to simple reply if webhook fails
            await message.reply(f"Link cleaned by Purelink:\n{cleaned_content}", mention_author=False)
            print(f"[DEBUG] Webhook error: {e}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')
    start_http_server(int(os.getenv('METRICS_PORT', 8000)))
    client.run(token)
