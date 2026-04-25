import asyncio
import os
import re
import discord
import subprocess
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink Discord Bot - Terminal Stealth Edition
# Uses the server's own 'curl' to bypass Cloudflare blocks.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely", "joinmavely", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "lordofsavings", "tdgdeals", "pricedoffers", "ojrq.net", "sjv.io"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag=", "linkId="]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price', 'sprefix']

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Uses the system's curl command to follow redirects stealthily."""
    print(f"[DEBUG] Unrolling via System Curl: {url}")
    
    try:
        # Use curl -L (follow) -I (head) -s (silent) to find the final URL
        # We mimic a real Chrome browser
        cmd = [
            "curl", "-L", "-s", "-o", "/dev/null", "-w", "%{url_effective}",
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            url
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        final_url = stdout.decode().strip() if stdout else url
        print(f"[DEBUG] Curl resolved to: {final_url}")
        
    except Exception as e:
        print(f"[ERROR] Curl failed: {e}")
        final_url = url

    # Apply Purity Logic
    p = urlparse(final_url)
    if any(k in p.path for k in ['/s', '/search']) or 'k=' in p.query:
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        return urlunparse((p.scheme, p.netloc, p.path, '', urlencode(clean_qs, doseq=True), ''))
    else:
        if p.scheme and p.netloc:
            # Total strip for product pages
            return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        return final_url

@client.event
async def on_ready():
    print(f'>>> SUCCESS: Purelink is ready as {client.user}')

@client.event
async def on_message(message):
    if message.author.bot: return

    urls = re.findall(r'https?://[^\s<>"]+', message.content)
    if not urls: return

    print(f"[DEBUG] Heartbeat: Processing {len(urls)} link(s) from {message.author}")
    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        # Check if it's a known affiliate domain or has tracking
        is_tracking = any(kw in url.lower() for kw in TRACKING_KEYWORDS)
        is_affiliate = any(d in url.lower() for d in UNWRAP_DOMAINS)

        if is_tracking or is_affiliate:
            new_url = await unwrap_link(url)
            
            # Repost if the link changed OR if it's a known affiliate link 
            # (We always want to "clean" affiliates to show they were processed)
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
                content=cleaned_content + "\n\n-# *Link cleaned by Purelink*",
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await message.delete()
        except Exception as e:
            await message.channel.send(f"**Cleaned link:**\n{cleaned_content}")

if __name__ == '__main__':
    token = os.getenv('TOKEN')
    client.run(token)
