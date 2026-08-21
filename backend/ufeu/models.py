"""Shared data shapes.

Every engine, however messy its source, must hand back ``Listing`` objects.
That is the whole point of the normalisation layer: the UI never has to know
whether a row came from an official REST API or a scraped table cell.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResultStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    SKIPPED = "skipped"
    # The marketplace cannot be queried programmatically (bot protection or
    # ToS); we hand back a deep link for the human to click instead.
    MANUAL = "manual"
    # Needs credentials the vault does not have yet.
    NEEDS_AUTH = "needs_auth"


class Listing(BaseModel):
    id: str
    marketplace_id: str
    marketplace_name: str
    country: str
    title: str
    url: str
    price: float | None = None
    currency: str = "EUR"
    price_eur: float | None = None
    image: str | None = None
    location: str | None = None
    seller: str | None = None
    description: str | None = None
    condition: str | None = None
    posted: datetime | None = None
    ships: bool | None = None
    dedupe_group: str | None = None
    score: float = 0.0
    # Filled in by the shipping resolver so the UI can rank on what the item
    # actually costs delivered to Portugal, not on the sticker price.
    shipping_cost_eur: float | None = None
    shipping_strategy: str | None = None
    landed_cost_eur: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class MarketResult(BaseModel):
    marketplace_id: str
    marketplace_name: str
    country: str
    status: ResultStatus
    listings: list[Listing] = Field(default_factory=list)
    search_url: str | None = None
    error: str | None = None
    elapsed_ms: int = 0
    cached: bool = False


class SearchQuery(BaseModel):
    q: str
    countries: list[str] | None = None
    marketplaces: list[str] | None = None
    min_price_eur: float | None = None
    max_price_eur: float | None = None
    limit: int = 24
    sort: Literal["relevance", "price_asc", "price_desc", "newest", "landed_asc"] = "relevance"
    include_disabled: bool = False
    fresh: bool = False


class SearchStats(BaseModel):
    markets_queried: int = 0
    markets_ok: int = 0
    markets_failed: int = 0
    markets_manual: int = 0
    listings_total: int = 0
    duplicates_removed: int = 0
    elapsed_ms: int = 0


class SearchResponse(BaseModel):
    query: SearchQuery
    stats: SearchStats
    listings: list[Listing]
    results: list[MarketResult]
