#!/usr/bin/env python3
"""Probe every marketplace in the catalogue and report what still works.

Scraped selectors rot — a site redesigns and an engine that returned 40 rows
yesterday silently returns 0 today. Run this monthly (or when a country goes
quiet) to find out which entries need attention *before* you rely on a search:

    python scripts/verify_catalog.py                # everything enabled by default
    python scripts/verify_catalog.py --all          # including off-by-default sites
    python scripts/verify_catalog.py -m bazos_cz    # one site

It issues exactly one search per marketplace. Do not run it in a loop.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ufeu.catalog import load_catalog          # noqa: E402
from ufeu.models import ResultStatus, SearchQuery  # noqa: E402
from ufeu.orchestrator import search           # noqa: E402

_ICON = {
    ResultStatus.OK: "✓",
    ResultStatus.EMPTY: "·",
    ResultStatus.MANUAL: "→",
    ResultStatus.NEEDS_AUTH: "🔑",
    ResultStatus.ERROR: "✗",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    print(f"\nProbe: {args.query!r} · {len(response.results)} marketplaces\n")
    broken: list[str] = []
    for result in sorted(response.results, key=lambda r: (r.status.value, r.country)):
        icon = _ICON.get(result.status, "?")
        detail = result.error or f"{len(result.listings)} listings"
        print(f" {icon} {result.country:<3} {result.marketplace_id:<22} {result.elapsed_ms:>5}ms  {detail}")
        if result.status is ResultStatus.ERROR:
            broken.append(result.marketplace_id)
        elif result.status is ResultStatus.EMPTY and catalog.by_id[result.marketplace_id].engine in ("html", "json_api"):
            # A generic query returning nothing usually means the selectors moved,
            # not that Europe has run out of iPhones.
            broken.append(result.marketplace_id + " (empty — check selectors)")

    print(f"\n{response.stats.markets_ok} healthy, {len(broken)} need attention")
    if broken:
        print("  " + "\n  ".join(broken))
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
