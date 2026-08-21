"""The engine contract.

An "engine" is the code that knows how to ask one *kind* of marketplace for
results. Marketplaces themselves are data (marketplaces.yaml), not code — which
is why 64 sites need only six engines, and why adding the 65th is a YAML edit.
"""

from __future__ import annotations

import abc
import logging
import time
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from ..catalog import Marketplace
from ..models import Listing, MarketResult, ResultStatus, SearchQuery
from ..normalize import clean_text, parse_datetime, parse_price, relevance, slugify

log = logging.getLogger(__name__)


class EngineError(RuntimeError):
    """Raised for anything the engine can explain to the user in one line."""


class NeedsAuth(EngineError):
    """The marketplace needs credentials the vault does not have."""


class BaseEngine(abc.ABC):
    name: str = "base"

    def __init__(self, market: Marketplace, client: httpx.AsyncClient, credentials: dict[str, Any] | None = None):
        self.market = market
        self.client = client
        self.credentials = credentials or {}
        self.config = market.engine_config

    # ---------------------------------------------------------------- helpers

    def build_search_url(self, query: SearchQuery) -> str:
        """Human-clickable URL for this query. Also the fallback for `manual`."""
        template = self.config.get("search_url")
        if not template:
            return self.market.site
        term = slugify(query.q) if self.config.get("slugify_query") else quote(query.q)
        return (
            template.replace("{q}", term)
            .replace("{limit}", str(query.limit))
        )

    def make_listing(
        self,
        *,
        id: str,
        title: str,
        url: str,
        price: Any = None,
        currency: str | None = None,
        query: SearchQuery,
        **extra: Any,
    ) -> Listing | None:
        title = clean_text(title) or ""
        url = clean_text(url) or ""
        if not title or not url:
            return None
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith("http"):
            url = urljoin(self.market.site + "/", url.lstrip("/"))

        default_currency = currency or self.market.currency
        amount, resolved_currency = parse_price(price, default_currency)
        description = clean_text(extra.get("description"))

        return Listing(
            id=f"{self.market.id}:{id}",
            marketplace_id=self.market.id,
            marketplace_name=self.market.name,
            country=self.market.country,
            title=title,
            url=url,
            price=amount,
            currency=resolved_currency,
            image=clean_text(extra.get("image")),
            location=clean_text(extra.get("location")),
            seller=clean_text(extra.get("seller")),
            description=description,
            condition=clean_text(extra.get("condition")),
            posted=parse_datetime(extra.get("posted")),
            ships=extra.get("ships"),
            dedupe_group=self.market.dedupe_group,
            score=relevance(query.q, title, description),
            raw=extra.get("raw") or {},
        )

    def headers(self) -> dict[str, str]:
        base = {
            "Accept-Language": "en,pt;q=0.9,es;q=0.8,de;q=0.7,fr;q=0.6",
        }
        base.update(self.config.get("headers") or {})
        cookie = self.credentials.get("cookie")
        if cookie:
            base["Cookie"] = cookie
        bearer = self.credentials.get("bearer")
        if bearer:
            base["Authorization"] = f"Bearer {bearer}"
        return base

    # ----------------------------------------------------------------- driver

    async def run(self, query: SearchQuery) -> MarketResult:
        """Execute a search, converting every failure mode into a result row.

        One dead marketplace must never take down a 30-site fan-out, so nothing
        escapes from here.
        """
        started = time.perf_counter()
        result = MarketResult(
            marketplace_id=self.market.id,
            marketplace_name=self.market.name,
            country=self.market.country,
            status=ResultStatus.OK,
            search_url=self.build_search_url(query),
        )
        try:
            listings = await self.search(query)
            result.listings = listings[: query.limit]
            result.status = ResultStatus.OK if listings else ResultStatus.EMPTY
        except NeedsAuth as exc:
            result.status = ResultStatus.NEEDS_AUTH
            result.error = str(exc)
        except httpx.HTTPStatusError as exc:
            result.status = ResultStatus.ERROR
            code = exc.response.status_code
            hint = {
                401: "credentials rejected", 403: "blocked (bot protection or geo-fence)",
                404: "search endpoint moved", 429: "rate limited — slow down",
            }.get(code, "")
            result.error = f"HTTP {code}{f' — {hint}' if hint else ''}"
        except httpx.RequestError as exc:
            result.status = ResultStatus.ERROR
            result.error = f"network error: {type(exc).__name__}"
        except EngineError as exc:
            result.status = ResultStatus.ERROR
            result.error = str(exc)
        except Exception as exc:  # a parser bug must not kill the search
            log.exception("engine %s failed for %s", self.name, self.market.id)
            result.status = ResultStatus.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    @abc.abstractmethod
    async def search(self, query: SearchQuery) -> list[Listing]:
        """Return listings, or raise. Never swallow errors here — `run` does that."""
