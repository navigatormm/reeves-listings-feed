# Reeves Realty Listings Feed

An always-current **Meta Home Listings catalog feed** of every property on
[reevesrealty.ca](https://www.reevesrealty.ca/listings.php), for Advantage+
catalog ads (real estate) on Facebook and Instagram.

**Feed URL** (paste into Meta Commerce Manager as a scheduled feed):

```
https://raw.githubusercontent.com/navigatormm/reeves-listings-feed/main/feed.csv
```

## Meta setup

- The catalog must be created with the **Real estate / Properties** type.
  A home listings feed cannot be uploaded into an e-commerce catalog.
- Set the data source to a **Replace** schedule, not Update. Replace deletes
  items that are no longer in the file, which is how sold listings leave the
  catalog. Update never deletes, so sold homes would keep running in ads.
- Prices are CAD.

## Fields

Per Meta's catalog reference for `item_type=HOME_LISTING`:

`home_listing_id` (MLS number), `name`, `description`, `availability`,
`price`, `url`, `latitude`, `longitude`, `address.addr1`, `address.city`,
`address.region`, `address.country`, `address.postal_code`, `neighborhood`,
`property_type`, `listing_type`, `num_beds`, `num_baths`, `year_built`,
and up to 10 `image[N].url` columns.

`property_type` is mapped from the site's sub-type to Meta's allowed values
(apartment, condo, house, land, manufactured, other, townhouse), and
`availability` from listing status (for_sale, sale_pending, recently_sold,
off_market).

## How it refreshes

`build_feed.py` follows every "next page" link on the listings page, then
opens each property page for its address, coordinates, room counts, year
built and photos, and writes `feed.csv`.

It runs twice a day, at **5am and 5pm Calgary time**, as a Claude Code cloud
routine named "Refresh Reeves Realty listings feed"
(https://claude.ai/code/routines). Nothing runs on a local machine.

### Why not GitHub Actions

reevesrealty.ca returns HTTP 403 to GitHub's data-center IP ranges, so a
GitHub Actions workflow cannot crawl it. The cloud routine reaches the site
normally.

## Safety behaviour

The feed is a full replacement each run, so it is deliberately cautious about
publishing a short file. `build_feed.py` refuses to write, leaving the last
good feed live, when:

- the listings pages cannot be fetched at all;
- fewer than 80% of the listings found could be parsed;
- the listing count fell below 60% of the previous feed. Under a Replace
  schedule such a drop would delete real listings from the catalog, so it is
  treated as a site glitch. Re-run with `ALLOW_SHRINK=1` if the drop is real.

## Manual refresh

Open the routine at https://claude.ai/code/routines and run it, or run
`python3 build_feed.py` locally and commit the resulting `feed.csv`.
