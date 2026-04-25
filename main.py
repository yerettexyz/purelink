import asyncio
import os
import re
import discord
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from dotenv import load_dotenv

# Purelink Discord Bot - Amazon Path-Hardened Build (Final Stable)
# Hardened timeout and loop safety for finicky shortlinks.

load_dotenv()

UNWRAP_DOMAINS = [
    "mavely", "joinmavely", "mavelyinfluencer.com", "amzn.to", "a.co", "bit.ly", "tinyurl.com",
    "lordofsavings", "tdgdeals", "pricedoffers", "ojrq.net", "sjv.io", "rstyle.me",
    "link.profitlounge.us", "howl.link", "jdoqocy.com", "sylikes.com", "bizrate.com", 
    "skimresources.com", "t.co", "pricingerrors.com"
]
TRACKING_KEYWORDS = ["utm_", "fbclid", "gclid", "cjevent", "cjdata", "tag=", "linkId="]
PEEK_KEYS = ["return", "url", "dest", "destination", "u", "q", "redirect", "redirect_url", "murl"]
SEARCH_KEEPERS = ['k', 'q', 'srs', 'bbn', 'rh', 'rnid', 'crid', 'low-price', 'high-price', 'sprefix']

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def unwrap_link(url: str) -> str:
    """A hardened multi-hop resolver with a global timeout."""
    current_url = url
    print(f"DEBUG: Unroll started for {url}")
    
    try:
        # We put the entire unroll process in a 15-second cage
        async with asyncio.timeout(15.0):
            for hop in range(1, 10):
                # 1. PEAKING
                p = urlparse(current_url)
                qs = parse_qs(p.query)
                found_peek = False
                for key in PEEK_KEYS:
                    if key in qs:
                        potential = unquote(qs[key][0])
                        if potential.startswith("http"):
                            print(f"DEBUG: Hop {hop} Peeked {potential}")
                            current_url = potential
                            found_peek = True
                            break
                if found_peek: continue

                # 2. CURL RESOLUTION
                try:
                    cmd = [
                        "curl", "-Ls", "--max-time", "8", "-A", "Mozilla/5.0",
                        "-w", "\n%{url_effective}",
                        current_url
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, 
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    stdout, _ = await proc.communicate()
                    if not stdout: break
                    
                    lines = stdout.decode('utf-8', errors='ignore').splitlines()
                    if not lines: break
                    
                    new_url = lines[-1].strip() 
                    content = "\n".join(lines[:-1])
                    
                    # Check Meta Refresh
                    if "meta" in content.lower() and "http-equiv" in content.lower():
                        meta = re.search(r'url=(?P<url>https?://[^"\']+)', content, re.I)
                        if meta:
                            current_url = meta.group("url")
                            continue
                    
                    if new_url == current_url: break
                    current_url = new_url
                    
                    # Stop if we hit a clean domain
                    if not any(d in current_url for d in UNWRAP_DOMAINS) and not any(kw in current_url for kw in TRACKING_KEYWORDS):
                        break
                except Exception as e:
                    print(f"ERROR: Hop {hop} curl failed: {e}")
                    break
    except asyncio.TimeoutError:
        print(f"ERROR: Global timeout reached for {url}")
            
    final_url = current_url
    p = urlparse(final_url)
    
    # Path Scrubbing (Amazon ref segments)
    clean_path = p.path
    if "amazon" in p.netloc:
        clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)
    
    # Purity Logic
    is_search = any(k in clean_path for k in ['/s', '/search']) or 'k=' in p.query
    if is_search:
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        return urlunparse((p.scheme, p.netloc, clean_path, '', urlencode(clean_qs, doseq=True), ''))
    else:
        if p.scheme and p.netloc:
            return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), '', '', ''))
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

    print(f"INFO: Message from {message.author} contains {len(urls)} link(s)")
    cleaned_content = message.content
    any_cleaned = False

    for url in urls:
        url_clean = url.rstrip('.,!?;:')
        is_tracking = any(kw in url_clean.lower() for kw in TRACKING_KEYWORDS)
        is_affiliate = any(d in url.lower() for d in UNWRAP_DOMAINS)

        if is_tracking or is_affiliate:
            try:
                new_url = await unwrap_link(url_clean)
                if new_url != url_clean or is_affiliate:
                    cleaned_content = cleaned_content.replace(url, new_url)
                    any_cleaned = True
            except Exception as e:
                print(f"ERROR: Processing failed: {e}")

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
