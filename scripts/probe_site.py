#!/usr/bin/env python3
"""Inspect one marketplace and report what its search response actually contains.

`verify_catalog.py` tells you *that* a source broke. This tells you *how* to fix
it, without anyone having to read a page of minified HTML: it fetches the search
URL exactly as the engine would, then reports whether the configured selector or
JSON root still resolves and, when it does not, what does.

    python scripts/probe_site.py maltapark_mt
    python scripts/probe_site.py dba_dk -q "iphone 13"
    python scripts/probe_site.py custojusto_pt --save /tmp/cj.html

Paste the output into the conversation and the catalogue entry can usually be
corrected from it directly.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from ufeu.adapters import build_engine  # noqa: E402
from ufeu.adapters.html import _BLOCK_SIGNS, _suggest_item_selectors  # noqa: E402
from ufeu.adapters.json_api import extract_embedded_json, suggest_roots  # noqa: E402
from ufeu.catalog import load_catalog  # noqa: E402
from ufeu.models import SearchQuery  # noqa: E402
from ufeu.settings import REQUEST_TIMEOUT, USER_AGENT  # noqa: E402
from ufeu.vault import get_credentials  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("marketplace", help="catalogue id, e.g. maltapark_mt")
    parser.add_argument("-q", "--query", default="iphone")
    parser.add_argument("--save", help="write the raw response body to this path")
    parser.add_argument(
        "--url",
        help="override the search URL (use %%QUERY%% for the term) to try a candidate path "
             "without editing the catalogue first",
    )
    args = parser.parse_args()

    catalog = load_catalog()
    market = catalog.by_id.get(args.marketplace)
    if market is None:
        print(f"Unknown marketplace {args.marketplace!r}", file=sys.stderr)
        return 1

    query = SearchQuery(q=args.query, limit=5)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        engine = build_engine(market, client, get_credentials(market.id))
        url = (
            args.url.replace("%QUERY%", quote(args.query))
            if args.url
            else engine.build_search_url(query)
        )

        print(f"\n{market.name}  ({market.id}, engine={market.engine})")
        print(f"GET {url}\n")
        try:
            response = await client.get(url, headers=engine.headers())
        except httpx.RequestError as exc:
            print(f"  network error: {type(exc).__name__}: {exc}")
            return 1

    body = response.text
    print(f"  HTTP {response.status_code} · {len(body)/1024:.1f} KB · "
          f"{response.headers.get('content-type', '?')} · "
          f"{response.elapsed.total_seconds()*1000:.0f}ms")
    if response.history:
        print(f"  redirected via {' → '.join(str(r.url) for r in response.history)}")

    if args.save:
        Path(args.save).write_text(body, encoding="utf-8")
        print(f"  body written to {args.save}")

    lowered = body[:200_000].lower()
    hits = [sign for sign in _BLOCK_SIGNS if sign in lowered]
    if hits or response.status_code in (403, 429):
        print(f"\n  ⛔ looks blocked ({', '.join(hits) or f'HTTP {response.status_code}'}).")
        if response.elapsed.total_seconds() < 0.3:
            print("     Refused in under 300ms — that is an edge block on IP reputation,")
            print("     not something a selector change will fix. Try a residential connection.")
        return 1

    # ── JSON responses ────────────────────────────────────────────────────
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            print("\n  content-type says JSON but the body will not parse.")
            return 1
        root = market.engine_config.get("root")
        print(f"\n  JSON response. configured root: {root!r}")
        for hint in suggest_roots(payload, limit=6):
            print(f"    candidate root: {hint}")
        first = _first_object(payload)
        if first:
            print(f"    keys on a sample item: {sorted(first)[:18]}")
        return 0

    # ── HTML responses ────────────────────────────────────────────────────
    describe_page_shape(body, args.query)

    soup = BeautifulSoup(body, "lxml")
    item_selector = market.engine_config.get("item")
    if item_selector:
        matched = soup.select(item_selector)
        print(f"\n  configured item selector {item_selector!r} → {len(matched)} matches")
        if matched:
            for field, spec in (market.engine_config.get("fields") or {}).items():
                value = matched[0].select_one(spec["sel"]) if spec.get("sel") else matched[0]
                got = (value.get_text(" ", strip=True)[:60] if value else None)
                print(f"    {field:<12} {'✓' if value else '✗'}  {got!r}")
        else:
            print("\n  repeated listing-shaped elements (link + price-like text):")
            hints = _suggest_item_selectors(soup, limit=6)
            for hint in hints or ["(none found)"]:
                print(f"    {hint}")
            if not hints:
                # Fall back to raw structure: on a JS-rendered shell there is
                # nothing listing-shaped, but seeing what *is* repeated tells us
                # whether we are looking at an app skeleton or the wrong page.
                print("\n  most repeated elements of any kind:")
                for line in repeated_elements(soup, limit=8) or ["(nothing repeats)"]:
                    print(f"    {line}")

    payload, strategy = extract_embedded_json(body)
    print(f"\n  embedded JSON: {strategy}")
    if payload is not None:
        for hint in suggest_roots(payload, limit=6):
            print(f"    candidate root: {hint}")
    return 0


_FRAMEWORKS = [
    ("Next.js", re.compile(r"__NEXT_DATA__|/_next/static", re.I)),
    ("Nuxt", re.compile(r"__NUXT__|/_nuxt/", re.I)),
    ("React", re.compile(r"react(?:-dom)?(?:\.production)?\.min\.js|data-reactroot", re.I)),
    ("Vue", re.compile(r"\bvue(?:\.runtime)?(?:\.min)?\.js|data-v-[0-9a-f]{8}", re.I)),
    ("Angular", re.compile(r"ng-version=|angular(?:\.min)?\.js", re.I)),
    ("Cloudflare challenge", re.compile(r"cdn-cgi/challenge-platform|__cf_chl", re.I)),
]


def describe_page_shape(body: str, term: str) -> None:
    """Answer the one question that decides whether a selector fix is possible.

    If the search term is nowhere in the HTML, the server did not render the
    results — no CSS selector will ever match them, and the site needs either
    its underlying XHR endpoint or a browser engine. Everything else is detail.
    """
    occurrences = body.lower().count(term.lower())
    print(f"\n  search term {term!r} appears in the HTML: "
          f"{'yes, ' + str(occurrences) + ' times' if occurrences else 'NO'}")
    if not occurrences:
        print("    → the server did not render the results. No selector can match them.")
        print("      Find the XHR that fetches them (devtools → Network → Fetch/XHR) and")
        print("      point a json_api engine at it, or move this site to a browser engine.")

    detected = [name for name, pattern in _FRAMEWORKS if pattern.search(body)]
    if detected:
        print(f"  framework hints: {', '.join(detected)}")

    scripts = len(re.findall(r"<script\b", body, re.I))
    links = len(re.findall(r"<a\s[^>]*href=", body, re.I))
    print(f"  page has {links} links and {scripts} script tags")


def repeated_elements(soup, limit: int = 8) -> list[str]:
    """Most common tag+class signatures, unfiltered — the page's raw skeleton."""
    counts: Counter[str] = Counter()
    for node in soup.find_all(True):
        classes = node.get("class") or []
        if not classes:
            continue
        counts[f"{node.name}." + ".".join(sorted(classes)[:3])] += 1
    return [f"{sig}  ({n}\u00d7)" for sig, n in counts.most_common(limit) if n >= 3]


def _first_object(node, depth: int = 0):
    """Find a representative item dict so its field names can be reported."""
    if depth > 8:
        return None
    if isinstance(node, list):
        return node[0] if node and isinstance(node[0], dict) else None
    if isinstance(node, dict):
        for value in node.values():
            found = _first_object(value, depth + 1)
            if found:
                return found
    return None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
