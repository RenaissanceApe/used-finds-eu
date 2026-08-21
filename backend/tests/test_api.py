"""API surface: deliverable (c) — what the UI actually talks to."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ["UFEU_DEMO"] = "1"          # no live marketplace traffic in tests
    from ufeu.api import app

    with TestClient(app) as test_client:
        yield test_client
    os.environ.pop("UFEU_DEMO", None)


def test_health_reports_mode_and_freshness(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["home_country"] == "PT"
    assert "fx_stale" in body and "catalog_updated" in body


def test_catalog_lists_every_country_with_its_shipping_zone(client):
    body = client.get("/api/catalog").json()
    codes = {c["code"] for c in body["countries"]}
    assert len(codes) >= 27
    assert all("zone" in c for c in body["countries"])
    assert any(m["scope"] == "pan_eu" for m in body["marketplaces"])
    # The UI needs to explain each pick to the user.
    assert all(m["why"] for m in body["marketplaces"])


def test_search_returns_listings_stats_and_per_market_results(client):
    body = client.post("/api/search", json={"q": "nikon d750", "limit": 5}).json()
    assert body["stats"]["markets_queried"] > 20
    assert body["listings"]
    first = body["listings"][0]
    for field in ("title", "url", "country", "marketplace_name", "price_eur", "landed_cost_eur"):
        assert field in first
    assert len(body["results"]) == body["stats"]["markets_queried"]


def test_search_can_be_scoped_to_countries(client):
    body = client.post("/api/search", json={"q": "lego", "limit": 5, "countries": ["ES", "PT"]}).json()
    assert {r["country"] for r in body["results"]} <= {"ES", "PT", "EU"}


def test_search_rejects_an_empty_query(client):
    assert client.post("/api/search", json={"q": "   "}).status_code == 400


def test_search_limit_is_clamped(client):
    body = client.post("/api/search", json={"q": "lego", "limit": 100000}).json()
    assert body["query"]["limit"] <= 100


def test_price_filters_apply_in_eur_across_currencies(client):
    body = client.post("/api/search", json={"q": "lego", "limit": 30, "max_price_eur": 100}).json()
    assert all(l["price_eur"] is None or l["price_eur"] <= 100 for l in body["listings"])


def test_landed_sort_orders_by_delivered_cost(client):
    body = client.post("/api/search", json={"q": "lego", "limit": 20, "sort": "landed_asc"}).json()
    landed = [l["landed_cost_eur"] for l in body["listings"] if l["landed_cost_eur"] is not None]
    assert landed == sorted(landed)


def test_shipping_endpoint_ranks_routes(client):
    body = client.get("/api/shipping", params={"country": "DE", "title": "sofa", "price_eur": 200}).json()
    assert body["country"] == "DE" and body["bulky"] is True
    assert body["options"] and body["options"][0]["recommended"] is True


def test_shipping_endpoint_rejects_a_bad_country_code(client):
    assert client.get("/api/shipping", params={"country": "GERMANY"}).status_code == 422


def test_accounts_roundtrip_never_echoes_the_secret(client):
    assert client.put("/api/accounts/ebay", json={"client_id": "id", "client_secret": "s3cret"}).status_code == 200

    rows = {row["id"]: row for row in client.get("/api/accounts").json()["accounts"]}
    assert rows["ebay"]["configured"] is True
    assert "client_secret" in rows["ebay"]["fields"]
    # Field *names* are safe to show; values must never leave the vault.
    assert "s3cret" not in client.get("/api/accounts").text

    assert client.delete("/api/accounts/ebay").json()["ok"] is True
    rows = {row["id"]: row for row in client.get("/api/accounts").json()["accounts"]}
    assert rows["ebay"]["configured"] is False


def test_accounts_reject_unknown_marketplaces_and_empty_payloads(client):
    assert client.put("/api/accounts/not_a_real_site", json={"cookie": "x"}).status_code == 404
    assert client.put("/api/accounts/ebay", json={}).status_code == 400


def test_ui_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "used-finds-eu" in response.text
