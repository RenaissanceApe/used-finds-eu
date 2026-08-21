"""Price parsing is where an aggregator silently goes wrong, so it gets the
most tests: a decimal comma read as a thousands separator is a 100x error."""

import pytest

from ufeu.normalize import (
    is_negotiable,
    parse_datetime,
    parse_price,
    relevance,
    slugify,
    tokenize,
)


@pytest.mark.parametrize(
    "raw,expected_amount,expected_currency",
    [
        ("1.234,56 €", 1234.56, "EUR"),      # German/Portuguese formatting
        ("€1,234.56", 1234.56, "EUR"),       # Irish/anglophone formatting
        ("1.200 €", 1200.0, "EUR"),          # thousands, not 1.2
        ("35,00 €", 35.0, "EUR"),            # decimal, not 3500
        ("2.500", 2500.0, "EUR"),
        ("12 345 Kč", 12345.0, "CZK"),
        ("1 234 500 Ft", 1234500.0, "HUF"),
        ("450 zł", 450.0, "PLN"),
        ("1,5 lei", 1.5, "RON"),
        ("199 лв", 199.0, "BGN"),
        (129900, 129900.0, "EUR"),
        (49.99, 49.99, "EUR"),
    ],
)
def test_parse_price_across_locales(raw, expected_amount, expected_currency):
    amount, currency = parse_price(raw, "EUR")
    assert amount == pytest.approx(expected_amount)
    assert currency == expected_currency


@pytest.mark.parametrize("raw", ["Preis auf Anfrage", "", None, "—"])
def test_unparseable_prices_are_none_not_zero(raw):
    # A zero would sort to the top of a cheapest-first list and read as a bargain.
    amount, _ = parse_price(raw, "EUR")
    assert amount is None


@pytest.mark.parametrize("raw", ["Gratis", "kostenlos", "grátis", "zdarma", "Free"])
def test_free_is_zero_not_none(raw):
    amount, _ = parse_price(raw, "EUR")
    assert amount == 0.0


def test_zero_and_negative_numerics_are_rejected():
    assert parse_price(0, "EUR")[0] is None
    assert parse_price(-5, "EUR")[0] is None


def test_currency_defaults_to_the_sites_own():
    assert parse_price("2 500", "SEK") == (2500.0, "SEK")


def test_slugify_matches_kleinanzeigen_shape():
    assert slugify("Nikon D750 (körperlich) — Ähnlich") == "nikon-d750-korperlich-ahnlich"
    assert slugify("!!!") == "x"


def test_relevance_prefers_exact_model_matches():
    strong = relevance("nikon d750", "Nikon D750 body 24MP")
    weak = relevance("nikon d750", "Camera bag for assorted cameras")
    assert strong == 1.0
    assert weak < strong


def test_relevance_of_empty_query_is_zero():
    assert relevance("", "anything") == 0.0


def test_tokenize_strips_accents():
    assert tokenize("Câmara fotográfica") == ["camara", "fotografica"]


def test_parse_datetime_handles_seconds_and_milliseconds():
    assert parse_datetime(1_700_000_000).year == 2023
    assert parse_datetime(1_700_000_000_000).year == 2023
    assert parse_datetime("2026-03-04T10:00:00Z").month == 3
    assert parse_datetime("not a date at all") is None


def test_is_negotiable():
    assert is_negotiable("90 € VB")
    assert not is_negotiable("90 €")
