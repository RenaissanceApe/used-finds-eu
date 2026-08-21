#!/usr/bin/env python3
"""Probe every marketplace in the catalogue and report what still works.

Run this from the machine that will actually do the searching. That matters
more than it sounds: the first live run of this script was done from a GitHub
Codespace, and twelve marketplaces returned HTTP 403 in under 110ms — an edge
block on datacenter IP reputation, before anything looked at the request. The
same catalogue from a residential connection behaves very differently. So the
output is grouped by *cause*, because "blocked" and "broken" need opposite
responses: one is a networking decision, the other is a code fix.

    python scripts/verify_catalog.py                # everything enabled by default
    python scripts/verify_catalog.py --all          # including off-by-default sites
    python scripts/verify_catalog.py -m bazos_cz    # one site

It issues exactly one search per marketplace. Do not run it in a loop.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ufeu import http as ufeu_http                    # noqa: E402
from ufeu.catalog import load_catalog                 # noqa: E402
from ufeu.models import MarketResult, ResultStatus, SearchQuery  # noqa: E402
from ufeu.orchestrator import search                  # noqa: E402

# An error message tells us which of these it was; the fix differs completely.
BLOCKED = re.compile(r"\b(403|429)\b|blocked|anti-bot|bot protection|geo-fence", re.I)
BROKEN = re.compile(
    r"\b404\b|resolved to nothing|matched nothing|no embedded JSON|App Router"
    r"|non-JSON|expected a list|selector missing|changed its rendering",
    re.I,
)


def classify(result: MarketResult, engine: str) -> str:
    if result.status is ResultStatus.OK:
        return "ok"
    if result.status is ResultStatus.MANUAL:
        return "manual"
    if result.status is ResultStatus.NEEDS_AUTH:
        return "auth"
    if result.status is ResultStatus.ERROR:
        if BLOCKED.search(result.error or ""):
            return "blocked"
        if BROKEN.search(result.error or ""):
            return "broken"
        return "unknown"
    # A generic term returning nothing from a scraped source is almost always
    # rot, not an empty market.
    if result.status is ResultStatus.EMPTY and engine in ("html", "json_api"):
        return "broken"
    return "empty"


GROUPS = [
    ("ok", "✓", "Working"),
    ("broken", "✗", "Broken — needs a code or config fix"),
    ("blocked", "⛔", "Blocked by the site — an IP/network problem, not a code one"),
    ("auth", "🔑", "Needs credentials"),
    ("manual", "→", "Manual by design (no automated search offered)"),
    ("empty", "·", "Returned nothing (may be a genuinely empty market)"),
    ("unknown", "?", "Unclassified failure"),
]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-q", "--query", default="iphone", help="probe term (default: iphone)")
    parser.add_argument("-m", "--marketplace", action="append", help="check only these ids")
    parser.add_argument("--all", action="store_true", help="include off-by-default marketplaces")
    args = parser.parse_args()

    catalog = load_catalog()
    response = await search(
        SearchQuery(
            q=args.query,
            marketplaces=args.marketplace,
            include_disabled=args.all,
            limit=5,
            fresh=True,
        )
    )

    buckets: dict[str, list[MarketResult]] = {key: [] for key, _, _ in GROUPS}
    for result in response.results:
        engine = catalog.by_id[result.marketplace_id].engine
        buckets[classify(result, engine)].append(result)

    print(f"\nProbe: {args.query!r} · {len(response.results)} marketplaces\n")
    for key, icon, heading in GROUPS:
        rows = buckets[key]
        if not rows:
            continue
        print(f"{heading} ({len(rows)})")
        for result in sorted(rows, key=lambda r: r.country):
            detail = result.error or f"{len(result.listings)} listings"
            print(f"  {icon} {result.country:<3} {result.marketplace_id:<22} {result.elapsed_ms:>5}ms")
            # Never truncate: for a broken source this line *is* the fix — the
            # JMESPath root or the CSS selector to paste into the catalogue.
            for line in textwrap.wrap(detail, width=96) or [""]:
                print(f"        {line}")
        print()

    working, broken, blocked = len(buckets["ok"]), len(buckets["broken"]), len(buckets["blocked"])
    print(f"{working} working · {broken} broken · {blocked} blocked · "
          f"{len(buckets['auth'])} need credentials\n")

    if blocked:
        wants_browser = [
            r for r in buckets["blocked"]
            if catalog.by_id[r.marketplace_id].engine_config.get("impersonate")
        ]
        if wants_browser and not ufeu_http.available():
            print(f"{len(wants_browser)} of these are configured to need a browser TLS fingerprint,")
            print(f"which is unavailable here ({ufeu_http.unavailable_reason()}). These sites reject")
            print("Python's TLS handshake regardless of your IP. Install it and re-run:\n")
            print("    pip install -r backend/requirements-browser.txt\n")
        elif wants_browser:
            print("These still refuse us *with* a browser fingerprint, so the block is not the")
            print("handshake. Next suspects, in order: the IP itself (try a different network),")
            print("a geo restriction, or a JS challenge that needs a real browser engine.\n")
        else:
            print("These are not configured for impersonation. If the refusal was fast, try")
            print("adding `impersonate: chrome124` to their engine_config and re-running.\n")
    if broken:
        print("Broken sources report what they found instead of what they expected — paste")
        print("those lines back and the catalogue entry can usually be fixed from them.\n")

    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
