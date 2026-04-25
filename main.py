import asyncio
import os
import re
import httpx
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink Discord Bot - Diagnostic Edition
# Designed to track exactly where links are failing.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely.app", "joinmavely.com", "mavelylife.com", "mavelyinfluencer.com",
    "mavely.app.link", "go.mavely.app", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "link.lordofsavings.com", "link.tdgdeals.com", "pricedoffers.com",
    "ojrq.net", "sjv.io", "rstyle.me"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag=", "linkId="]
REDIRECT_KEYS = ["return", "url", "dest", "u", "q"]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price', 'sprefix']

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    print(f"[DEBUG] Starting unwrap for: {url}")
    current_url = url
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as httpx_client:
        for hop in range(1, 11):
            try:
                # 1. Quick Peek
                p = urlparse(current_url)
                qs = parse_qs(p.query)
                for key in REDIRECT_KEYS:
                    if key in qs:
                        potential = unquote(qs[key][0])
                        if potential.startswith("http"):
                            print(f"[DEBUG] Hop {hop} (Peeking): Found hidden URL in query params: {potential}")
                            current_url = potential
                            break
                
                # 2. HTTP Request
                resp = await httpx_client.get(current_url, headers={"User-Agent": "Mozilla/5.0"})
                print(f"[DEBUG] Hop {hop} (Resolved): Status {resp.status_code} -> {resp.url}")
                current_url = str(resp.url)
                
                # 3. Meta Refresh
                meta = re.search(r'url=(?P<url>https?://[^"\']+)', resp.text, re.I)
                if meta:
                    print(f"[DEBUG] Hop {hop} (Meta): Found refresh target: {meta.group('url')}")
                    current_url = meta.group("url")
                    continue

                # Stop if it's no longer a known tracker
                if not any(d in current_url for d in UNWRAP_DOMAINS) and not any(kw in current_url.lower() for kw in TRACKING_KEYWORDS):
                    print(f"[DEBUG] Destination reached: {current_url}")
                    break
            except Exception as e:
                print(f"[DEBUG] Unwrap error at hop {hop}: {e}")
                break
    
    # 4. Final Purity
    p = urlparse(current_url)
    if any(k in p.path for k in ['/s', '/search']) or 'k=' in p.query:
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        print(f"[DEBUG] Final Clean (Search): Stripping trackers...")
        return urlunparse((p.scheme, p.netloc, p.path, '', urlencode(clean_qs, doseq=True), ''))
    else:
        print(f"[DEBUG] Final Clean (Product): Total strip...")
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))

@client.event
async def on_ready():
    print(f'>>> SUCCESS: Purelink is ready as {client.user}')

@client.event
async def on_message(message):
    print(f"[DEBUG] Heartbeat: Message from {message.author}")
    if message.author.bot: return

    # Better URL Regex
    urls = re.findall(r'https?://[^\s<>"]+', message.content)
    if not urls: return

    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        url_clean = url.rstrip('.,!?;:')
        print(f"[DEBUG] Found URL: {url_clean}")
        
        is_tracking = any(kw in url_clean.lower() for kw in TRACKING_KEYWORDS)
        is_shortener = any(d in url_clean for d in UNWRAP_DOMAINS)

        if is_tracking or is_shortener:
            print(f"[DEBUG] Link needs cleaning. Unwrapping...")
            new_url = await unwrap_link(url_clean)
            if new_url != url_clean:
                cleaned_content = cleaned_content.replace(url_clean, new_url)
                any_cleaned = True
                print(f"[DEBUG] Cleaned Result: {new_url}")
            else:
                print(f"[DEBUG] No changes found during unwrap.")

    if any_cleaned:
        print(f"[DEBUG] Attempting to send cleaned message...")
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
            print(f"[DEBUG] Message successfully replaced!")
        except Exception as e:
            print(f"[ERROR] Final Step Failed: {e}")
            await message.channel.send(f"**Cleaned link:**\n{cleaned_content}")

if __name__ == '__main__':
    token = os.getenv('TOKEN')
    client.run(token)
