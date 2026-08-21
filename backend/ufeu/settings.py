"""Runtime configuration and filesystem layout."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
REPO_ROOT = PACKAGE_DIR.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"


def state_dir() -> Path:
    """Where the vault, cache and FX snapshots live.

    Defaults to ``~/.local/state/ufeu`` so credentials never land inside the
    repo by accident. Override with ``UFEU_STATE_DIR`` (tests do).
    """
    raw = os.environ.get("UFEU_STATE_DIR")
    base = Path(raw).expanduser() if raw else Path.home() / ".local" / "state" / "ufeu"
    base.mkdir(parents=True, exist_ok=True)
    return base


# Network behaviour. Deliberately conservative: we are a guest on every one of
# these sites, and a polite client is a client that keeps working.
USER_AGENT = os.environ.get(
    "UFEU_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
)
REQUEST_TIMEOUT = float(os.environ.get("UFEU_TIMEOUT", "20"))
MAX_CONCURRENCY = int(os.environ.get("UFEU_CONCURRENCY", "8"))
DEFAULT_LIMIT = int(os.environ.get("UFEU_LIMIT", "24"))
CACHE_TTL_SECONDS = int(os.environ.get("UFEU_CACHE_TTL", "600"))

# Browser origins allowed to call the API. The local UI is same-origin, but the
# static GitHub Pages build is not — it talks to whatever backend you point it
# at, so its origin has to be allowed explicitly.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "UFEU_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,https://renaissanceape.github.io",
    ).split(",")
    if origin.strip()
]

# Home base. Everything in shipping.py is measured relative to this.
HOME_COUNTRY = os.environ.get("UFEU_HOME_COUNTRY", "PT")
HOME_CURRENCY = os.environ.get("UFEU_HOME_CURRENCY", "EUR")
