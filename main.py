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
MAVELY_DOMAINS = ["mavely.app", "joinmavely.com"]
URL_REGEX = re.compile(r'(?P<url>https?://[^\s]+)')
FOOTER_TEXT = "\n\n*Link cleaned by Purelink*"

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
    """Follows redirects and strips tracking parameters."""
    parsed = urlparse(url)
    is_mavely = any(domain in parsed.netloc for domain in MAVELY_DOMAINS)
    
    if is_mavely:
        async with httpx.AsyncClient(follow_redirects=True, max_redirects=5) as httpx_client:
            try:
                response = await httpx_client.get(url, timeout=10.0)
                final_url = str(response.url)
                # Strip all query params for Mavely destination
                p = urlparse(final_url)
                return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
            except Exception:
                # Fallback to unalix if resolution fails
                return clear_url(url)
    
    # Standard cleaning for non-mavely links
    cleaned = clear_url(url)
    return cleaned

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
        # Check against pure unalix cleaning first for quick detection
        # (Unalix is synchronous, so we use it for a quick check)
        standard_cleaned = clear_url(url).strip('&')
        is_mavely = any(domain in url for domain in MAVELY_DOMAINS)
        
        if standard_cleaned != url.strip('&') or is_mavely:
            # Perform deeper async cleaning/unwrapping
            new_url = await unwrap_link(url)
            if new_url != url:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True

    if any_cleaned:
        permissions = message.channel.permissions_for(message.guild.me)
        if not (permissions.manage_messages and permissions.manage_webhooks):
            # Fallback to simple reply if permissions are missing
            await message.reply(f"I found tracking links! Here is the clean version:\n{cleaned_content}", mention_author=False)
            return

        # Prepare webhook for reposting
        try:
            webhooks = await message.channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Purelink Cleaner")
            if not webhook:
                webhook = await message.channel.create_webhook(name="Purelink Cleaner")

            # Repost message as user
            await webhook.send(
                content=cleaned_content + FOOTER_TEXT,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none() # Avoid pings during repost
            )
            
            # Delete original
            await message.delete()
            cleaned_messages.inc()
        except discord.HTTPException as e:
            print(f"Error handling webhook or deletion: {e}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')
    metrics_port = int(os.getenv('METRICS_PORT', 8000))

    if not token:
        print("CRITICAL ERROR: No TOKEN found in .env file.")
        exit(1)

    start_http_server(metrics_port)
    print(f"Metrics server started on port {metrics_port}")
    client.run(token)
