"""A small on-disk response cache.

Searching 30 marketplaces takes real seconds and real goodwill from the sites
involved. Re-running the same query while you tweak filters in the UI should
not re-hit any of them, so results are cached by (marketplace, query) for a
short TTL. `fresh=true` on the request bypasses it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from typing import Any

from .settings import CACHE_TTL_SECONDS, state_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(state_dir() / "cache.sqlite3", timeout=5)
    conn.execute(_SCHEMA)
    return conn


def make_key(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(key: str, ttl: int = CACHE_TTL_SECONDS) -> Any | None:
    with closing(_db()) as conn:
        row = conn.execute("SELECT value, created_at FROM cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    value, created_at = row
    if time.time() - created_at > ttl:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def put(key: str, value: Any) -> None:
    with closing(_db()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), time.time()),
        )
        conn.commit()


def purge(older_than: int = 86_400) -> int:
    cutoff = time.time() - older_than
    with closing(_db()) as conn:
        cursor = conn.execute("DELETE FROM cache WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount
