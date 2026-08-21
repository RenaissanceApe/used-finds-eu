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
import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup

from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError

_FIELDS = ("id", "title", "url", "price", "image", "location", "seller", "posted", "description", "condition")

_BLOCK_SIGNS = ("captcha", "are you a robot", "access denied", "datadome",
                "cf-browser-verification", "just a moment", "unusual traffic")
_DIGIT = re.compile(r"\d")


def _suggest_item_selectors(soup: BeautifulSoup, limit: int = 3) -> list[str]:
    """Guess what a result row looks like on a page whose selectors have rotted.

    Sites redesign and `engine_config.item` silently stops matching; the failure
    is indistinguishable from "no results" unless you go and read the HTML. So
    when nothing matches, look for the shape a listing actually has — an element
    that repeats, contains a link, and carries a number that could be a price —
    and hand back the candidates. Fixing the catalogue then means pasting one of
    these into the YAML instead of hunting through a page by hand.
    """
    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}

    for node in soup.find_all(True):
        classes = node.get("class") or []
        if not classes:
            continue
        if not node.find("a", href=True):
            continue
        text = node.get_text(" ", strip=True)
        # Too short to be a listing, or so long it is the whole page wrapper.
        if not (20 <= len(text) <= 600) or not _DIGIT.search(text):
            continue

        signature = f"{node.name}." + ".".join(sorted(classes)[:3])
        counts[signature] += 1
        samples.setdefault(signature, text[:60])

    return [
        f"{selector}  ({count}\u00d7, e.g. {samples[selector]!r})"
        for selector, count in counts.most_common(limit)
        if count >= 4
    ]


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

    @property
    def query_encoding(self) -> str:
        return "slug" if self.config.get("slugify_query") else "component"

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
            # Three very different situations look identical here — blocked,
            # genuinely no results, or our selector rotted — and each has a
            # different fix, so say which one it is.
            body = response.text.lower()
            if any(word in body for word in _BLOCK_SIGNS):
                raise EngineError("blocked by anti-bot page")

            suggestions = _suggest_item_selectors(soup)
            if suggestions:
                raise EngineError(
                    f"item selector {item_selector!r} matched nothing, but the page "
                    f"has repeated listing-shaped elements. Try: " + " | ".join(suggestions)
                )
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
