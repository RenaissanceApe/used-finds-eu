"""The catalogue is the product as much as the code is — deliverable (a).
These tests are what stop it rotting into a list of dead links."""

import pytest

from ufeu.adapters import ENGINES
from ufeu.catalog import load_catalog

EU27 = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_every_eu_member_state_has_a_number_one_pick(catalog):
    """The whole promise of (a): no country left without an answer."""
    missing = {code for code in EU27 if not any(m.rank == 1 for m in catalog.for_country(code))}
    assert not missing, f"no rank-1 marketplace for: {sorted(missing)}"


def test_every_eu_member_state_has_a_marketplace_enabled_by_default(catalog):
    covered = {m.country for m in catalog.select()}
    # Pan-EU sites (Vinted, eBay) cover the rest through their own country pools.
    uncovered = EU27 - covered
    assert not uncovered, f"nothing searched by default in: {sorted(uncovered)}"


def test_marketplace_ids_are_unique(catalog):
    ids = [m.id for m in catalog.marketplaces]
    assert len(ids) == len(set(ids))


def test_every_engine_named_in_the_catalog_exists(catalog):
    unknown = {m.engine for m in catalog.marketplaces} - set(ENGINES)
    assert not unknown, f"catalog references engines that do not exist: {unknown}"


def test_search_urls_are_https_and_carry_the_query_placeholder(catalog):
    # vinted/olx/ebay build their request parameters in code and use search_url
    # only as the API base, so the placeholder rule does not apply to them.
    templated = {"json_api", "html", "manual"}
    for market in catalog.marketplaces:
        url = market.engine_config.get("search_url")
        if not url or market.engine not in templated:
            continue
        assert url.startswith("https://"), f"{market.id}: search_url is not https"
        # POST engines carry the term in the body template instead of the URL.
        where = url + (market.engine_config.get("body") or "")
        assert "{q}" in where, f"{market.id}: no {{q}} placeholder in search_url or body"


def test_site_urls_are_https(catalog):
    for market in catalog.marketplaces:
        assert market.site.startswith("https://"), f"{market.id}: site is not https"


def test_html_engines_declare_an_item_selector_and_a_title(catalog):
    for market in catalog.marketplaces:
        if market.engine != "html":
            continue
        assert market.engine_config.get("item"), f"{market.id}: html engine needs engine_config.item"
        fields = market.engine_config.get("fields", {})
        assert "title" in fields and "url" in fields, f"{market.id}: html engine needs title and url fields"


def test_json_engines_declare_a_root_and_a_title(catalog):
    for market in catalog.marketplaces:
        if market.engine != "json_api":
            continue
        assert market.engine_config.get("root"), f"{market.id}: json engine needs engine_config.root"
        assert market.engine_config.get("fields", {}).get("title"), f"{market.id}: json engine needs a title mapping"


def test_every_marketplace_explains_why_it_is_in_the_catalog(catalog):
    missing = [m.id for m in catalog.marketplaces if not (m.why or "").strip()]
    assert not missing, f"no rationale recorded for: {missing}"


def test_sites_needing_credentials_say_where_to_get_them(catalog):
    for market in catalog.marketplaces:
        if market.account.required_for_search:
            assert market.account.signup_url or market.account.notes, (
                f"{market.id} needs an account but gives the user no way to make one"
            )


def test_low_confidence_entries_are_not_silently_trusted(catalog):
    """A low-confidence "most used" claim must not be enabled by default without
    being flagged in its rationale, or the user inherits our guess as fact."""
    for market in catalog.marketplaces:
        if market.confidence == "low" and market.default_enabled:
            assert market.engine == "manual", (
                f"{market.id}: low-confidence entry is scraped by default"
            )


def test_explicit_marketplace_selection_overrides_the_enabled_flag(catalog):
    off_by_default = next(m for m in catalog.marketplaces if not m.default_enabled)
    selected = catalog.select(marketplace_ids=[off_by_default.id])
    assert [m.id for m in selected] == [off_by_default.id]


def test_country_selection_keeps_pan_eu_sites(catalog):
    selected = catalog.select(countries=["PT"])
    assert any(m.scope == "pan_eu" for m in selected)
    assert all(m.country in ("PT", "EU") for m in selected)


def test_vinted_national_domains_share_a_dedupe_group(catalog):
    vinted = [m for m in catalog.marketplaces if m.engine == "vinted"]
    assert len(vinted) > 20
    assert all(m.dedupe_group == "vinted" for m in vinted)
    # Only one is on by default, or every search returns the same item 24 times.
    assert sum(1 for m in vinted if m.default_enabled) == 1
