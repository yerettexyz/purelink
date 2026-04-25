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

# High-fidelity Browser Headers
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

async def unwrap_link(url: str) -> str:
    """Follows redirects and cleans with deep inspection of search vs product pages."""
    
    final_url = url
    async with httpx.AsyncClient(
        follow_redirects=True, 
        max_redirects=10, 
        headers=HEADERS, 
        cookies=httpx.Cookies(),
        http2=True,
        timeout=15.0
    ) as httpx_client:
        hops = 0
        current_url = url
        while hops < 10:
            parsed = urlparse(current_url)
            try:
                response = await httpx_client.get(current_url)
                current_url = str(response.url)
                
                # Check for Meta Refresh in body
                meta_match = re.search(r'url=(?P<url>https?://[^"\']+)', response.text, re.I)
                if meta_match and hops < 5:
                    current_url = meta_match.group("url")
                    hops += 1
                    continue 
                else:
                    # If we're off known shorteners and didn't redirect, we're likely done
                    is_shortener = any(d in parsed.netloc for d in UNWRAP_DOMAINS)
                    if not is_shortener:
                        break
            except Exception as e:
                print(f"[DEBUG] Resolution failed for {current_url}: {e}")
                break
            hops += 1
        
        final_url = current_url

    # Smart Purity: Determine if it's a search page or a product page
    p = urlparse(final_url)
    is_search = p.path.endswith('/s') or '/search' in p.path or 'q=' in p.query or 'k=' in p.query
    
    if is_search:
        # Precision cleaning for search pages: Strip trackers but KEEP valid search keywords
        qs = parse_qs(p.query)
        clean_qs = {k: v for k, v in qs.items() if k in SEARCH_KEEPERS or k.startswith('p_')}
        
        # If we have valid search terms, reconstruct the search URL
        if clean_qs:
            new_query = urlencode(clean_qs, doseq=True)
            return urlunparse((p.scheme, p.netloc, p.path, '', new_query, ''))
        else:
            # If it's a search with no terms, let unalix try a general clean
            return clear_url(final_url)
    else:
        # Total Purity for Product Pages: Strip ALL params
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))

@client.event
async def on_message(message):
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
            print(f"[DEBUG] Cleaning URL: {url}")
            new_url = await unwrap_link(url)
            
            # Repost if the link changed OR it was an affiliate domain we want to sanitize
            if new_url != url or should_unwrap:
                cleaned_content = cleaned_content.replace(url, new_url)
                any_cleaned = True
                print(f"[DEBUG] -> Success: {new_url}")

    if any_cleaned:
        permissions = message.channel.permissions_for(message.guild.me)
        if not (permissions.manage_messages and permissions.manage_webhooks):
            await message.reply(f"Link cleaned by Purelink:\n{cleaned_content}", mention_author=False)
            return

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
            print(f"[DEBUG] Webhook error: {e}")

if __name__ == '__main__':
    load_dotenv()
    token = os.getenv('TOKEN')
    start_http_server(int(os.getenv('METRICS_PORT', 8000)))
    client.run(token)
