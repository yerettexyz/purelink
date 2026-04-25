import asyncio
import os
import re
import httpx
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv
from unalix import clear_url

# Purelink Discord Bot - Hardened Simple Edition
# No metrics, no decorators, just cleaning.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely.app", "joinmavely.com", "mavelylife.com", "mavelyinfluencer.com",
    "mavely.app.link", "go.mavely.app", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "link.lordofsavings.com", "link.tdgdeals.com", "pricedoffers.com",
    "ojrq.net", "sjv.io", "rstyle.me"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag="]
REDIRECT_KEYS = ["return", "url", "dest", "u", "q"]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price']

intents = discord.Intents.all()
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """Follows redirects with deep query peeking."""
    current_url = url
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as httpx_client:
        for _ in range(10):
            try:
                # Peek for hidden URLs in query params (Bypass Cloudflare)
                p = urlparse(current_url)
                qs = parse_qs(p.query)
                for key in REDIRECT_KEYS:
                    if key in qs:
                        potential = unquote(qs[key][0])
                        if potential.startswith("http"):
                            current_url = potential
                            break
                
                # Standard resolution
                resp = await httpx_client.get(current_url, headers={"User-Agent": "Mozilla/5.0"})
                current_url = str(resp.url)
                
                # Meta refresh
                meta = re.search(r'url=(?P<url>https?://[^"\']+)', resp.text, re.I)
                if meta:
                    current_url = meta.group("url")
                    continue

                if not any(d in current_url for d in UNWRAP_DOMAINS) and not any(kw in current_url for kw in TRACKING_KEYWORDS):
                    break
            except:
                break
    
    # Final Purity Logic
    p = urlparse(current_url)
    if any(k in p.path for k in ['/s', '/search']) or 'k=' in p.query:
        # Search page: Keep keywords
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS}
        return urlunparse((p.scheme, p.netloc, p.path, '', urlencode(clean_qs, doseq=True), ''))
    else:
        # Product page: Total strip
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))

@client.event
async def on_ready():
    print(f'>>> SUCCESS: Purelink is logged in as {client.user}')
    print(f'>>> Ensure "Message Content Intent" is ON in the Discord Portal!')

@client.event
async def on_message(message):
    print(f"[DEBUG] Heartbeat: Got message from {message.author}")
    if message.author.bot:
        return

    urls = re.findall(r'https?://[^\s]+', message.content)
    if not urls:
        return

    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        if any(d in url for d in UNWRAP_DOMAINS) or any(kw in url for kw in TRACKING_KEYWORDS):
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
        except Exception as e:
            await message.channel.send(f"Cleaned link:\n{cleaned_content}")
            print(f"[ERROR] Webhook/Delete failed: {e}")

if __name__ == '__main__':
    token = os.getenv('TOKEN')
    if not token:
        print("ERROR: TOKEN not found in .env file!")
    else:
        client.run(token)
