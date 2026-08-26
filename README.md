# Reeves Realty Listings Feed

An always-current product feed of every listing on
[reevesrealty.ca](https://www.reevesrealty.ca/listings.php), for use as a
catalog feed in Meta (Facebook / Instagram) ads.

**Feed URL** (paste this into Meta Commerce Manager as a scheduled feed):

```
https://raw.githubusercontent.com/navigatormm/reeves-listings-feed/main/feed.xml
```

Currency is CAD. Each item carries MLS number, address, price, photo,
link, full property description, and beds / baths / square footage as
custom labels for ad targeting.

## How it refreshes

`build_feed.py` visits the listings page, follows every "next page" link,
then opens each individual listing page for its full description, and
writes `feed.xml`.

It runs twice a day, at **5am and 5pm Calgary time**, as a Claude Code
cloud routine named "Refresh Reeves Realty listings feed"
(see https://claude.ai/code/routines). The routine crawls the site,
rebuilds the feed, and publishes `feed.xml` back to this repository.
Nothing runs on a local machine.

### Why not GitHub Actions

reevesrealty.ca returns HTTP 403 to GitHub's data-center IP ranges, so a
GitHub Actions workflow cannot crawl it. The cloud routine reaches the
site normally. The old workflow was removed for that reason.

### Safety behaviour

If the crawl fails or returns zero listings (site down, layout changed,
blocked), the routine publishes nothing and leaves the previous
`feed.xml` in place, so live ads keep running on the last good data.

## Manual refresh

Open the routine at https://claude.ai/code/routines and run it, or run
`python3 build_feed.py` locally and commit the resulting `feed.xml`.
