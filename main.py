import asyncio
import os
import re
import httpx
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv
from unalix import clear_url
from prometheus_client import start_http_server, Summary, Counter, Gauge

# Purelink Discord Bot
# Production Version 1.3.0
# Copyright (c) 2024 Purelink Team

# Core Configuration
UNWRAP_DOMAINS = [
    "mavely.app", "joinmavely.com", "mavelylife.com", "mavelyinfluencer.com",
    "mavely.app.link", "go.mavely.app", 
    "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "link.lordofsavings.com", "link.tdgdeals.com", "pricedoffers.com",
    "ojrq.net", "sjv.io", "impactradius", "rstyle.me", "gotrackier.com"
]

TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "ref=", "aff_", "mc_cid", "mc_eid", "tag="]
REDIRECT_KEYS = ["return", "url", "dest", "destination", "u", "q", "redirect", "redirect_url"]

# Expanded SEARCH_KEEPERS
SEARCH_KEEPERS = [
    'k', 'q', 'query', 'srs', 'bbn', 'rh', 'i', 'p_36', 
    'rnid', 'crid', 'low-price', 'high-price', 'sprefix'
]
URL_REGEX = re.compile(r'(?P<url>https?://[^\s]+)')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Intents: Using all() to ensure full compatibility with modern Discord requirements
intents = discord.Intents.all()
client = discord.Client(intents=intents)

# Metrics
process_message_time = Summary('process_message_time', 'Time spent processing message')
messages = Counter('messages', 'Total number of messages processed')
cleaned_messages = Counter('cleaned_messages', 'Number of messages with tracking links cleaned')
servers = Gauge('servers', 'Number of servers the bot is in')

async def update_metrics():
    while True:
        servers.set(len(client.guilds))
        await asyncio.sleep(60)

async def unwrap_link(url: str) -> str:
    """Follows redirects through multiple hops, with deep query-parameter peeking."""
    
    p_init = urlparse(url)
    final_url = urlunparse((p_init.scheme, p_init.netloc, p_init.path, '', '', ''))

    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=15, 
        headers=HEADERS, 
        timeout=20.0
    ) as httpx_client:
        hops = 0
        current_url = url
        
        while hops < 15:
            try:
                # STEP 1: Deep Peeking (Bypasses Cloudflare 403)
                # Check if the next URL is already in the query parameters
                p_current = urlparse(current_url)
                qs = parse_qs(p_current.query)
                found_in_query = False
                
                for key in REDIRECT_KEYS:
                    if key in qs:
                        potential_url = qs[key][0]
                        if potential_url.startswith("http"):
                            current_url = unquote(potential_url)
                            final_url = current_url
                            found_in_query = True
                            break
                
                if found_in_query:
                    hops += 1
                    continue

                # STEP 2: Standard Request
                response = await httpx_client.get(current_url)
                current_url = str(response.url)
                final_url = current_url
                
                # Check for Meta Refresh
                if response.status_code == 200:
                    meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', response.text, re.I)
                    if meta_match:
                        current_url = meta_match.group("url")
                        hops += 1
                        continue

                # Stop if we hit a non-tracking domain
                has_tracking = any(kw in current_url.lower() for kw in TRACKING_KEYWORDS)
                is_known_shortener = any(d in p_current.netloc for d in UNWRAP_DOMAINS)
                
                if not (has_tracking or is_known_shortener):
                    break
            except:
                break
            hops += 1
        
    # Apply Final Purity Logic
    p = urlparse(final_url)
    is_search = p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query
    
    if is_search:
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        if clean_qs:
            new_query = urlencode(clean_qs, doseq=True)
            return urlunparse((p.scheme, p.netloc, p.path, '', new_query, ''))
        else:
            return clear_url(final_url).strip('&')
    else:
        if p.scheme and p.netloc:
            # Full strip for product pages
            return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        return final_url

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))
    asyncio.create_task(update_metrics())
    print(f'Purelink is ready and logged in as {client.user}')

@process_message_time.time()
@client.event
async def on_message(message):
    print(f"[DEBUG] Heartbeat: Received message from {message.author}")
    if message.author.bot:
        return

    urls = URL_REGEX.findall(message.content)
    if not urls:
        return

    messages.inc()
    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        standard_cleaned = clear_url(url).strip('&')
        is_affiliate = any(domain in url for domain in UNWRAP_DOMAINS)
        is_tracking = any(kw in url.lower() for kw in TRACKING_KEYWORDS)
        
        if standard_cleaned != url.strip('&') or is_affiliate or is_tracking:
            new_url = await unwrap_link(url)
            if new_url != url:
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
            cleaned_messages.inc()
        except:
            await message.channel.send(f"Cleaned link:\n{cleaned_content}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')
    metrics_port = int(os.getenv('METRICS_PORT', 8000))
    
    if not token:
        print("Error: TOKEN not found in .env")
    else:
        start_http_server(metrics_port)
        client.run(token)
