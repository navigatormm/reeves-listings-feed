# Reeves Realty Listings Feed

This repository automatically keeps an up-to-date product feed of all current
listings from [reevesrealty.ca](https://www.reevesrealty.ca/listings.php),
for use as a catalog feed in Meta (Facebook/Instagram) ads.

**Feed URL (paste this into Meta Commerce Manager as a scheduled feed):**

```
https://raw.githubusercontent.com/navigatormm/reeves-listings-feed/main/feed.xml
```

## How it works

- `build_feed.py` visits the listings page and every individual listing page,
  and writes `feed.xml` with each property's MLS number, address, price,
  photo, beds/baths/sqft, link, and full description.
- A GitHub Actions schedule (`.github/workflows/refresh-feed.yml`) re-runs the
  crawler around **5am and 5pm Calgary time every day** (four UTC runs cover
  both daylight-saving and standard time), entirely on GitHub's servers —
  no local computer needs to be on.
- If the crawler ever finds zero listings (e.g. the website layout changes),
  it stops without overwriting the feed, so ads keep running on the last
  good data.

To refresh manually: Actions tab → "Refresh listings feed" → "Run workflow".
