"""Deliverable (b): credentials are stored, encrypted, locally — and nowhere else."""

import json

import pytest

from ufeu import vault
from ufeu.settings import state_dir


@pytest.fixture(autouse=True)
def clean_vault():
    for market_id in list(vault.status()):
        vault.delete_credentials(market_id)
    yield


def test_credentials_roundtrip():
    vault.set_credentials("ebay", client_id="abc", client_secret="shh")
    stored = vault.get_credentials("ebay")
    assert stored["client_id"] == "abc" and stored["client_secret"] == "shh"
    assert "updated_at" in stored


def test_setting_credentials_merges_rather_than_replaces():
    vault.set_credentials("ebay", client_id="abc", client_secret="shh")
    vault.set_credentials("ebay", access_token="tok")     # what the eBay engine does
    stored = vault.get_credentials("ebay")
    assert stored["client_id"] == "abc" and stored["access_token"] == "tok"


def test_nothing_is_written_to_disk_in_the_clear():
    vault.set_credentials("olx_pt", cookie="session=SUPERSECRETVALUE")
    blob = (state_dir() / "vault.enc").read_bytes()
    assert b"SUPERSECRETVALUE" not in blob
    assert b"olx_pt" not in blob


def test_vault_file_is_not_world_readable():
    vault.set_credentials("olx_pt", cookie="x")
    mode = (state_dir() / "vault.enc").stat().st_mode & 0o777
    assert mode == 0o600


def test_status_exposes_field_names_but_never_values():
    vault.set_credentials("olx_pt", cookie="session=SUPERSECRETVALUE")
    status = vault.status()
    assert status["olx_pt"]["fields"] == ["cookie"]
    assert "SUPERSECRETVALUE" not in json.dumps(status)


def test_missing_credentials_are_an_empty_dict_not_an_error():
    assert vault.get_credentials("never_configured") == {}


def test_delete_reports_whether_anything_was_there():
    vault.set_credentials("olx_pt", cookie="x")
    assert vault.delete_credentials("olx_pt") is True
    assert vault.delete_credentials("olx_pt") is False
