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
# Production Version
# Copyright (c) 2024 Purelink Team

# Core Configuration
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

# Intents
intents = discord.Intents.default()
intents.message_content = True
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
    """Follows redirects where possible; falls back to 'naked' links for guarded domains."""
    
    p_init = urlparse(url)
    # Default 'clean' link is just the original link without query parameters or fragments
    final_url = urlunparse((p_init.scheme, p_init.netloc, p_init.path, '', '', ''))

    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=10, 
        headers=HEADERS, 
        timeout=10.0
    ) as httpx_client:
        try:
            response = await httpx_client.get(url)
            if response.status_code == 200:
                final_url = str(response.url)
                
                # Check for standard HTML Meta Refresh
                meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', response.text, re.I)
                if meta_match:
                    # Resolve the meta link once
                    meta_url = meta_match.group("url")
                    meta_resp = await httpx_client.get(meta_url)
                    final_url = str(meta_resp.url)
        except:
            # If resolution fails (403, timeout, etc.), we stick with the naked URL version
            pass

    # Apply Purity Logic
    p = urlparse(final_url)
    # If it's a search page, use mild cleaning (preserves keywords k, q, etc.)
    if p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query:
        return clear_url(final_url)
    else:
        # If it's a product or general page, strip all parameters for Total Purity
        if p.scheme and p.netloc:
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
    if message.author.bot:
        return

    urls = URL_REGEX.findall(message.content)
    if not urls:
        return

    messages.inc()
    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        # Check if the URL needs cleaning (unalix difference, affiliate domain, or tracking keywords)
        standard_cleaned = clear_url(url).strip('&')
        is_affiliate = any(domain in url for domain in UNWRAP_DOMAINS)
        is_tracking = any(kw in url.lower() for kw in TRACKING_KEYWORDS)
        
        if standard_cleaned != url.strip('&') or is_affiliate or is_tracking:
            new_url = await unwrap_link(url)
            
            # If the URL changed OR was an affiliate link (which we wanted to sanitize anyway)
            if new_url != url or is_affiliate:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True

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
            cleaned_messages.inc()
        except:
            # Silent fallback to non-webhook if permissions missing
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
