"""Config-driven CSS-selector engine for server-rendered classifieds sites.

This covers the long tail — Bazoš, SS.lv, Njuškalo, Bolha, Bazaraki, MaltaPark,
Jófogás, Adverts.ie, Okidoki, Kleinanzeigen and friends. Many of these are
plain 2010-era HTML with no JavaScript, which makes them the most *dependable*
sources in the catalogue even though scraping sounds like the fragile option.

Two rules keep this civil, and they are not optional:
  * one request per search, never a crawl;
  * `rate_limit_rps` in the config throttles the noisier sites.
Check each site's robots.txt and terms before you enable it in anger.
"""

from __future__ import annotations

import asyncio
from typing import Any

from bs4 import BeautifulSoup

from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError

_FIELDS = ("id", "title", "url", "price", "image", "location", "seller", "posted", "description", "condition")


def _extract(node, spec: dict[str, Any] | None) -> str | None:
    """Pull one field out of a listing node per its `{sel, attr}` spec."""
    if not spec:
        return None
    target = node
    selector = spec.get("sel")
    if selector:
        target = node.select_one(selector)
        if target is None:
            return None

    attr = spec.get("attr", "text")
    if attr == "text":
        return target.get_text(" ", strip=True)
    value = target.get(attr)
    if value is None and attr == "src":
        # Lazy-loaded images are the norm on these sites.
        for fallback in ("data-src", "data-imgsrc", "data-lazy", "srcset"):
            value = target.get(fallback)
            if value:
                break
        if value and " " in str(value):  # srcset — take the first candidate
            value = str(value).split(",")[0].strip().split(" ")[0]
    if isinstance(value, list):
        value = " ".join(value)
    return value


class HtmlEngine(BaseEngine):
    name = "html"

    async def search(self, query: SearchQuery) -> list[Listing]:
        rps = float(self.config.get("rate_limit_rps") or 0)
        if rps:
            await asyncio.sleep(1.0 / rps)

        url = self.build_search_url(query)
        response = await self.client.get(url, headers=self.headers(), follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        item_selector = self.config.get("item")
        if not item_selector:
            raise EngineError("engine_config.item selector missing")
        nodes = soup.select(item_selector)
        if not nodes:
            # Distinguish "no results" from "our selectors rotted", because the
            # fix is completely different and silence here wastes hours.
            body = response.text.lower()
            if any(word in body for word in ("captcha", "are you a robot", "access denied", "datadome")):
                raise EngineError("blocked by anti-bot page")
            return []

        field_specs: dict[str, dict[str, Any]] = self.config.get("fields", {})
        listings: list[Listing] = []
        for index, node in enumerate(nodes[: query.limit]):
            values = {key: _extract(node, field_specs.get(key)) for key in _FIELDS}
            listing = self.make_listing(
                id=str(values.get("id") or index),
                title=values.get("title") or "",
                url=values.get("url") or "",
                price=values.get("price"),
                currency=self.config.get("currency"),
                query=query,
                image=values.get("image"),
                location=values.get("location"),
                seller=values.get("seller"),
                posted=values.get("posted"),
                description=values.get("description"),
                condition=values.get("condition"),
            )
            if listing:
                listings.append(listing)
        return listings
