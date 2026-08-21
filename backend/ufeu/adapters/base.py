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

from .. import http as ufeu_http
from ..catalog import Marketplace
from ..models import Listing, MarketResult, ResultStatus, SearchQuery
from ..normalize import clean_text, parse_datetime, parse_price, relevance, slugify
from ..settings import REQUEST_TIMEOUT

log = logging.getLogger(__name__)


class EngineError(RuntimeError):
    """Raised for anything the engine can explain to the user in one line."""


class NeedsAuth(EngineError):
    """The marketplace needs credentials the vault does not have."""


class BaseEngine(abc.ABC):
    name: str = "base"

    #: How the search term is encoded into ``search_url``. Read by
    #: scripts/build_static_site.py so the static build can produce identical
    #: links in the browser instead of duplicating this logic in JS.
    #: "component" = percent-encoded · "slug" = nikon-d750 · "dash" = nikon-d750 unencoded
    query_encoding: str = "component"

    def __init__(self, market: Marketplace, client: httpx.AsyncClient, credentials: dict[str, Any] | None = None):
        self.market = market
        self.client = client
        self.credentials = credentials or {}
        self.config = market.engine_config
        self._browser: ufeu_http.BrowserTransport | None = None
        self._impersonation_warned = False

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

    # ------------------------------------------------------------- transport

    @property
    def impersonate(self) -> str | None:
        """Which browser fingerprint this marketplace needs, if any.

        Set `impersonate: chrome124` (or `true`) in engine_config for sites that
        reject Python's TLS handshake. Off by default — plain httpx is faster
        and perfectly welcome almost everywhere.
        """
        value = self.config.get("impersonate")
        if not value:
            return None
        return ufeu_http.DEFAULT_PROFILE if value is True else str(value)

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make a request, through a browser fingerprint where one is required.

        Falls back to httpx — loudly, once — when the marketplace asks for
        impersonation but curl_cffi is not installed, so a missing optional
        dependency degrades to "probably blocked" rather than "cannot start".
        """
        profile = self.impersonate
        if profile and ufeu_http.available():
            if self._browser is None:
                self._browser = ufeu_http.BrowserTransport(profile)
            return await self._browser.request(
                method, url, params=params, headers=headers,
                content=content, data=data, timeout=REQUEST_TIMEOUT,
            )

        if profile and not self._impersonation_warned:
            self._impersonation_warned = True
            log.warning(
                "%s needs a browser TLS fingerprint but curl_cffi is unavailable (%s); "
                "falling back to httpx, which this site will probably refuse. "
                "Install it with: pip install curl_cffi",
                self.market.id,
                ufeu_http.unavailable_reason(),
            )

        return await self.client.request(
            method, url, params=params, headers=headers,
            content=content, data=data, follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None

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
        finally:
            await self.aclose()
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    @abc.abstractmethod
    async def search(self, query: SearchQuery) -> list[Listing]:
        """Return listings, or raise. Never swallow errors here — `run` does that."""
