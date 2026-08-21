"""Turning 20 countries' worth of messy strings into comparable numbers.

Price parsing is the single most error-prone part of an aggregator like this.
"1.234,56 €" (Germany), "€1,234.56" (Ireland), "12 345 Kč" (Czechia) and
"1 234 500 Ft" (Hungary) all mean different things, and getting the decimal
separator wrong is a 100x error that silently poisons every price comparison.
So the rules here are explicit rather than clever.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from dateutil import parser as dateparser

# Symbol / suffix → ISO code. Order matters: longest tokens are tried first so
# "kn" does not shadow "k".
_CURRENCY_TOKENS: list[tuple[str, str]] = [
    ("eur", "EUR"), ("€", "EUR"),
    ("czk", "CZK"), ("kč", "CZK"), ("kc", "CZK"),
    ("pln", "PLN"), ("zł", "PLN"), ("zl", "PLN"),
    ("huf", "HUF"), ("ft", "HUF"),
    ("ron", "RON"), ("lei", "RON"),
    ("bgn", "BGN"), ("лв", "BGN"), ("lv", "BGN"),
    ("sek", "SEK"), ("dkk", "DKK"), ("nok", "NOK"),
    ("gbp", "GBP"), ("£", "GBP"),
    ("usd", "USD"), ("$", "USD"),
    ("chf", "CHF"),
    ("kr", None),  # ambiguous across SE/DK/NO — resolved by the site default
]

_FREE_WORDS = {
    "gratis", "free", "zdarma", "za darmo", "ingyen", "ingyenes", "gratuit",
    "grátis", "gratuito", "kostenlos", "verschenken", "zu verschenken",
    "besplatno", "brezplacno", "bezmaksas", "nemokamai", "gratuito", "regalo",
    "δωρεάν", "безплатно", "gratuit", "bezplatne", "za free",
}

_NEGOTIABLE_WORDS = {"vb", "verhandlungsbasis", "negociável", "negociable", "trattabile", "ono", "obo"}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def detect_currency(text: str, default: str = "EUR") -> str:
    low = text.lower()
    for token, code in _CURRENCY_TOKENS:
        if token in low:
            return code or default
    return default


def parse_price(value, default_currency: str = "EUR") -> tuple[float | None, str]:
    """Parse a price out of anything a marketplace might hand us.

    Returns ``(amount, currency)``. ``amount`` is ``None`` for "free", "swap
    only", "price on request" and anything unparseable — never 0.0, because a
    zero would sort to the top of a price-ascending list and look like a bargain.
    """
    if value is None:
        return None, default_currency
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = float(value)
        return (amount if amount > 0 else None), default_currency

    text = str(value).strip()
    if not text:
        return None, default_currency

    currency = detect_currency(text, default_currency)
    low = _strip_accents(text.lower())
    if any(word in low for word in (_strip_accents(w) for w in _FREE_WORDS)):
        return 0.0, currency

    # Keep digits and separators only.
    cleaned = re.sub(r"[^\d.,\s ']", "", text).replace(" ", " ").replace("'", " ")
    cleaned = cleaned.strip()
    if not cleaned or not re.search(r"\d", cleaned):
        return None, currency

    # Decide what the last separator means. If exactly two digits follow it and
    # there is more than one separator kind (or the group is not 3 long), it is
    # a decimal point; otherwise it is a thousands separator.
    last_sep_match = None
    for m in re.finditer(r"[.,]", cleaned):
        last_sep_match = m
    if last_sep_match:
        tail = cleaned[last_sep_match.end():]
        tail_digits = re.sub(r"\D", "", tail)
        is_decimal = len(tail_digits) in (1, 2) and " " not in tail
        if is_decimal:
            head = cleaned[: last_sep_match.start()]
            cleaned = re.sub(r"\D", "", head) + "." + tail_digits
        else:
            cleaned = re.sub(r"[^\d]", "", cleaned)
    else:
        cleaned = re.sub(r"[^\d]", "", cleaned)

    if not cleaned or cleaned == ".":
        return None, currency
    try:
        amount = float(cleaned)
    except ValueError:
        return None, currency
    return amount, currency


def parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Milliseconds vs seconds: anything past ~2286 in seconds is really ms.
        seconds = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = dateparser.parse(str(value), fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed and not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def clean_text(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def slugify(text: str) -> str:
    """URL slug in the shape Kleinanzeigen and friends expect: `nikon-d750`."""
    ascii_text = _strip_accents(text).lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-") or "x"


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(_strip_accents(text or "").lower())


def relevance(query: str, listing_title: str, description: str | None = None) -> float:
    """How well a listing matches the query, 0..1.

    Deliberately simple token coverage. Marketplaces run their own (often bad)
    matching, so this mostly exists to push obvious junk — accessories and
    lookalikes returned for a specific model number — down the page.
    """
    q_tokens = [t for t in tokenize(query) if len(t) > 1]
    if not q_tokens:
        return 0.0
    title_tokens = set(tokenize(listing_title))
    desc_tokens = set(tokenize(description or ""))
    hits = 0.0
    for token in q_tokens:
        if token in title_tokens:
            hits += 1.0
        elif any(token in t or t in token for t in title_tokens):
            hits += 0.6
        elif token in desc_tokens:
            hits += 0.3
    return min(hits / len(q_tokens), 1.0)


def is_negotiable(text: str | None) -> bool:
    if not text:
        return False
    low = _strip_accents(text.lower())
    return any(word in low for word in _NEGOTIABLE_WORDS)
