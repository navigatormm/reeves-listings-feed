#!/usr/bin/env python3
"""Build a Meta (Facebook) catalog-compatible RSS feed from reevesrealty.ca listings."""
import re
import sys
import time
import html as htmllib
import urllib.request
import urllib.error
import xml.sax.saxutils as sx
from datetime import datetime, timezone

LISTINGS_URL = "https://www.reevesrealty.ca/listings.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}


def fetch(url, attempts=3):
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            code = getattr(e, "code", "")
            print(f"  fetch attempt {i + 1}/{attempts} failed for {url}: {code} {e}")
            time.sleep(5 * (i + 1))
    raise last_err


def parse_cards(page):
    """Parse teaser cards from the listings page."""
    cards = []
    # Each card is an <a ... class="teaser teaser__card" ...> ... </a>
    for m in re.finditer(
        r'<a\s+href="(https://www\.reevesrealty\.ca/listing/[^"]+)"\s+class="teaser teaser__card"(.*?)</a>',
        page, re.S,
    ):
        url, body = m.group(1), m.group(2)
        def g(pat, default=""):
            mm = re.search(pat, body, re.S)
            return htmllib.unescape(mm.group(1)).strip() if mm else default

        price = g(r'teaser__price__title">([^<]+)<')
        address = g(r'teaser__address notranslate">\s*([^<]+?)\s*</h4>')
        image = g(r'data-src="([^"]+)"')
        mls = g(r'listing_id="([^"]+)"')
        beds = g(r'<span>\s*(\d+)\s*Beds')
        baths = g(r'<span>\s*(\d+)\s*Baths')
        sqft = g(r'<span>([\d,]+) SqFt</span>')
        ptype = g(r'listing_type="([^"]+)"')
        if url and price and mls:
            cards.append(dict(url=url, price=price, address=address, image=image,
                              mls=mls, beds=beds, baths=baths, sqft=sqft, ptype=ptype))
    return cards


def get_description(url):
    try:
        page = fetch(url)
        m = re.search(r'<meta name="description" content="([^"]*)"', page)
        if m:
            return htmllib.unescape(m.group(1)).strip()
    except Exception as e:
        print(f"  WARNING: could not get description from {url}: {e}")
    return ""


def build_xml(cards):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    items = []
    for c in cards:
        price_num = re.sub(r"[^\d.]", "", c["price"]) or "0"
        bits = []
        if c["beds"]:
            bits.append(f'{c["beds"]} Beds')
        if c["baths"]:
            bits.append(f'{c["baths"]} Baths')
        if c["sqft"]:
            bits.append(f'{c["sqft"]} SqFt')
        title = f'{c["address"]} | {c["price"]}'
        desc = c.get("desc") or " · ".join(bits) or c["address"]
        # Meta recommends description max ~5000 chars; keep it tidy
        desc = desc[:4900]
        e = sx.escape
        items.append(f"""    <item>
      <g:id>{e(c["mls"])}</g:id>
      <g:title>{e(title)}</g:title>
      <g:description>{e(desc)}</g:description>
      <g:link>{e(c["url"])}</g:link>
      <g:image_link>{e(c["image"])}</g:image_link>
      <g:brand>Reeves Realty</g:brand>
      <g:condition>new</g:condition>
      <g:availability>in stock</g:availability>
      <g:price>{e(price_num)} CAD</g:price>
      <g:product_type>{e(c["ptype"] or "Real Estate")}</g:product_type>
      <g:custom_label_0>{e(c["beds"])} Beds</g:custom_label_0>
      <g:custom_label_1>{e(c["baths"])} Baths</g:custom_label_1>
      <g:custom_label_2>{e(c["sqft"])} SqFt</g:custom_label_2>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>Reeves Realty Current Listings</title>
    <link>{LISTINGS_URL}</link>
    <description>Current property listings from Reeves Realty</description>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def parse_all_pages():
    """Crawl listings.php and every paginated page (?p=2, ?p=3, ...) via rel=next."""
    cards, seen = [], set()
    url = LISTINGS_URL
    for _ in range(50):  # safety cap on page count
        page = fetch(url)
        page_cards = [c for c in parse_cards(page) if c["mls"] not in seen]
        for c in page_cards:
            seen.add(c["mls"])
        cards.extend(page_cards)
        print(f"  page {url}: {len(page_cards)} listings")
        m = re.search(r'<link rel="next" href="([^"]+)"', page)
        if not m or not page_cards:
            break
        nxt = htmllib.unescape(m.group(1))
        url = nxt if nxt.startswith("http") else LISTINGS_URL + nxt
        time.sleep(1)
    return cards


def main():
    try:
        cards = parse_all_pages()
    except Exception as e:
        print(f"ERROR: could not fetch the listings page: {e}")
        print("The previous feed.xml is kept unchanged.")
        sys.exit(1)
    print(f"Found {len(cards)} listings")
    if not cards:
        print("ERROR: page fetched but zero listings parsed - site layout may have changed.")
        print("The previous feed.xml is kept unchanged.")
        sys.exit(1)
    for c in cards:
        c["desc"] = get_description(c["url"])
        print(f'  {c["mls"]}: {c["address"]} {c["price"]} desc={len(c["desc"])} chars')
        time.sleep(0.5)
    xml = build_xml(cards)
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print("Wrote feed.xml")


if __name__ == "__main__":
    main()
