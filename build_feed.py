#!/usr/bin/env python3
"""Build a Meta Home Listings catalog feed (CSV) from reevesrealty.ca.

Field names and allowed values follow Meta's catalog batch reference for
item_type=HOME_LISTING (Advantage+ catalog ads for real estate).

Listing data comes from reevesrealty.ca. The click-through link for each home
comes from listing_urls.csv, which this script maintains as a worklist: every
live listing gets a row, new listings arrive with a blank url, and listings
that have left are dropped. Filling in a url is the one manual step, because a
Lofty link carries an internal id that exists only on their site and cannot be
derived from the MLS number or the address.

A listing with no url is held out of the feed entirely, so no ad can ever run
without a destination.

The feed is a full replacement each run. Meta deletes absent items when the
data source uses a Replace schedule, so this script refuses to publish a feed
that has shrunk implausibly - see SHRINK_LIMIT.
"""
import csv
import html as htmllib
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

LISTINGS_URL = "https://www.reevesrealty.ca/listings.php"
OUT_CSV = "feed.csv"
# Destination links live in their own file so they survive every rebuild.
URL_MAP_CSV = "listing_urls.csv"
MAX_IMAGES = 5
DESCRIPTION_LIMIT = 900
# Refuse to publish if the count falls below this share of the previous feed.
SHRINK_LIMIT = 0.6
# Seconds between property-page requests. The source rate-limits below ~1s.
PAGE_DELAY = 1.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

# Nested and repeated fields use Meta's JSON-path column convention:
# address.<part> for the address object, neighborhood[0] because neighborhood
# is an array of strings, image[N].url for the photo list.
COLUMNS = [
    "home_listing_id", "name", "description", "availability", "price", "url",
    "latitude", "longitude",
    "address.addr1", "address.city", "address.region", "address.country",
    "address.postal_code",
    "neighborhood[0]", "property_type", "listing_type",
    "num_beds", "num_baths", "year_built",
] + [f"image[{i}].url" for i in range(MAX_IMAGES)]


PROVINCES = {
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB",
    "New Brunswick": "NB", "Newfoundland and Labrador": "NL",
    "Northwest Territories": "NT", "Nova Scotia": "NS", "Nunavut": "NU",
    "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
    "Saskatchewan": "SK", "Yukon": "YT",
}


def coord(value):
    """Six decimal places is ~0.1m; the site pads to twelve."""
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


def fetch(url, attempts=4):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            # 429 means we are asking too fast, so back off hard rather than
            # burn the attempt. Anything else is usually a blip.
            wait = 45 * (i + 1) if code == 429 else 5 * (i + 1)
            print(f"  fetch attempt {i + 1}/{attempts} failed for {url}: "
                  f"{code or ''} {e}; waiting {wait}s")
            if i < attempts - 1:
                time.sleep(wait)
    raise last


def listing_urls():
    """Collect every listing URL, following the site's rel=next pagination."""
    urls, seen, page_url = [], set(), LISTINGS_URL
    for _ in range(50):
        page = fetch(page_url)
        found = re.findall(
            r'href="(https://www\.reevesrealty\.ca/listing/[^"]+)"', page)
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
    """Distinct photos in page order.

    Each photo is served at three sizes: -l (1024x767), -m (640x480) and
    -s (320x240). Only -l clears Meta's 500x500 minimum, and the other two
    are the same picture, so take -l only and keep one per photo number.
    """
    found = re.findall(
        r'(https://feed-images\.rewhosting\.com/[^\s"\\\']+?-l\.jpg)', page)

    def seq(u):
        m = re.search(r'/(\d+)-[0-9a-f]{16,}', u)
        return int(m.group(1)) if m else 9999

    by_photo = {}
    for u in found:
        if "/XLarge/" in u:
            by_photo.setdefault(seq(u), u)
    return [by_photo[n] for n in sorted(by_photo)][:MAX_IMAGES]


def scrape(url, url_map):
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
        desc = re.sub(r"\s+", " ", htmllib.unescape(m.group(1))).strip()
        if len(desc) > DESCRIPTION_LIMIT:
            cut = desc[:DESCRIPTION_LIMIT]
            stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            desc = (cut[:stop + 1] if stop > 200 else cut).strip()

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
        "url": url_map.get(mls, ""),
        "latitude": coord(field(page, "Latitude")),
        "longitude": coord(field(page, "Longitude")),
        "address.addr1": addr,
        "address.city": city,
        "address.region": PROVINCES.get(field(page, "AddressState"),
                                        field(page, "AddressState")),
        "address.country": "CA",
        "address.postal_code": field(page, "AddressZipCode"),
        "neighborhood[0]": field(page, "AddressSubdivision"),
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


def load_url_map(path=URL_MAP_CSV):
    """home_listing_id -> destination URL. A blank url means 'not filled in yet'."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            out = {}
            for r in csv.DictReader(f):
                mls = (r.get("home_listing_id") or "").strip()
                url = (r.get("url") or "").strip()
                if not mls:
                    continue
                if url and not url.startswith("http"):
                    print(f"  WARNING: {mls} has a url that is not a link, ignoring: {url!r}")
                    url = ""
                out[mls] = url
            return out
    except FileNotFoundError:
        print(f"WARNING: {path} not found; no listing will have a destination link.")
        return {}


def write_url_map(rows, url_map, path=URL_MAP_CSV):
    """Rewrite the worklist: one row per live listing, blank url when unknown.

    Adds rows for new listings, drops rows for listings that have left, and
    preserves every url already filled in. Listings still needing a url are
    written first so they are easy to spot. Only called after the feed has
    passed its safety checks, so a partial crawl cannot disturb the file.
    """
    live = [(r["home_listing_id"], r["name"]) for r in rows]
    live_ids = {mls for mls, _ in live}
    added = sorted(mls for mls in live_ids if mls not in url_map)
    removed = sorted(set(url_map) - live_ids)

    needing = sorted((m, n) for m, n in live if not url_map.get(m))
    filled = sorted((m, n) for m, n in live if url_map.get(m))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["home_listing_id", "address", "url"])
        for mls, name in needing + filled:
            w.writerow([mls, name, url_map.get(mls, "")])

    if added:
        print(f"Added {len(added)} new listing(s) to {path} awaiting a url: "
              f"{', '.join(added)}")
    if removed:
        print(f"Removed {len(removed)} listing(s) from {path} that have left "
              f"the site: {', '.join(removed)}")
    return needing


def previous_count(path):
    """Listings in the currently published feed, or None if there isn't one."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
    except FileNotFoundError:
        return None


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

    url_map = load_url_map()
    print(f"Destination links on file: {sum(1 for v in url_map.values() if v)}")

    rows = []
    for u in urls:
        try:
            row = scrape(u, url_map)
        except Exception as e:
            print(f"  SKIPPED ({e}): {u}")
            row = None
        if row:
            rows.append(row)
            print(f"  {row['home_listing_id']}: {row['name']} {row['price']} "
                  f"{row['property_type']} beds={row['num_beds']} "
                  f"photos={sum(1 for k in row if k.startswith('image'))}")
        time.sleep(PAGE_DELAY)

    if not rows:
        print("ERROR: no listings could be parsed. Previous feed kept unchanged.")
        sys.exit(1)
    if len(rows) < len(urls) * 0.8:
        print(f"ERROR: only {len(rows)} of {len(urls)} listings parsed. "
              "Previous feed kept unchanged.")
        sys.exit(1)

    previous = previous_count(OUT_CSV)
    publish = [r for r in rows if r["url"]]

    if (previous and previous >= 5 and len(publish) < previous * SHRINK_LIMIT
            and not os.environ.get("ALLOW_SHRINK")):
        print(f"ERROR: publishable listing count fell from {previous} to "
              f"{len(publish)}. That is a bigger drop than listings selling "
              "would explain, so it most likely means the site served a partial "
              "page or destination links went missing. Publishing this feed "
              "would delete those listings from the Meta catalog, so the "
              "previous feed is kept unchanged. If the drop is genuine, re-run "
              "with ALLOW_SHRINK=1.")
        sys.exit(1)

    needing = write_url_map(rows, url_map)

    # A listing without a destination link is held back entirely, so no ad can
    # run without one.
    if not publish:
        print("ERROR: no listing has a destination link, so the feed would be "
              f"empty. Fill in the url column in {URL_MAP_CSV}. Previous feed "
              "kept unchanged.")
        sys.exit(1)

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in publish:
            w.writerow({c: r.get(c, "") for c in COLUMNS})

    if needing:
        print(f"\nNOTE: {len(needing)} listing(s) are held out of the feed until a "
              f"url is added in {URL_MAP_CSV}:")
        for mls, name in needing:
            print(f"  {mls}   ({name})")
    else:
        print("Every live listing has a destination link.")

    was = f" (previous feed had {previous})" if previous is not None else ""
    print(f"Wrote {OUT_CSV} with {len(publish)} of {len(rows)} listings{was} at "
          f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")


if __name__ == "__main__":
    main()
