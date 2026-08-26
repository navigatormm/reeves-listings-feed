#!/usr/bin/env python3
"""Build a Meta Home Listings catalog feed (CSV) from reevesrealty.ca.

Field names and allowed values follow Meta's catalog batch reference for
item_type=HOME_LISTING (Advantage+ catalog ads for real estate).
"""
import csv
import html as htmllib
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

LISTINGS_URL = "https://www.reevesrealty.ca/listings.php"
OUT_CSV = "feed.csv"
MAX_IMAGES = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

COLUMNS = [
    "home_listing_id", "name", "description", "availability", "price", "url",
    "latitude", "longitude",
    "address.addr1", "address.city", "address.region", "address.country",
    "address.postal_code",
    "neighborhood", "property_type", "listing_type",
    "num_beds", "num_baths", "year_built",
] + [f"image[{i}].url" for i in range(MAX_IMAGES)]


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            print(f"  fetch attempt {i + 1}/{attempts} failed for {url}: {getattr(e, 'code', '')} {e}")
            time.sleep(5 * (i + 1))
    raise last


def listing_urls():
    """Collect every listing URL, following the site's rel=next pagination."""
    urls, seen, page_url = [], set(), LISTINGS_URL
    for _ in range(50):
        page = fetch(page_url)
        found = [u for u in re.findall(
            r'href="(https://www\.reevesrealty\.ca/listing/[^"]+)"', page)]
        fresh = [u for u in dict.fromkeys(found) if u not in seen]
        seen.update(fresh)
        urls.extend(fresh)
        print(f"  {page_url}: {len(fresh)} listings")
        m = re.search(r'<link rel="next" href="([^"]+)"', page)
        if not m or not fresh:
            break
        nxt = htmllib.unescape(m.group(1))
        page_url = nxt if nxt.startswith("http") else LISTINGS_URL + nxt
        time.sleep(1)
    return urls


def field(page, key):
    """Pull a value out of the listing page's embedded JSON."""
    m = re.search(r'"' + key + r'":\s*"((?:[^"\\]|\\.)*)"', page)
    if not m:
        return ""
    return m.group(1).replace('\\"', '"').replace("\\/", "/").strip()


def property_type(sub_type, listing_type):
    """Map the site's property sub-type to Meta's allowed values."""
    s = f"{sub_type} {listing_type}".lower()
    if "apartment" in s:
        return "apartment"
    if "row" in s or "townhouse" in s:
        return "townhouse"
    if "land" in s or "lot" in s:
        return "land"
    if "mobile" in s or "manufactured" in s:
        return "manufactured"
    if "condo" in s:
        return "condo"
    if "detached" in s or "house" in s or "residential" in s:
        return "house"
    return "other"


def availability(status):
    """Map the site's listing status to Meta's allowed values."""
    s = status.lower()
    if "pending" in s:
        return "sale_pending"
    if "sold" in s:
        return "recently_sold"
    if "expired" in s or "cancel" in s or "withdraw" in s or "terminat" in s:
        return "off_market"
    return "for_sale"


def images(page):
    """Photo URLs in the order the page lists them, largest size available."""
    found = re.findall(r'(https://feed-images\.rewhosting\.com/[^\s"\\\']+?\.jpg)', page)
    ordered = list(dict.fromkeys(u for u in found if "/XLarge/" in u))

    def seq(u):
        m = re.search(r'/(\d+)-[0-9a-f]{16,}', u)
        return int(m.group(1)) if m else 9999

    return sorted(ordered, key=seq)[:MAX_IMAGES]


def scrape(url):
    raw = fetch(url)
    page = htmllib.unescape(raw)

    mls = field(page, "ListingMLS")
    addr = field(page, "Address")
    city = field(page, "AddressCity")
    price = re.sub(r"[^\d]", "", field(page, "ListingPrice"))
    photos = images(page)

    if not (mls and addr and price and photos):
        print(f"  SKIPPED (missing id/address/price/photo): {url}")
        return None

    desc = ""
    m = re.search(r'<meta name="description" content="([^"]*)"', raw)
    if m:
        desc = re.sub(r"\s+", " ", htmllib.unescape(m.group(1))).strip()[:5000]

    baths = field(page, "NumberOfBathrooms")
    try:
        baths = int(float(baths)) if baths else ""
    except ValueError:
        baths = ""
    beds = re.sub(r"[^\d]", "", field(page, "NumberOfBedrooms"))
    year = re.sub(r"[^\d]", "", field(page, "YearBuilt"))[:4]

    row = {
        "home_listing_id": mls,
        "name": f"{addr}, {city}" if city else addr,
        "description": desc or f"{addr}, {city}",
        "availability": availability(field(page, "ListingStatus")),
        "price": f"{price} CAD",
        "url": url,
        "latitude": field(page, "Latitude"),
        "longitude": field(page, "Longitude"),
        "address.addr1": addr,
        "address.city": city,
        "address.region": field(page, "AddressState"),
        "address.country": "CA",
        "address.postal_code": field(page, "AddressZipCode"),
        "neighborhood": field(page, "AddressSubdivision"),
        "property_type": property_type(field(page, "ListingSubType"),
                                       field(page, "ListingType")),
        "listing_type": "for_sale_by_agent",
        "num_beds": beds,
        "num_baths": baths,
        "year_built": year,
    }
    for i, u in enumerate(photos):
        row[f"image[{i}].url"] = u
    return row


def main():
    try:
        urls = listing_urls()
    except Exception as e:
        print(f"ERROR: could not fetch the listings pages: {e}")
        print("The previous feed is kept unchanged.")
        sys.exit(1)

    print(f"Found {len(urls)} listing pages")
    if not urls:
        print("ERROR: zero listings found - site layout may have changed.")
        print("The previous feed is kept unchanged.")
        sys.exit(1)

    rows = []
    for u in urls:
        try:
            row = scrape(u)
        except Exception as e:
            print(f"  SKIPPED ({e}): {u}")
            row = None
        if row:
            rows.append(row)
            print(f"  {row['home_listing_id']}: {row['name']} {row['price']} "
                  f"{row['property_type']} beds={row['num_beds']} "
                  f"photos={sum(1 for k in row if k.startswith('image'))}")
        time.sleep(0.5)

    if not rows:
        print("ERROR: no listings could be parsed. Previous feed kept unchanged.")
        sys.exit(1)
    if len(rows) < len(urls) * 0.8:
        print(f"ERROR: only {len(rows)} of {len(urls)} listings parsed. "
              "Previous feed kept unchanged.")
        sys.exit(1)

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})

    print(f"Wrote {OUT_CSV} with {len(rows)} listings at "
          f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")


if __name__ == "__main__":
    main()
