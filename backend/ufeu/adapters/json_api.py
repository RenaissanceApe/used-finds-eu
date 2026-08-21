"""Config-driven engine for marketplaces that speak JSON.

Two shapes are covered:

  ``mode: rest``       a real JSON endpoint (Marktplaats, Subito, Wallapop,
                       Blocket, 2dehands, DoneDeal, Sbazar, Tradera).
  ``mode: next_data``  a server-rendered Next.js page whose ``__NEXT_DATA__``
                       blob contains the search results (willhaben, Tori, DBA).
                       Same extraction pipeline, different transport.

Field mapping is JMESPath, so a new site is usually 10 lines of YAML.
"""

from __future__ import annotations

import json
import re
from typing import Any

import jmespath

from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError, NeedsAuth

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
_STATE_ASSIGN_RE = re.compile(
    r'(?:window\.__NUXT__|window\.__INITIAL_STATE__|window\.__APOLLO_STATE__)\s*=\s*(\{.*?\})\s*;?\s*</script>',
    re.DOTALL,
)
# Next.js App Router streams its payload as JS pushes rather than one JSON blob.
_FLIGHT_RE = re.compile(r"self\.__next_f\.push\(")


def _largest_json(candidates: list[str]) -> Any | None:
    """Parse every candidate blob, return the biggest one that is a dict."""
    best = None
    best_size = 0
    for blob in candidates:
        blob = blob.strip()
        if len(blob) <= best_size:
            continue
        try:
            parsed = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, (dict, list)):
            best, best_size = parsed, len(blob)
    return best


def extract_embedded_json(html: str) -> tuple[Any | None, str]:
    """Pull a page's server-rendered state out of its HTML.

    Sites move between these representations without warning — dba.dk and
    tori.fi both dropped ``__NEXT_DATA__`` between this catalogue being written
    and being verified — so try each known shape rather than hard-coding one,
    and report which shape matched so the config can be pinned later.
    """
    match = _NEXT_DATA_RE.search(html)
    if match:
        try:
            return json.loads(match.group(1)), "__NEXT_DATA__"
        except json.JSONDecodeError:
            pass

    state = _STATE_ASSIGN_RE.search(html)
    if state:
        try:
            return json.loads(state.group(1)), "window state assignment"
        except json.JSONDecodeError:
            pass

    scripts = _JSON_SCRIPT_RE.findall(html)
    if scripts:
        parsed = _largest_json(scripts)
        if parsed is not None:
            return parsed, "application/json script tag"

    if _FLIGHT_RE.search(html):
        # Recognised but not reassembled: the flight payload is a stream of
        # partial strings, and guessing at it produces silent wrong answers.
        return None, "next-app-router-flight"
    return None, "none"


def suggest_roots(payload: Any, limit: int = 4) -> list[str]:
    """Find the arrays of objects a search result could plausibly live in.

    Same idea as the HTML engine's selector hints: when `root` stops resolving,
    say where the data actually is instead of just returning nothing.
    """
    found: list[tuple[int, str]] = []

    def walk(node: Any, path: str, depth: int) -> None:
        if depth > 8 or len(found) > 400:
            return
        if isinstance(node, list):
            if node and isinstance(node[0], dict):
                found.append((len(node), path))
            if node:
                walk(node[0], f"{path}[0]", depth + 1)
        elif isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str) or not key.isidentifier():
                    continue
                walk(value, f"{path}.{key}" if path else key, depth + 1)

    walk(payload, "", 0)
    found.sort(key=lambda pair: -pair[0])
    return [f"{path} ({count} items)" for count, path in found[:limit]]

# Fields we map straight through; anything else in `fields` is handled specially.
_SIMPLE_FIELDS = (
    "id", "title", "url", "price", "image", "location", "seller", "posted",
    "description", "condition",
)


def _search(expression: str | None, document: Any) -> Any:
    if not expression:
        return None
    try:
        return jmespath.search(expression, document)
    except jmespath.exceptions.JMESPathError:
        return None


class JsonApiEngine(BaseEngine):
    name = "json_api"

    async def _payload(self, query: SearchQuery) -> Any:
        url = self.build_search_url(query)
        mode = self.config.get("mode", "rest")

        if self.config.get("needs_bearer") and not self.credentials.get("bearer"):
            raise NeedsAuth(
                "Needs a bearer token. Grab it from the site's network tab while "
                f"logged in, then: ufeu accounts set {self.market.id} --bearer '<token>'"
            )

        if mode == "next_data":
            response = await self.client.get(url, headers=self.headers(), follow_redirects=True)
            response.raise_for_status()
            payload, strategy = extract_embedded_json(response.text)
            if payload is None:
                if strategy == "next-app-router-flight":
                    raise EngineError(
                        "page moved to the Next.js App Router — its data arrives as a "
                        "streamed flight payload, not one JSON blob. This site needs a "
                        "real endpoint (check the network tab for an XHR) or a browser engine."
                    )
                raise EngineError(
                    "no embedded JSON on the page (tried __NEXT_DATA__, window state, "
                    "and JSON script tags) — the site changed its rendering."
                )
            self._strategy = strategy
            return payload

        method = self.config.get("method", "GET").upper()
        if method == "POST":
            body_template = self.config.get("body") or "{}"
            body = body_template.replace("{q}", query.q.replace('"', '\\"')).replace(
                "{limit}", str(query.limit)
            )
            response = await self.client.post(
                url,
                headers={**self.headers(), "Content-Type": "application/json"},
                content=body.encode("utf-8"),
                follow_redirects=True,
            )
        else:
            response = await self.client.get(url, headers=self.headers(), follow_redirects=True)
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise EngineError("endpoint returned non-JSON (probably an anti-bot page)") from exc

    def _attributes(self, item: Any, fields: dict[str, str]) -> dict[str, Any]:
        """Flatten the two attribute-bag shapes we meet in the wild.

        Subito nests everything under ``features`` keyed by a URI; willhaben
        uses ``attributes.attribute`` keyed by an upper-case name. Both hide the
        price, which is exactly the field we cannot do without.
        """
        out: dict[str, Any] = {}

        feature_map = self.config.get("feature_map")
        if feature_map:
            features = _search(fields.get("features", "features"), item) or []
            index: dict[str, Any] = {}
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                key = feature.get("uri") or feature.get("name")
                values = feature.get("values") or []
                if key and values and isinstance(values[0], dict):
                    index[key] = values[0].get("value") or values[0].get("key")
            for target, source in feature_map.items():
                if source in index:
                    out[target] = index[source]

        attr_map = self.config.get("attr_map")
        if attr_map:
            attributes = _search(fields.get("attrs", "attributes.attribute"), item) or []
            index = {}
            for attribute in attributes:
                if not isinstance(attribute, dict):
                    continue
                name = attribute.get("name")
                values = attribute.get("values") or []
                if name:
                    index[name] = values[0] if values else None
            for target, source in attr_map.items():
                if source in index:
                    out[target] = index[source]
        return out

    async def search(self, query: SearchQuery) -> list[Listing]:
        payload = await self._payload(query)
        root = self.config.get("root")
        items = _search(root, payload) if root else payload
        if items is None or (isinstance(items, list) and not items):
            hints = suggest_roots(payload)
            if hints:
                strategy = getattr(self, "_strategy", None)
                where = f" (extracted via {strategy})" if strategy else ""
                raise EngineError(
                    f"root {root!r} resolved to nothing{where}. Largest arrays of "
                    "objects in the payload: " + " | ".join(hints)
                )
            return []
        if isinstance(items, dict):
            items = list(items.values())
        if not isinstance(items, list):
            raise EngineError(f"expected a list of items at {root!r}, got {type(items).__name__}")

        fields: dict[str, str] = self.config.get("fields", {})
        divisor = float(self.config.get("price_divisor") or 1)
        url_template = self.config.get("url_template")
        currency_field = self.config.get("currency_field")

        listings: list[Listing] = []
        for index, item in enumerate(items[: query.limit]):
            values = {key: _search(fields.get(key), item) for key in _SIMPLE_FIELDS}
            values.update(self._attributes(item, fields))

            price = values.get("price")
            if isinstance(price, (int, float)) and divisor != 1:
                price = price / divisor

            url = values.get("url")
            if url_template and url is not None:
                url = url_template.replace("{}", str(url))

            currency = None
            if currency_field:
                currency = _search(currency_field, item)

            listing = self.make_listing(
                id=str(values.get("id") or f"{index}"),
                title=values.get("title") or "",
                url=url or "",
                price=price,
                currency=currency,
                query=query,
                image=values.get("image"),
                location=values.get("location"),
                seller=values.get("seller"),
                posted=values.get("posted"),
                description=values.get("description"),
                condition=values.get("condition"),
                ships=values.get("shipping"),
            )
            if listing:
                listings.append(listing)
        return listings
