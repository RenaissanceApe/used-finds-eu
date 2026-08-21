"""Deliverable (f): the routes must be sane, and the sanity is testable.

Sofas do not go by parcel post, Portuguese items do not get shipped at all, and
an overlay like a proxy buyer is never allowed to masquerade as a route."""

import pytest

from ufeu.shipping import cheapest_cost, estimate_weight, plan, zone_for


def test_portugal_only_ever_offers_local_pickup():
    options = plan("PT", title="Bicicleta gravel").options
    assert [o.id for o in options] == ["local_pickup"]
    assert options[0].cost_eur == 0.0


def test_spain_is_the_closest_zone_and_cyprus_the_furthest():
    assert zone_for("ES") == 1
    assert zone_for("DE") == 2
    assert zone_for("CY") == 5
    # An unknown code must not crash the resolver mid-search.
    assert zone_for("ZZ") == 4


@pytest.mark.parametrize(
    "title,expected_weight,expected_bulky",
    [
        ("Máquina de lavar Bosch", 65.0, True),
        ("Sofa 3 lugares", 45.0, True),
        ("Nikon D750 camera body", 2.0, False),
        ("iPhone 13 Pro 256GB", 0.6, False),
        ("Bicicleta gravel Canyon", 15.0, True),
        ("something entirely unclassifiable", 2.5, False),
    ],
)
def test_weight_estimation_is_multilingual(title, expected_weight, expected_bulky):
    # A German washing-machine listing will not contain the words "washing machine".
    weight, bulky = estimate_weight(title)
    assert weight == expected_weight
    assert bulky is expected_bulky


def test_bulky_items_never_get_a_parcel_route():
    options = plan("DE", title="Sofa 3 lugares").options
    assert options, "a sofa from Germany must still have some route"
    for option in options:
        assert option.id not in ("prepaid_label", "inpost_locker", "packeta_pickup", "hand_carry")


def test_heavy_items_reach_for_freight_or_a_van():
    ids = [o.id for o in plan("FR", title="Máquina de lavar Bosch").options]
    assert "diaspora_van" in ids and "pallet_freight" in ids
    # France is the densest diaspora corridor, so the van should win on price.
    assert ids[0] == "diaspora_van"


def test_spanish_bulky_goods_prefer_the_land_border():
    ids = [o.id for o in plan("ES", title="Vitra Eames office chair").options]
    assert ids[0] in ("coach_freight", "border_pickup")
    assert "border_pickup" in ids


def test_poland_gets_the_locker_corridor():
    ids = [o.id for o in plan("PL", title="iPhone 13 Pro").options]
    assert ids[0] == "inpost_locker"


def test_platform_native_only_offered_when_the_platform_actually_ships():
    without = [o.id for o in plan("DE", title="Vintage jacket", native_shipping=False).options]
    with_native = [o.id for o in plan("DE", title="Vintage jacket", native_shipping=True).options]
    assert "platform_native" not in without
    assert with_native[0] == "platform_native"


def test_overlays_never_rank_first_or_get_recommended():
    for country in ("DE", "ES", "PL", "EE"):
        options = plan(country, title="Nikon D750").options
        assert not options[0].overlay
        recommended = [o for o in options if o.recommended]
        assert len(recommended) == 1 and not recommended[0].overlay
        # Overlays sort to the very end.
        overlay_positions = [i for i, o in enumerate(options) if o.overlay]
        assert all(i >= len(options) - len(overlay_positions) for i in overlay_positions)


def test_cheapest_cost_ignores_overlays():
    options = plan("DE", title="Nikon D750").options
    primary = [o.cost_eur for o in options if not o.overlay]
    assert cheapest_cost("DE", "Nikon D750") == min(primary)


def test_landed_cost_is_item_plus_shipping():
    option = plan("IT", title="Technics turntable", item_price_eur=500.0).options[0]
    assert option.landed_cost_eur == pytest.approx(500.0 + option.cost_eur)


def test_distance_costs_money():
    near = cheapest_cost("ES", "Nikon D750")
    far = cheapest_cost("EE", "Nikon D750")
    assert far > near


def test_every_route_carries_actionable_instructions():
    for option in plan("DE", title="Nikon D750").options:
        assert option.summary
        assert option.steps or option.providers, f"{option.id} tells the user nothing to do"
        assert 1 <= option.effort <= 5 and 1 <= option.risk <= 5
        assert option.days_min <= option.days_max
        assert option.cost_low_eur <= option.cost_eur <= option.cost_high_eur


def test_pan_eu_listings_get_a_zone_rather_than_the_worst_case():
    # Vinted and eBay do not attribute a listing to one country.
    assert zone_for("EU") == 2
    assert plan("EU", title="Vintage jacket").options
