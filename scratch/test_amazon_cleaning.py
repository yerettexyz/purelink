import asyncio
import json
import os
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote

# Import the actual logic if possible, or just copy it for a clean test
# I'll copy it to ensure it's exactly what's in main.py but without discord dependencies

def load_config():
    config_path = 'data.json'
    with open(config_path, 'r') as f:
        return json.load(f)

CONFIG = load_config()

async def unwrap_link(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    final_url = url

    # Purity Scrub
    p = urlparse(final_url)
    qs = parse_qs(p.query)

    clean_qs = {}
    for k, v in qs.items():
        k_lower = k.lower()
        is_tracking = False
        for kw in CONFIG["tracking_keywords"]:
            kw_clean = kw.lower().rstrip('=')
            if kw.endswith('='):
                if k_lower == kw_clean:
                    is_tracking = True
                    break
            elif kw.endswith('_'):
                if k_lower.startswith(kw_clean):
                    is_tracking = True
                    break
            else:
                if kw.lower() in k_lower:
                    is_tracking = True
                    break
        
        if not is_tracking:
            clean_qs[k] = v

    clean_path = p.path
    if "amazon" in p.netloc.lower():
        clean_path = re.sub(r'/(ref[=/].*)', '', clean_path)

    new_query = urlencode(clean_qs, doseq=True)
    return urlunparse((p.scheme, p.netloc, clean_path.rstrip('/'), p.params, new_query, p.fragment))

async def main():
    test_urls = [
        "https://www.amazon.com/dp/B01LXC4JPJ?th=1&smid=ATVPDKIKX0DER&linkCode=sl2&tag=essedeals-20&linkId=1ee718a0c7424b70669c068e5968e992&language=en_US&ref_=as_li_ss_tl",
        "https://www.macys.com/shop/product/tour-edge-exotics-ls-right-hand-mens-x2013-9.0-ventus-blue-blk-stiff-driver?ID=25142710",
        "https://www.amazon.com/dp/B002KE7JB2?ref=t_ac_spc_accepted_tile&linkCode=tr1&tag=shopeva-20&linkId=B002KE7JB2_1777066761651",
        "https://www.amazon.com/gp/product/B0FK1GVJFV?tag=shopeva-20",
        "https://open.spotify.com/track/4EDmwV0cTLJ31s9sLQ1x2p?si=kXsEHkrkSbmETyUy8Sd_7w",
        "https://youtu.be/WDoxNTBrvzQ?si=QL9lPjwL2q35h6dC",
        "https://www.instagram.com/reel/DXgTPwuDlbd?igsh=bmozaWVpNWhqdDFj"
    ]
    
    for url in test_urls:
        print(f"\nInitial: {url}")
        cleaned = await unwrap_link(url)
        print(f"Cleaned: {cleaned}")

if __name__ == "__main__":
    asyncio.run(main())
