"""Offline fixture engine.

Lets the whole app — UI, filtering, dedupe, currency conversion, shipping
resolution — be demonstrated and tested without touching a single marketplace.
Enable it with ``UFEU_DEMO=1``; every catalogue entry is then served from
``tests/fixtures/demo_listings.json`` instead of the network.
"""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

from ..models import Listing, SearchQuery
from ..normalize import tokenize
from .base import BaseEngine

_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo_listings.json"


@lru_cache(maxsize=1)
def _fixture_data() -> list[dict]:
    if not _FIXTURE.exists():
        return []
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


class DemoEngine(BaseEngine):
    name = "demo"

    async def search(self, query: SearchQuery) -> list[Listing]:
        rng = random.Random(f"{self.market.id}:{query.q}")
        query_tokens = set(tokenize(query.q))
        listings: list[Listing] = []

        for template in _fixture_data():
            if query_tokens and not (query_tokens & set(tokenize(template["title"]))):
                continue
            # Give each marketplace its own plausible price and id.
            jitter = rng.uniform(0.7, 1.35)
            listing = self.make_listing(
                id=f"demo-{rng.randrange(10**6)}",
                title=template["title"],
                url=f"{self.market.site}/item/demo-{rng.randrange(10**6)}",
                price=round(template["price_eur"] * jitter, 2),
                currency="EUR",
                query=query,
                image=template.get("image"),
                location=self.market.country,
                seller=template.get("seller", "demo_seller"),
                description=template.get("description"),
                condition=template.get("condition"),
                ships=self.market.shipping.native_to_pt,
            )
            if listing:
                listings.append(listing)
        if not listings:
            # Nothing in the fixtures matches — synthesise plausible rows so any
            # query demonstrates the full pipeline, not just the seeded ones.
            listings = self._synthesise(query, rng)
        rng.shuffle(listings)
        return listings[: query.limit]

    def _synthesise(self, query: SearchQuery, rng: random.Random) -> list[Listing]:
        conditions = ["Like new", "Very good", "Good", "Fair", "For parts"]
        base = rng.uniform(25, 400)
        out: list[Listing] = []
        for n in range(rng.randrange(2, 7)):
            listing = self.make_listing(
                id=f"synth-{rng.randrange(10**6)}",
                title=f"{query.q.title()} ({rng.choice(conditions).lower()})",
                url=f"{self.market.site}/item/synth-{rng.randrange(10**6)}",
                price=round(base * rng.uniform(0.6, 1.6), 2),
                currency="EUR",
                query=query,
                location=self.market.country,
                seller=f"user{rng.randrange(1000, 9999)}",
                condition=rng.choice(conditions),
                ships=self.market.shipping.native_to_pt,
            )
            if listing:
                out.append(listing)
        return out
