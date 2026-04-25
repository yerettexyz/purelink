import asyncio
import os
import re
import httpx
import discord
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
from unalix import clear_url
from prometheus_client import start_http_server, Summary, Counter, Gauge

# Purelink Discord Bot
# Original Copyright (c) Daniel Ting
# Modifications Copyright (c) 2024 psalm2517 (Purelink Team)
# Licensed under LGPL-3.0

# Purelink Configuration
UNWRAP_DOMAINS = [
    "mavely.app", "joinmavely.com", "mavelylife.com", 
    "mavely.app.link", "go.mavely.app", 
    "amzn.to", "a.co", "bit.ly", "tinyurl.com"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "ref=", "aff_", "mc_cid", "mc_eid", "tag="]
URL_REGEX = re.compile(r'(?P<url>https?://[^\s]+)')
FOOTER_TEXT = "\n\n*Link cleaned by Purelink*"

# Regex for Meta Refresh: <meta http-equiv="refresh" content="0; url=https://example.com">
RE_META_REFRESH = re.compile(r'<\s*meta[^>]+http-equiv\s*=\s*["\']refresh["\'][^>]+content\s*=\s*["\']\d+;\s*url=(?P<url>https?://[^"\']+)["\']', re.I)

# High-fidelity Browser Headers to bypass bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

process_message_time = Summary('process_message_time', 'Time spent processing message')
messages = Counter('messages', 'Total number of messages processed')
cleaned_messages = Counter('cleaned_messages', 'Number of messages with tracking links cleaned')
servers = Gauge('servers', 'Number of servers the bot is in')
members = Gauge('members', 'Combined member count of all servers the bot is in')

async def count_servers_members():
    while True:
        servers.set(len(client.guilds))
        members.set(sum([guild.member_count for guild in client.guilds]))
        await asyncio.sleep(60)

async def unwrap_link(url: str) -> str:
    """Follows redirects and cleans appropriately for product vs search pages."""
    
    final_url = url
    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=10, 
        headers=HEADERS, 
        cookies=httpx.Cookies(),
        http2=True,
        timeout=12.0
    ) as httpx_client:
        hops = 0
        current_url = url
        while hops < 10:
            parsed = urlparse(current_url)
            should_unwrap = any(domain in parsed.netloc for domain in UNWRAP_DOMAINS)
            
            try:
                response = await httpx_client.get(current_url)
                current_url = str(response.url)
                
                # Check for Meta Refresh
                match = RE_META_REFRESH.search(response.text)
                if match:
                    current_url = match.group("url")
                    hops += 1
                    continue 
                else:
                    if not should_unwrap and hops > 0:
                        break
            except Exception:
                break
            hops += 1
        
        final_url = current_url

    # Smart Purity Logic
    p = urlparse(final_url)
    # Don't strip ALL params for search pages (Amazon /s or Google /search)
    if p.path.endswith('/s') or '/search' in p.path:
        return clear_url(final_url)
    else:
        # Total Purity for everything else (Product pages)
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))
    asyncio.create_task(count_servers_members())
    print(f'Purelink is logged in as {client.user}')

@process_message_time.time()
@client.event
async def on_message(message):
    if message.author.bot:
        return

    messages.inc()
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
            new_url = await unwrap_link(url)
            # If it's a known affiliate domain or search, we ALWAYS consider it "cleaned" 
            # to ensure the webhook repost happens even if the URL didn't change much.
            if new_url != url or should_unwrap:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True

    if any_cleaned:
        permissions = message.channel.permissions_for(message.guild.me)
        if not (permissions.manage_messages and permissions.manage_webhooks):
            await message.reply(f"I found tracking links! Here is the clean version:\n{cleaned_content}", mention_author=False)
            return

        try:
            webhooks = await message.channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Purelink Cleaner")
            if not webhook:
                webhook = await message.channel.create_webhook(name="Purelink Cleaner")

            await webhook.send(
                content=cleaned_content + FOOTER_TEXT,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none()
            )
            
            await message.delete()
            cleaned_messages.inc()
        except discord.HTTPException as e:
            print(f"Error handling webhook or deletion: {e}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')

    if not token:
        print("CRITICAL ERROR: No TOKEN found in .env file.")
        exit(1)

    # Use a default port if environment variable is missing
    metrics_port = int(os.getenv('METRICS_PORT', 8000))
    start_http_server(metrics_port)
    client.run(token)
