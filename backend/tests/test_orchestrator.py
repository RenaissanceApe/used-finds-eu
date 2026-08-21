"""Fan-out behaviour: deliverable (e). Merging is where the value is added."""

import httpx
import pytest
import respx

from ufeu import fx
from ufeu.models import Listing, ResultStatus, SearchQuery
from ufeu.orchestrator import _annotate_shipping, _canonical_url, _dedupe, search


def _listing(**kwargs) -> Listing:
    base = dict(
        id="x", marketplace_id="m", marketplace_name="M", country="DE",
        title="Nikon D750 body", url="https://example.com/a",
    )
    base.update(kwargs)
    return Listing(**base)


def test_canonical_url_ignores_tracking_noise():
    a = _canonical_url("https://Example.com/item/1?utm_source=x&ref=y")
    b = _canonical_url("https://example.com/item/1/")
    assert a == b


def test_canonical_url_keeps_meaningful_query_params():
    assert "id=42" in _canonical_url("https://example.com/view?id=42&utm_medium=mail")


def test_dedupe_collapses_the_same_url():
    kept, dropped = _dedupe([
        _listing(url="https://example.com/a"),
        _listing(url="https://example.com/a?utm_source=newsletter"),
        _listing(url="https://example.com/b"),
    ])
    assert len(kept) == 2 and dropped == 1


def test_dedupe_collapses_vinteds_shared_pool_across_domains():
    """The same jumper served by vinted.pt and vinted.es is one item, not two."""
    kept, dropped = _dedupe([
        _listing(url="https://www.vinted.pt/items/1", dedupe_group="vinted",
                 title="Levis 501 vintage", price_eur=24.0),
        _listing(url="https://www.vinted.es/items/2", dedupe_group="vinted",
                 title="501 Levis vintage", price_eur=24.0),
    ])
    assert len(kept) == 1 and dropped == 1


def test_dedupe_keeps_genuinely_different_items_in_the_same_group():
    kept, _ = _dedupe([
        _listing(url="https://www.vinted.pt/items/1", dedupe_group="vinted",
                 title="Levis 501", price_eur=24.0),
        _listing(url="https://www.vinted.pt/items/2", dedupe_group="vinted",
                 title="Levis 501", price_eur=39.0),
    ])
    assert len(kept) == 2


def test_dedupe_does_not_cross_marketplaces_without_a_group():
    """Two shops legitimately listing the same model at the same price are two
    offers, and collapsing them would hide the cheaper seller's competition."""
    kept, dropped = _dedupe([
        _listing(url="https://olx.pl/x", marketplace_id="olx_pl", price_eur=100.0),
        _listing(url="https://bazos.cz/y", marketplace_id="bazos_cz", price_eur=100.0),
    ])
    assert len(kept) == 2 and dropped == 0


def test_shipping_annotation_adds_landed_cost():
    listings = [_listing(country="DE", price_eur=600.0), _listing(country="PT", price_eur=650.0, url="https://olx.pt/1")]
    _annotate_shipping(listings)
    german, portuguese = listings
    assert german.shipping_cost_eur > 0
    assert german.landed_cost_eur == pytest.approx(600.0 + german.shipping_cost_eur)
    # Buying at home costs nothing to move.
    assert portuguese.shipping_strategy == "local_pickup"
    assert portuguese.landed_cost_eur == pytest.approx(650.0)


def test_currency_conversion_makes_prices_comparable():
    table = fx.load()
    # 1899 PLN is roughly €440, not €1899.
    converted = table.to_eur(1899.0, "PLN")
    assert 300 < converted < 600
    assert table.to_eur(100.0, "EUR") == 100.0
    assert table.to_eur(None, "PLN") is None


@respx.mock
async def test_search_survives_a_marketplace_that_is_completely_down():
    """One dead site must not take down a 30-site fan-out."""
    respx.route(host="www.bazos.cz").mock(side_effect=httpx.ConnectError("down"))
    respx.route(host="www.bazos.sk").mock(side_effect=httpx.ConnectError("down"))
    respx.route().mock(return_value=httpx.Response(200, json={"data": []}))

    response = await search(SearchQuery(q="nikon d750", limit=5, fresh=True,
                                        marketplaces=["bazos_cz", "bazos_sk", "olx_pt"]))
    statuses = {r.marketplace_id: r.status for r in response.results}
    assert statuses["bazos_cz"] is ResultStatus.ERROR
    assert statuses["olx_pt"] in (ResultStatus.OK, ResultStatus.EMPTY)
    assert response.stats.markets_failed == 2
    # Failures stay visible instead of quietly shrinking the result set.
    assert response.stats.markets_queried == 3


@respx.mock
async def test_manual_marketplaces_report_a_link_without_a_request():
    route = respx.route().mock(return_value=httpx.Response(200, text=""))
    response = await search(SearchQuery(q="vélo", limit=5, fresh=True, marketplaces=["leboncoin_fr"]))
    assert not route.called, "manual marketplaces must never be requested"
    assert response.stats.markets_manual == 1
    assert response.results[0].search_url.startswith("https://www.leboncoin.fr/recherche?text=")
