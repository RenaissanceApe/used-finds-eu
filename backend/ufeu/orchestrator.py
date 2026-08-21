"""Fan-out search across the catalogue, then merge into one ranked list.

Deliverables (d) and (e). The hard parts are not the requests — they are:
  * one slow or dead site must not hold up the other 30 (per-market timeout);
  * prices in six currencies must be comparable (EUR normalisation);
  * Vinted's shared pool returns the same item on every domain (dedupe);
  * failures must stay visible instead of silently shrinking the result set.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from . import cache, fx, shipping
from .adapters import build_engine, demo_mode
from .catalog import Marketplace, load_catalog
from .models import (
    Listing,
    MarketResult,
    ResultStatus,
    SearchQuery,
    SearchResponse,
    SearchStats,
)
from .normalize import tokenize
from .settings import MAX_CONCURRENCY, REQUEST_TIMEOUT, USER_AGENT
from .vault import get_credentials

log = logging.getLogger(__name__)

_TRACKING_PARAMS = re.compile(r"(utm_[a-z]+|reason|ref|referrer|sid)=", re.IGNORECASE)


def _canonical_url(url: str) -> str:
    """Strip tracking noise so the same item from two domains compares equal."""
    base = url.split("#", 1)[0]
    if "?" in base:
        path, _, qs = base.partition("?")
        kept = [p for p in qs.split("&") if p and not _TRACKING_PARAMS.match(p)]
        base = path + ("?" + "&".join(kept) if kept else "")
    return base.rstrip("/").lower()


def _dedupe(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Collapse repeats, keeping the first (highest-ranked) occurrence.

    Two passes: exact URL, then — inside a dedupe group such as Vinted's shared
    pool — title plus price, which catches the same item served under different
    national domains and item ids.
    """
    seen_urls: set[str] = set()
    seen_soft: set[tuple[str, str, int]] = set()
    kept: list[Listing] = []
    dropped = 0

    for listing in listings:
        url_key = _canonical_url(listing.url)
        if url_key in seen_urls:
            dropped += 1
            continue

        soft_key = None
        if listing.dedupe_group and listing.price_eur is not None:
            title_key = " ".join(sorted(set(tokenize(listing.title))))[:120]
            soft_key = (listing.dedupe_group, title_key, int(round(listing.price_eur)))
            if soft_key in seen_soft:
                dropped += 1
                continue

        seen_urls.add(url_key)
        if soft_key:
            seen_soft.add(soft_key)
        kept.append(listing)
    return kept, dropped


def _annotate_shipping(listings: list[Listing]) -> None:
    """Attach the cheapest realistic route to Portugal to every row.

    This is what makes the unified list honest: a €90 lens in Estonia and a €110
    lens in Spain are not what they look like until shipping is in the number.
    """
    for listing in listings:
        plan = shipping.plan(
            listing.country,
            title=" ".join(p for p in (listing.title, listing.description) if p),
            item_price_eur=listing.price_eur,
            native_shipping=bool(listing.ships),
        )
        best = next((o for o in plan.options if o.recommended), plan.best)
        if best is None:
            continue
        listing.shipping_cost_eur = best.cost_eur
        listing.shipping_strategy = best.id
        if listing.price_eur is not None:
            listing.landed_cost_eur = round(listing.price_eur + best.cost_eur, 2)


def _sort_key(listing: Listing, mode: str):
    if mode == "price_asc":
        return (listing.price_eur is None, listing.price_eur or 0.0, -listing.score)
    if mode == "price_desc":
        return (listing.price_eur is None, -(listing.price_eur or 0.0), -listing.score)
    if mode == "landed_asc":
        return (listing.landed_cost_eur is None, listing.landed_cost_eur or 0.0, -listing.score)
    if mode == "newest":
        return (listing.posted is None, -(listing.posted.timestamp() if listing.posted else 0))
    # Relevance, with cheaper items breaking ties — this is a bargain hunter.
    return (-round(listing.score, 3), listing.price_eur if listing.price_eur is not None else 1e12)


async def _run_market(
    market: Marketplace,
    client: httpx.AsyncClient,
    query: SearchQuery,
    semaphore: asyncio.Semaphore,
) -> MarketResult:
    cache_key = cache.make_key(
        "search", market.id, query.q, query.limit, query.min_price_eur, query.max_price_eur
    )
    if not query.fresh and not demo_mode():
        cached = cache.get(cache_key)
        if cached is not None:
            result = MarketResult.model_validate(cached)
            result.cached = True
            return result

    async with semaphore:
        engine = build_engine(market, client, get_credentials(market.id))
        try:
            result = await asyncio.wait_for(engine.run(query), timeout=REQUEST_TIMEOUT + 5)
        except asyncio.TimeoutError:
            return MarketResult(
                marketplace_id=market.id,
                marketplace_name=market.name,
                country=market.country,
                status=ResultStatus.ERROR,
                error=f"timed out after {REQUEST_TIMEOUT + 5:.0f}s",
                search_url=market.site,
            )

    if result.status in (ResultStatus.OK, ResultStatus.EMPTY) and not demo_mode():
        cache.put(cache_key, result.model_dump(mode="json"))
    return result


async def search(query: SearchQuery) -> SearchResponse:
    started = time.perf_counter()
    catalog = load_catalog()
    markets = catalog.select(
        countries=query.countries,
        marketplace_ids=query.marketplaces,
        include_disabled=query.include_disabled,
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    limits = httpx.Limits(max_connections=MAX_CONCURRENCY * 2, max_keepalive_connections=MAX_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        limits=limits,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(_run_market(market, client, query, semaphore) for market in markets)
        )

    rates = fx.load()
    listings: list[Listing] = []
    for result in results:
        for listing in result.listings:
            listing.price_eur = rates.to_eur(listing.price, listing.currency)
            listings.append(listing)

    if query.min_price_eur is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur >= query.min_price_eur]
    if query.max_price_eur is not None:
        listings = [l for l in listings if l.price_eur is None or l.price_eur <= query.max_price_eur]

    _annotate_shipping(listings)
    listings.sort(key=lambda l: _sort_key(l, query.sort))
    listings, duplicates = _dedupe(listings)

    stats = SearchStats(
        markets_queried=len(results),
        markets_ok=sum(1 for r in results if r.status == ResultStatus.OK),
        markets_failed=sum(
            1 for r in results if r.status in (ResultStatus.ERROR, ResultStatus.NEEDS_AUTH)
        ),
        markets_manual=sum(1 for r in results if r.status == ResultStatus.MANUAL),
        listings_total=len(listings),
        duplicates_removed=duplicates,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    # Sites that produced something first, then the ones needing attention.
    results.sort(key=lambda r: (-len(r.listings), r.status.value, r.marketplace_name))
    return SearchResponse(query=query, stats=stats, listings=listings, results=results)
