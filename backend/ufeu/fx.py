"""EUR conversion, with an offline fallback so the app is never useless.

Rates come from the ECB's public daily reference feed (no key, no ToS issue),
cached to disk for a day. If the network is unavailable — or the machine is
behind a proxy that blocks it — we fall back to a baked-in table. Converted
prices are then flagged ``stale`` so the UI can say so rather than quietly
lying about a Hungarian price.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from .settings import REQUEST_TIMEOUT, state_dir

log = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# Units of foreign currency per 1 EUR. Rough mid-2026 levels; only used when
# the live feed cannot be reached.
FALLBACK_RATES: dict[str, float] = {
    "EUR": 1.0, "USD": 1.08, "GBP": 0.85, "CHF": 0.95,
    "SEK": 11.30, "DKK": 7.46, "NOK": 11.60,
    "PLN": 4.28, "CZK": 25.10, "HUF": 395.0,
    "RON": 4.97, "BGN": 1.9558,  # BGN is pegged
}

_CACHE_FILE = "fx-rates.xml"
_MAX_AGE = timedelta(hours=24)


class FxTable:
    def __init__(self, rates: dict[str, float], as_of: datetime | None, stale: bool) -> None:
        self.rates = rates
        self.as_of = as_of
        self.stale = stale

    def to_eur(self, amount: float | None, currency: str) -> float | None:
        if amount is None:
            return None
        rate = self.rates.get((currency or "EUR").upper())
        if not rate:
            return None
        return round(amount / rate, 2)


def _parse(xml_text: str) -> tuple[dict[str, float], datetime | None]:
    root = ET.fromstring(xml_text)
    rates: dict[str, float] = {"EUR": 1.0}
    as_of: datetime | None = None
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag != "Cube":
            continue
        if "time" in node.attrib:
            try:
                as_of = datetime.strptime(node.attrib["time"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        if "currency" in node.attrib and "rate" in node.attrib:
            try:
                rates[node.attrib["currency"].upper()] = float(node.attrib["rate"])
            except ValueError:
                continue
    return rates, as_of


_memo: FxTable | None = None


def load(force: bool = False) -> FxTable:
    """Return the current rate table, refreshing from the ECB at most daily."""
    global _memo
    if _memo is not None and not force:
        return _memo

    path = state_dir() / _CACHE_FILE
    if path.exists() and not force:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if age < _MAX_AGE:
            try:
                rates, as_of = _parse(path.read_text(encoding="utf-8"))
                _memo = FxTable(rates, as_of, stale=False)
                return _memo
            except ET.ParseError:
                log.warning("cached FX file was corrupt; refetching")

    try:
        response = httpx.get(ECB_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        rates, as_of = _parse(response.text)
        path.write_text(response.text, encoding="utf-8")
        _memo = FxTable(rates, as_of, stale=False)
    except Exception as exc:  # network, proxy, malformed feed — all non-fatal
        log.warning("ECB FX feed unavailable (%s); using built-in fallback rates", exc)
        if path.exists():
            try:
                rates, as_of = _parse(path.read_text(encoding="utf-8"))
                _memo = FxTable(rates, as_of, stale=True)
                return _memo
            except ET.ParseError:
                pass
        _memo = FxTable(dict(FALLBACK_RATES), None, stale=True)
    return _memo


def to_eur(amount: float | None, currency: str) -> float | None:
    return load().to_eur(amount, currency)
