"""OLX group (PL, PT, RO, BG).

One engine, four countries — OLX runs the same platform and the same
``/api/v1/offers`` search endpoint on every national domain. Poland is the
standout: OLX Przesyłki ships via InPost, whose lockers now reach Portugal.
"""

from __future__ import annotations

from typing import Any

from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError


def _param(offer: dict[str, Any], key: str) -> dict[str, Any] | None:
    for param in offer.get("params") or []:
        if param.get("key") == key:
            return param
    return None


class OlxEngine(BaseEngine):
    name = "olx"
    query_encoding = "dash"

    @property
    def base_url(self) -> str:
        return (self.config.get("base_url") or self.market.site).rstrip("/")

    def build_search_url(self, query: SearchQuery) -> str:
        from urllib.parse import quote

        # Each national domain uses its own word for "listings" in the path.
        path = self.config.get("search_path", "/ads/")
        return f"{self.base_url}{path}q-{quote(query.q.replace(' ', '-'))}/"

    async def search(self, query: SearchQuery) -> list[Listing]:
        params: dict[str, str] = {
            "offset": "0",
            "limit": str(min(query.limit, 50)),
            "query": query.q,
            "sort_by": "created_at:desc",
        }
        if query.min_price_eur:
            params["filter_float_price:from"] = str(int(query.min_price_eur))
        if query.max_price_eur:
            params["filter_float_price:to"] = str(int(query.max_price_eur))

        response = await self.client.get(
            f"{self.base_url}/api/v1/offers/",
            params=params,
            headers={**self.headers(), "Accept": "application/json"},
            follow_redirects=True,
        )
        response.raise_for_status()
        try:
            offers = response.json().get("data", [])
        except ValueError as exc:
            raise EngineError("OLX returned non-JSON (anti-bot interstitial?)") from exc

        listings: list[Listing] = []
        for offer in offers[: query.limit]:
            price_param = _param(offer, "price") or {}
            price_value = (price_param.get("value") or {})
            amount = price_value.get("value")
            currency = price_value.get("currency") or self.market.currency
            if amount is None:
                # Some categories only carry the rendered label ("120 zł", "Grátis").
                amount = price_value.get("label") or (price_param.get("value") or {}).get("label")

            photos = offer.get("photos") or []
            image = None
            if photos:
                # OLX photo links are templates: `...;s={width}x{height}`.
                image = str(photos[0].get("link", "")).replace("{width}", "640").replace("{height}", "480")

            location = offer.get("location") or {}
            city = (location.get("city") or {}).get("name")
            region = (location.get("region") or {}).get("name")

            delivery = offer.get("delivery") or {}
            listing = self.make_listing(
                id=str(offer.get("id")),
                title=offer.get("title") or "",
                url=offer.get("url") or "",
                price=amount,
                currency=currency,
                query=query,
                image=image,
                location=", ".join(part for part in (city, region) if part) or None,
                seller=(offer.get("user") or {}).get("name"),
                description=offer.get("description"),
                condition=((_param(offer, "state") or {}).get("value") or {}).get("label"),
                posted=offer.get("created_time"),
                ships=bool(delivery.get("rock", {}).get("active")) if delivery else None,
            )
            if listing:
                listings.append(listing)
        return listings
