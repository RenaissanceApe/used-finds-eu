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

Scraped selectors rot, and sites block. Those need opposite responses, so the
tooling separates them.

**`scripts/verify_catalog.py`** issues exactly one search per marketplace and
groups the results by *cause*: working / broken / blocked / needs-credentials /
manual. Run it monthly, or when a country goes quiet.

**`scripts/probe_site.py <id>`** inspects a single marketplace and reports what
its response actually contains — whether the configured CSS selector or JSON
root still resolves, and if not, what the repeated listing-shaped elements or
the largest arrays-of-objects are. It exists so that fixing a rotted entry is
reading one command's output and pasting a path into YAML, rather than scrolling
through minified HTML.

Both engines also diagnose themselves during a normal search. The HTML engine,
on zero matches, distinguishes an anti-bot page from a genuinely empty result
from a rotted selector — and in the last case reports candidate selectors with
a text sample. The JSON engine tries `__NEXT_DATA__`, `window.__NUXT__` /
`__INITIAL_STATE__`, and `application/json` script tags before giving up, and
names the largest arrays in the payload when the configured `root` resolves to
nothing.

### What the first live verification found (2026-08-21)

Run from a GitHub Codespace — an Azure datacenter IP — against 31 marketplaces:

| Outcome | Count | Notes |
| --- | --- | --- |
| Working | 10 | willhaben, 2dehands, Bazoš ×2, Kleinanzeigen, Wallapop, Vinted, SS.lv, Marktplaats, Bolha |
| Blocked | 12 | OLX ×4, Subito, Adverts.ie, Okidoki, Jófogás, Skelbiu, Vendora, Bazaraki, Njuškalo |
| Broken | 4 | dba.dk, tori.fi (both dropped `__NEXT_DATA__`), CustoJusto (404), MaltaPark (selectors) |
| Needs credentials | 2 | eBay, Blocket |
| Manual by design | 3 | leboncoin, Facebook, Luxauto |

### Re-run from a residential connection (same day)

The obvious hypothesis — datacenter IP reputation — turned out to be **wrong**.
Re-running from a residential connection in Portugal moved only two sites
(Jófogás and Vendora now reach the page and fail on selectors instead). Ten
still refused, in 109–167ms, `olx.pt` among them.

**A Portuguese address, refused by the Portuguese OLX, in 116ms.** That rules
out geo-fencing and IP reputation together, and it is far too fast for anything
to have read the request. What is left is the handshake: Python's TLS
ClientHello (JA3/JA4) and HTTP/2 SETTINGS frame match no browser, and
Cloudflare, Akamai and DataDome reject on that signature at the edge.

Hence `ufeu/http.py` and the optional `curl_cffi` transport, which reproduces
Chrome's exact fingerprint. `impersonate: chrome124` is set on those ten
entries. It is optional on purpose — without it they simply keep returning 403,
and the other twenty-one sources are unaffected.

The lesson worth keeping: *fast* refusals are about who you appear to be, not
what you asked for. Distinguishing "blocked at the edge" from "blocked after
inspection" is worth more than any individual selector fix.

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
