"""The CLI is the headless half of the UI; it must not regress silently."""

import os

import pytest

from ufeu.cli import main


@pytest.fixture(autouse=True)
def demo_mode():
    os.environ["UFEU_DEMO"] = "1"
    yield
    os.environ.pop("UFEU_DEMO", None)


def test_catalog_command_lists_every_country(capsys):
    assert main(["catalog"]) == 0
    out = capsys.readouterr().out
    for country in ("Portugal (PT)", "Germany (DE)", "Malta (MT)", "Cyprus (CY)"):
        assert country in out
    assert "shipping zone" in out


def test_ship_command_explains_the_route(capsys):
    assert main(["ship", "ES", "-i", "sofa", "-p", "150"]) == 0
    out = capsys.readouterr().out
    assert "ES → PT" in out
    assert "Spanish border pickup" in out
    assert "★" in out          # exactly one recommended route


def test_search_command_prints_landed_costs(capsys):
    assert main(["search", "lego", "-n", "3", "--sort", "landed_asc"]) == 0
    out = capsys.readouterr().out
    assert "landed" in out
    assert "marketplaces in" in out


def test_search_json_output_is_machine_readable(capsys):
    import json

    assert main(["search", "lego", "-n", "2", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "listings" in payload and "stats" in payload


def test_accounts_set_rejects_an_unknown_marketplace(capsys):
    assert main(["accounts", "set", "not_a_site", "--cookie", "x"]) == 1
