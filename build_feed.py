#!/usr/bin/env python3
"""Build a Meta (Facebook) catalog-compatible RSS feed from reevesrealty.ca listings."""
import re
import html as htmllib
import urllib.request
import xml.sax.saxutils as sx
from datetime import datetime, timezone

LISTINGS_URL = "https://www.reevesrealty.ca/listings.php"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ReevesRealtyFeedBot/1.0)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


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
    except Exception:
        pass
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


def main():
    page = fetch(LISTINGS_URL)
    cards = parse_cards(page)
    print(f"Found {len(cards)} listings")
    if not cards:
        raise SystemExit("No listings found - site layout may have changed; keeping previous feed.")
    for c in cards:
        c["desc"] = get_description(c["url"])
        print(f'  {c["mls"]}: {c["address"]} {c["price"]} desc={len(c["desc"])} chars')
    xml = build_xml(cards)
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print("Wrote feed.xml")


if __name__ == "__main__":
    main()
