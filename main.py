import asyncio
import os
import re
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink Discord Bot - Twitter/t.co Hardened Build
# Restoration of Meta-Refresh parsing to handle Twitter jump pages.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely", "joinmavely", "mavelyinfluencer.com", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "lordofsavings", "tdgdeals", "pricedoffers", "ojrq.net", "sjv.io", "rstyle.me",
    "link.profitlounge.us", "howl.link", "jdoqocy.com", "sylikes.com", "bizrate.com", 
    "skimresources.com", "rebeldealz.net", "t.co"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag=", "linkId="]
PEEK_KEYS = ["return", "url", "dest", "destination", "u", "q", "redirect", "redirect_url", "murl"]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price', 'sprefix']

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    current_url = url
    print(f"[DEBUG] Unrolling: {url}")
    
    for hop in range(1, 10):
        # 1. PEAKING (Bypass Blocks)
        p = urlparse(current_url)
        qs = parse_qs(p.query)
        found_peek = False
        for key in PEEK_KEYS:
            if key in qs:
                potential = unquote(qs[key][0])
                if potential.startswith("http"):
                    current_url = potential
                    found_peek = True
                    break
        if found_peek: continue

        # 2. CURL RESOLUTION (With Content Peeking for Meta-Refresh)
        try:
            # We fetch the HEADERS and the BODY to catch Meta Refresh and JS redirects
            cmd = [
                "curl", "-Ls", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "-w", "\n%{url_effective}",
                current_url
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if not stdout: break
            
            lines = stdout.decode().splitlines()
            new_url = lines[-1].strip() # The effective URL from -w
            content = "\n".join(lines[:-1]) # The actual page content
            
            # Check for Meta Refresh in the content (Crucial for t.co)
            meta = re.search(r'url=(?P<url>https?://[^"\']+)', content, re.I)
            if meta:
                current_url = meta.group("url")
                print(f"[DEBUG] Hop {hop} (Meta): Found jump to {current_url}")
                continue
            
            if new_url == current_url:
                break
                
            current_url = new_url
            print(f"[DEBUG] Hop {hop} (Curl): Moved to {current_url}")
            
            if not any(d in current_url for d in UNWRAP_DOMAINS) and not any(kw in current_url for kw in TRACKING_KEYWORDS):
                break
        except:
            break
            
    final_url = current_url
    p = urlparse(final_url)
    if any(k in p.path for k in ['/s', '/search']) or 'k=' in p.query:
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        return urlunparse((p.scheme, p.netloc, p.path, '', urlencode(clean_qs, doseq=True), ''))
    else:
        if p.scheme and p.netloc:
            return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
        return final_url

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))
    print(f'>>> SUCCESS: Purelink is ready as {client.user}')

@client.event
async def on_message(message):
    if message.author.bot: return
    urls = re.findall(r'https?://[^\s<>"]+', message.content)
    if not urls: return

    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        url_clean = url.rstrip('.,!?;:')
        is_tracking = any(kw in url_clean.lower() for kw in TRACKING_KEYWORDS)
        is_affiliate = any(d in url.lower() for d in UNWRAP_DOMAINS)

        if is_tracking or is_affiliate:
            new_url = await unwrap_link(url_clean)
            if new_url != url_clean or is_affiliate:
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
        except:
            await message.channel.send(f"**Cleaned link:**\n{cleaned_content}")

if __name__ == '__main__':
    token = os.getenv('TOKEN')
    client.run(token)
