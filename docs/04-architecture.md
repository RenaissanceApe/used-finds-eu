# Architecture, and how to add a marketplace

## The one idea

**Marketplaces are data, not code.** 64 sites are served by 6 engines because
everything site-specific — the URL template, the JSON paths, the CSS selectors,
the currency, the account requirements, the shipping notes — lives in
`backend/ufeu/data/marketplaces.yaml`. Adding the 65th site is usually a ten-line
YAML edit and no Python at all.

```
                       marketplaces.yaml  ─────┐
                                               ▼
  SearchQuery ──► catalog.select() ──► orchestrator ──► engine per site ──► HTTP
                                            │                │
                                            │           Listing[] (normalised)
                                            ▼                │
                                       fx → EUR ◄────────────┘
                                            ▼
                                    shipping.plan() per row
                                            ▼
                                    dedupe → sort → SearchResponse
```

## Modules

| File | Job |
| --- | --- |
| `catalog.py` | loads and validates the marketplace catalogue; answers "which sites for this query?" |
| `adapters/base.py` | the engine contract; turns every failure mode into a visible result row instead of an exception |
| `adapters/vinted.py` | Vinted's shared EU pool (anonymous session bootstrap) |
| `adapters/olx.py` | OLX group — PL, PT, RO, BG on one endpoint shape |
| `adapters/ebay.py` | official Browse API, OAuth client-credentials, fans out over 9 EU sites |
| `adapters/json_api.py` | generic JSON engine: `mode: rest` or `mode: next_data`, JMESPath field mapping |
| `adapters/html.py` | generic CSS-selector engine for server-rendered classifieds |
| `adapters/manual.py` | sites we deliberately do not automate; emits a deep search link |
| `adapters/demo.py` | offline fixtures, so the whole app runs with no network |
| `normalize.py` | multi-locale price parsing, dates, slugs, relevance scoring |
| `fx.py` | ECB daily rates, cached, with a baked-in offline fallback |
| `orchestrator.py` | async fan-out, EUR conversion, shipping annotation, dedupe, ranking |
| `shipping.py` | route resolution to Portugal (deliverable f) |
| `vault.py` | Fernet-encrypted local credential store |
| `api.py` / `cli.py` | HTTP and terminal front ends |

## Adding a marketplace

**1. Find the shape.** Open the site, search for something, and watch DevTools →
Network. In order of preference:

- an XHR returning JSON → `engine: json_api`, `mode: rest`
- a `__NEXT_DATA__` script tag in the HTML → `engine: json_api`, `mode: next_data`
- plain server-rendered HTML → `engine: html`
- an anti-bot wall (DataDome, "are you a robot") → `engine: manual`. Stop here.
  Do not try to beat it; you will lose, and the results panel showing an honest
  link is worth more than a scraper that breaks weekly.

**2. Write the YAML.** A JSON site:

```yaml
  - id: example_xx
    name: Example.xx
    country: XX
    rank: 1
    scope: national
    site: https://www.example.xx
    focus: [general]
    engine: json_api
    default_enabled: true
    confidence: medium
    why: Why a local would use this one first — this field is required and tested.
    engine_config:
      mode: rest
      search_url: "https://www.example.xx/api/search?q={q}&limit={limit}"
      root: results            # JMESPath to the list of items
      fields:                  # JMESPath, relative to each item
        id: id
        title: name
        url: link
        price: price.amount
        image: images[0].url
        location: city
      currency: XXX
    account: {required_for_search: false, kind: session, automatable: false}
    shipping: {native_to_pt: false, notes: How goods from here reach Portugal.}
```

An HTML site uses `item` (a CSS selector for one result) and `fields` of the
shape `{sel: "css", attr: "text|href|src|data-*"}`. Lazy-loaded images are
handled for you: `attr: src` falls back to `data-src`, `data-lazy` and `srcset`.

**3. Verify it.**

```bash
python scripts/verify_catalog.py -m example_xx      # one live probe
cd backend && pytest                                # catalogue integrity tests
```

The catalogue tests will fail the build if you forget `why`, use an engine that
does not exist, leave out the `{q}` placeholder, ship an `http://` URL, or enable
a low-confidence entry for scraping by default.

**4. Add a fixture test** if the mapping is non-obvious — record one real
response into `backend/tests/fixtures/` and assert on the parsed output. The
existing tests never touch the network, which is deliberate: a suite that
hammers Bazoš on every commit is exactly the behaviour this project tells you
not to have, and it would be red every time a site rotates its markup, which
tells you nothing about whether *our* code works.

## Keeping it alive

Scraped selectors rot. `scripts/verify_catalog.py` issues exactly one search per
marketplace and reports which ones came back empty or broken — run it monthly,
or when a country goes suspiciously quiet. An `EMPTY` result from a generic
query like "iphone" almost always means the selectors moved, not that Europe ran
out of iPhones, and the script flags it as such.

## Being a good guest

Every site here is doing us a favour by existing. The engines are built to be
polite and you should keep them that way:

- **one request per search, never a crawl.** No pagination loops, no following
  into detail pages.
- `rate_limit_rps` in `engine_config` throttles the noisier sites (Kleinanzeigen
  is set to 0.5 req/s).
- A 10-minute response cache means re-filtering in the UI re-hits nobody.
- Check `robots.txt` and the terms before enabling a site in anger; the ones
  that say no are already `manual`.

This is a personal shopping tool making a handful of searches a day. Keep it
that way and it will keep working.
