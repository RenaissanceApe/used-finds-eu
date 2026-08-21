"""For marketplaces we deliberately do not automate.

leboncoin, Milanuncios and Facebook Marketplace all sit behind commercial bot
protection and/or forbid automated access outright. Rather than pretend, or
ship something that gets your IP burned in a week, these return a MANUAL row:
the query is folded into a real search URL and surfaced as a one-click link.
The country still shows up in your results — honestly labelled.
"""

from __future__ import annotations

from ..models import Listing, MarketResult, ResultStatus, SearchQuery
from .base import BaseEngine


class ManualEngine(BaseEngine):
    name = "manual"

    async def search(self, query: SearchQuery) -> list[Listing]:
        return []

    async def run(self, query: SearchQuery) -> MarketResult:
        return MarketResult(
            marketplace_id=self.market.id,
            marketplace_name=self.market.name,
            country=self.market.country,
            status=ResultStatus.MANUAL,
            search_url=self.build_search_url(query),
            error=self.market.why or "Automated search not offered for this site.",
        )
