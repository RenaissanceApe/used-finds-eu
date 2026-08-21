"""Vinted.

The most valuable single integration in the project, because Vinted runs one
shared catalogue across connected country pools: a query against vinted.pt
returns sellers from most of Europe, and every one of them can ship to Portugal
under Buyer Protection. If you only ever wire up two engines, make them this
one and eBay.

Search works without an account. It does need a session cookie, which the API
hands to anonymous visitors on the first page load — so we bootstrap one per
process and reuse it.
"""

from __future__ import annotations

import asyncio

from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError

_bootstrap_lock = asyncio.Lock()


class VintedEngine(BaseEngine):
    name = "vinted"

    @property
    def base_url(self) -> str:
        return (self.config.get("base_url") or self.market.site).rstrip("/")

    def build_search_url(self, query: SearchQuery) -> str:
        from urllib.parse import quote

        return f"{self.base_url}/catalog?search_text={quote(query.q)}"

    async def _ensure_session(self) -> None:
        """Fetch an anonymous session cookie if the client does not have one."""
        if any(c.name.startswith("access_token_web") or c.name.endswith("_session")
               for c in self.client.cookies.jar):
            return
        async with _bootstrap_lock:
            if any(c.name.startswith("access_token_web") for c in self.client.cookies.jar):
                return
            response = await self.client.get(
                self.base_url + "/",
                headers={**self.headers(), "Accept": "text/html,application/xhtml+xml"},
                follow_redirects=True,
            )
            response.raise_for_status()

    async def search(self, query: SearchQuery) -> list[Listing]:
        await self._ensure_session()

        params = {
            "search_text": query.q,
            "per_page": str(self.config.get("per_page", 48)),
            "page": "1",
            "order": self.config.get("order", "newest_first"),
        }
        if query.min_price_eur:
            params["price_from"] = str(int(query.min_price_eur))
        if query.max_price_eur:
            params["price_to"] = str(int(query.max_price_eur))

        response = await self.client.get(
            f"{self.base_url}/api/v2/catalog/items",
            params=params,
            headers={**self.headers(), "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            follow_redirects=True,
        )
        if response.status_code == 401:
            # The anonymous token expired mid-flight; drop it and retry once.
            self.client.cookies.clear()
            await self._ensure_session()
            response = await self.client.get(
                f"{self.base_url}/api/v2/catalog/items",
                params=params,
                headers={**self.headers(), "Accept": "application/json"},
                follow_redirects=True,
            )
        response.raise_for_status()

        try:
            items = response.json().get("items", [])
        except ValueError as exc:
            raise EngineError("Vinted returned non-JSON — session bootstrap likely failed") from exc

        listings: list[Listing] = []
        for item in items[: query.limit]:
            price = item.get("price")
            currency = None
            if isinstance(price, dict):
                currency = price.get("currency_code")
                price = price.get("amount")
            photo = item.get("photo") or {}
            user = item.get("user") or {}

            descriptor = " · ".join(
                part for part in (item.get("brand_title"), item.get("size_title")) if part
            )
            listing = self.make_listing(
                id=str(item.get("id")),
                title=item.get("title") or "",
                url=item.get("url") or f"{self.base_url}/items/{item.get('id')}",
                price=price,
                currency=currency,
                query=query,
                image=photo.get("url") or (photo.get("thumbnails") or [{}])[0].get("url"),
                seller=user.get("login"),
                description=descriptor or None,
                condition=item.get("status"),
                ships=True,
                raw={"brand": item.get("brand_title"), "size": item.get("size_title")},
            )
            if listing:
                listings.append(listing)
        return listings
