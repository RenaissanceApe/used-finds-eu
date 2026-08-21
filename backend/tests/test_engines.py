"""Engine tests run against recorded fixtures, never the live sites.

That is deliberate: a test suite that hammers Bazoš on every commit is exactly
the behaviour this project tells you not to have, and a live test would also be
red every time a site rotates its markup — which tells you nothing about
whether *our* code works.
"""

import json

import httpx
import pytest
import respx

from ufeu.adapters import build_engine
from ufeu.adapters.base import NeedsAuth
from ufeu.catalog import load_catalog
from ufeu.models import ResultStatus, SearchQuery


@pytest.fixture
def catalog():
    return load_catalog()


async def _run(market, query, credentials=None):
    async with httpx.AsyncClient() as client:
        engine = build_engine(market, client, credentials or {})
        return await engine.run(query)


@respx.mock
async def test_json_api_rest_mode_marktplaats(catalog, fixtures_dir, query):
    payload = json.loads((fixtures_dir / "marktplaats_search.json").read_text())
    respx.get(url__startswith="https://www.marktplaats.nl/lrp/api/search").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _run(catalog.by_id["marktplaats_nl"], query)

    assert result.status is ResultStatus.OK
    # Three rows in, two out: the third has no title and must be dropped rather
    # than rendered as a blank card.
    assert len(result.listings) == 2

    first = result.listings[0]
    assert first.title == "Nikon D750 body in nette staat"
    assert first.price == pytest.approx(649.00)   # priceCents / 100
    assert first.url.startswith("https://www.marktplaats.nl/v/")
    assert first.location == "Utrecht"
    assert first.seller == "fotojan"
    assert first.posted is not None
    assert first.country == "NL"


@respx.mock
async def test_json_api_next_data_mode_willhaben(catalog, fixtures_dir, query):
    html = (fixtures_dir / "willhaben_next.html").read_text()
    respx.get(url__startswith="https://www.willhaben.at/").mock(
        return_value=httpx.Response(200, text=html)
    )
    result = await _run(catalog.by_id["willhaben_at"], query)

    assert result.status is ResultStatus.OK
    assert [l.title for l in result.listings] == ["Nikon D750 Gehäuse", "Nikon D750 mit Zubehör"]
    assert result.listings[0].price == pytest.approx(690.0)
    # "1.150" is a thousands separator in Austria, not €1.15.
    assert result.listings[1].price == pytest.approx(1150.0)
    assert result.listings[0].location == "Wien, 1070"


@respx.mock
async def test_next_data_missing_blob_is_a_clear_error(catalog, query):
    respx.get(url__startswith="https://www.willhaben.at/").mock(
        return_value=httpx.Response(200, text="<html><body>nope</body></html>")
    )
    result = await _run(catalog.by_id["willhaben_at"], query)
    assert result.status is ResultStatus.ERROR
    assert "__NEXT_DATA__" in result.error


@respx.mock
async def test_html_engine_bazos(catalog, fixtures_dir, query):
    html = (fixtures_dir / "bazos_search.html").read_text()
    respx.get(url__startswith="https://www.bazos.cz/search.php").mock(
        return_value=httpx.Response(200, text=html)
    )
    result = await _run(catalog.by_id["bazos_cz"], query)

    assert result.status is ResultStatus.OK
    assert len(result.listings) == 2
    first = result.listings[0]
    assert first.title == "Nikon D750 tělo"
    assert first.price == pytest.approx(16500.0)
    assert first.currency == "CZK"
    assert first.url == "https://www.bazos.cz/inzerat/1234567/nikon-d750.php"
    assert first.location == "Praha 4"
    # The second card lazy-loads its image via data-src.
    assert result.listings[1].image == "https://www.bazos.cz/img/1/1234568.jpg"


@respx.mock
async def test_html_engine_reports_bot_walls_distinctly(catalog, query):
    respx.get(url__startswith="https://www.bazos.cz/search.php").mock(
        return_value=httpx.Response(200, text="<html><body>Please complete the CAPTCHA</body></html>")
    )
    result = await _run(catalog.by_id["bazos_cz"], query)
    assert result.status is ResultStatus.ERROR
    assert "anti-bot" in result.error


@respx.mock
async def test_html_engine_zero_results_is_empty_not_error(catalog, query):
    respx.get(url__startswith="https://www.bazos.cz/search.php").mock(
        return_value=httpx.Response(200, text="<html><body><p>Nic nenalezeno</p></body></html>")
    )
    result = await _run(catalog.by_id["bazos_cz"], query)
    assert result.status is ResultStatus.EMPTY
    assert result.error is None


@respx.mock
async def test_vinted_bootstraps_a_session_then_searches(catalog, fixtures_dir):
    payload = json.loads((fixtures_dir / "vinted_items.json").read_text())
    home = respx.get("https://www.vinted.pt/").mock(
        return_value=httpx.Response(200, text="<html></html>", headers={"set-cookie": "access_token_web=abc; Path=/"})
    )
    api = respx.get(url__startswith="https://www.vinted.pt/api/v2/catalog/items").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _run(catalog.by_id["vinted"], SearchQuery(q="levis 501", limit=10))

    assert home.called and api.called
    assert result.status is ResultStatus.OK
    first = result.listings[0]
    assert first.price == pytest.approx(24.0)
    assert first.currency == "EUR"
    assert first.description == "Levi's · W32"   # brand · size
    assert first.ships is True
    # The second item only has thumbnails, no full-size photo.
    assert result.listings[1].image == "https://images.vinted.net/b.jpg"


@respx.mock
async def test_vinted_retries_once_on_401(catalog, fixtures_dir):
    payload = json.loads((fixtures_dir / "vinted_items.json").read_text())
    respx.get("https://www.vinted.pt/").mock(return_value=httpx.Response(200, text="<html></html>"))
    route = respx.get(url__startswith="https://www.vinted.pt/api/v2/catalog/items").mock(
        side_effect=[httpx.Response(401, json={}), httpx.Response(200, json=payload)]
    )
    result = await _run(catalog.by_id["vinted"], SearchQuery(q="levis 501", limit=10))
    assert route.call_count == 2
    assert result.status is ResultStatus.OK


@respx.mock
async def test_olx_maps_params_photos_and_delivery(catalog, fixtures_dir):
    payload = json.loads((fixtures_dir / "olx_offers.json").read_text())
    respx.get(url__startswith="https://www.olx.pl/api/v1/offers/").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _run(catalog.by_id["olx_pl"], SearchQuery(q="iphone 13 pro", limit=10))

    assert result.status is ResultStatus.OK
    first = result.listings[0]
    assert first.price == pytest.approx(1899.0)
    assert first.currency == "PLN"
    assert first.location == "Kraków, Małopolskie"
    assert first.condition == "Używane"
    assert first.ships is True
    # OLX photo links are templates and must be filled in, not passed through.
    assert "{width}" not in first.image and "s=640x480" in first.image
    # "Za darmo" (free) is a real price of zero, not a parse failure.
    assert result.listings[1].price == 0.0


async def test_ebay_without_credentials_asks_for_them(catalog, query):
    result = await _run(catalog.by_id["ebay"], query, credentials={})
    assert result.status is ResultStatus.NEEDS_AUTH
    assert "developer.ebay.com" in result.error


@respx.mock
async def test_ebay_fans_out_across_marketplaces(catalog):
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
    )
    respx.get(url__startswith="https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(200, json={"itemSummaries": [{
            "itemId": "v1|123|0", "title": "Nikon D750", "itemWebUrl": "https://www.ebay.de/itm/123",
            "price": {"value": "699.00", "currency": "EUR"}, "condition": "Used",
            "image": {"imageUrl": "https://i.ebayimg.com/a.jpg"},
            "itemLocation": {"country": "DE"}, "seller": {"username": "shop_de"},
            "shippingOptions": [{"shippingCost": {"value": "12.0"}}],
        }]})
    )
    market = catalog.by_id["ebay"]
    result = await _run(market, SearchQuery(q="nikon d750", limit=18),
                        credentials={"client_id": "id", "client_secret": "secret"})

    assert result.status is ResultStatus.OK
    # One row per configured eBay site, each attributed to its own country.
    assert len(result.listings) == len(market.engine_config["marketplaces"])
    assert {l.country for l in result.listings} == {"DE", "FR", "IT", "ES", "IE", "NL", "AT", "BE", "PL"}
    assert all(l.marketplace_name.startswith("eBay ") for l in result.listings)


async def test_manual_engine_returns_a_clickable_url_not_a_failure(catalog):
    result = await _run(catalog.by_id["leboncoin_fr"], SearchQuery(q="vélo gravel", limit=5))
    assert result.status is ResultStatus.MANUAL
    assert result.search_url == "https://www.leboncoin.fr/recherche?text=v%C3%A9lo%20gravel"
    assert result.listings == []


@respx.mock
async def test_http_errors_become_readable_rows(catalog, query):
    respx.get(url__startswith="https://www.bazos.cz/search.php").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    result = await _run(catalog.by_id["bazos_cz"], query)
    assert result.status is ResultStatus.ERROR
    assert "429" in result.error and "rate limited" in result.error


@respx.mock
async def test_network_failure_does_not_raise(catalog, query):
    respx.get(url__startswith="https://www.bazos.cz/search.php").mock(
        side_effect=httpx.ConnectError("no route to host")
    )
    result = await _run(catalog.by_id["bazos_cz"], query)
    assert result.status is ResultStatus.ERROR
    assert "network error" in result.error


async def test_blocket_requires_a_bearer_token(catalog, query):
    result = await _run(catalog.by_id["blocket_se"], query, credentials={})
    assert result.status is ResultStatus.NEEDS_AUTH
    assert "bearer" in result.error.lower()


# ── self-diagnosis ────────────────────────────────────────────────────────
# The verify run against live sites showed the expensive failure mode is not a
# crash but silence: a site redesigns, the selector matches nothing, and the
# result is indistinguishable from "no listings". These cover the machinery
# that tells us which it was.

@respx.mock
async def test_html_engine_suggests_selectors_when_its_own_have_rotted(catalog, fixtures_dir, query):
    """maltapark returned 200 with 0 listings in the live probe — this is that."""
    html = (fixtures_dir / "redesigned_site.html").read_text()
    respx.get(url__startswith="https://www.maltapark.com/search").mock(
        return_value=httpx.Response(200, text=html)
    )
    result = await _run(catalog.by_id["maltapark_mt"], query)

    assert result.status is ResultStatus.ERROR
    assert "matched nothing" in result.error
    # The real selector must be in the suggestions, with a sample to confirm it.
    assert "article.listing-card" in result.error
    assert "iPhone" in result.error


@respx.mock
async def test_html_engine_still_reports_plain_empty_when_the_page_has_no_rows(catalog, query):
    respx.get(url__startswith="https://www.maltapark.com/search").mock(
        return_value=httpx.Response(200, text="<html><body><p>No results found</p></body></html>")
    )
    result = await _run(catalog.by_id["maltapark_mt"], query)
    assert result.status is ResultStatus.EMPTY
    assert result.error is None


@respx.mock
async def test_block_detection_beats_selector_suggestion(catalog, fixtures_dir, query):
    """A blocked page can still contain repeated markup; don't send someone
    chasing selectors when the real problem is the IP."""
    html = (fixtures_dir / "redesigned_site.html").read_text().replace(
        "<header", "<p>Just a moment... checking your browser</p><header"
    )
    respx.get(url__startswith="https://www.maltapark.com/search").mock(
        return_value=httpx.Response(200, text=html)
    )
    result = await _run(catalog.by_id["maltapark_mt"], query)
    assert "anti-bot" in result.error


@respx.mock
async def test_json_engine_reports_where_the_data_actually_is(catalog, query):
    """dba_dk/tori_fi class of failure: page still renders, our root is stale."""
    payload = {"props": {"pageProps": {"searchResults": {
        "items": [{"id": i, "heading": f"iPhone {i}"} for i in range(30)]
    }}}}
    respx.get(url__startswith="https://www.dba.dk/").mock(
        return_value=httpx.Response(200, text=(
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload) + "</script></body></html>"
        ))
    )
    result = await _run(catalog.by_id["dba_dk"], query)

    assert result.status is ResultStatus.ERROR
    assert "resolved to nothing" in result.error
    # It must name the real path so fixing the YAML is a copy-paste.
    assert "props.pageProps.searchResults.items (30 items)" in result.error
    assert "__NEXT_DATA__" in result.error


@respx.mock
async def test_json_engine_reads_nuxt_and_plain_json_script_tags(catalog, query):
    """Not every server-rendered site is Next.js; don't fail just because of that."""
    payload = {"data": {"docs": [
        {"id": 1, "heading": "iPhone 13", "price": {"amount": 430},
         "canonical_url": "https://www.dba.dk/i/1"},
    ]}}
    respx.get(url__startswith="https://www.dba.dk/").mock(
        return_value=httpx.Response(200, text=(
            "<html><body><script>window.__NUXT__ = " + json.dumps(payload) + ";</script></body></html>"
        ))
    )
    market = catalog.by_id["dba_dk"].model_copy(deep=True)
    market.engine_config["root"] = "data.docs"
    result = await _run(market, query)

    assert result.status is ResultStatus.OK
    assert result.listings[0].title == "iPhone 13"
    assert result.listings[0].price == pytest.approx(430.0)


@respx.mock
async def test_json_engine_names_the_app_router_problem_precisely(catalog, query):
    """A streamed flight payload cannot be guessed at — say so rather than
    silently returning nothing or inventing a parse."""
    respx.get(url__startswith="https://www.tori.fi/").mock(
        return_value=httpx.Response(200, text=(
            '<html><body><script>self.__next_f.push([1,"a:[\\"$\\",\\"div\\"]"])</script></body></html>'
        ))
    )
    result = await _run(catalog.by_id["tori_fi"], query)
    assert result.status is ResultStatus.ERROR
    assert "App Router" in result.error
    assert "network tab" in result.error


def test_suggest_roots_ranks_by_size_and_skips_scalar_arrays():
    from ufeu.adapters.json_api import suggest_roots

    hints = suggest_roots({
        "small": [{"a": 1}, {"a": 2}],
        "big": {"nested": [{"a": i} for i in range(50)]},
        "scalars": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "empty": [],
    })
    assert hints[0].startswith("big.nested (50 items)")
    assert any(h.startswith("small (2 items)") for h in hints)
    assert not any("scalars" in h for h in hints)
