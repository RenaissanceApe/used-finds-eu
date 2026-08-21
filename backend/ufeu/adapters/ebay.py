"""eBay Browse API — the one fully sanctioned, documented integration here.

Nine EU marketplaces behind a single credential, a real "used condition"
filter, and no scraping. Get a free keyset at developer.ebay.com/my/keys, then:

    ufeu accounts set ebay --client-id <id> --client-secret <secret>

Application tokens last two hours and are cached in the vault, so a normal
day's searching costs one auth call.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any
from urllib.parse import quote

from .. import vault
from ..models import Listing, SearchQuery
from .base import BaseEngine, EngineError, NeedsAuth

# eBay marketplace id → ISO country, so results land in the right country bucket.
_MARKETPLACE_COUNTRY = {
    "EBAY_DE": "DE", "EBAY_FR": "FR", "EBAY_IT": "IT", "EBAY_ES": "ES",
    "EBAY_IE": "IE", "EBAY_NL": "NL", "EBAY_AT": "AT", "EBAY_BE": "BE",
    "EBAY_PL": "PL", "EBAY_GB": "GB", "EBAY_US": "US",
}
_SITE_HOST = {
    "EBAY_DE": "ebay.de", "EBAY_FR": "ebay.fr", "EBAY_IT": "ebay.it",
    "EBAY_ES": "ebay.es", "EBAY_IE": "ebay.ie", "EBAY_NL": "ebay.nl",
    "EBAY_AT": "ebay.at", "EBAY_BE": "befr.ebay.be", "EBAY_PL": "ebay.pl",
}

_token_lock = asyncio.Lock()


class EbayEngine(BaseEngine):
    name = "ebay_browse"

    def build_search_url(self, query: SearchQuery) -> str:
        return f"https://www.ebay.de/sch/i.html?_nkw={quote(query.q)}&LH_ItemCondition=4"

    async def _token(self) -> str:
        client_id = self.credentials.get("client_id")
        client_secret = self.credentials.get("client_secret")
        if not (client_id and client_secret):
            raise NeedsAuth(
                "No eBay API credentials. Create a free keyset at "
                "developer.ebay.com/my/keys, then run: "
                "ufeu accounts set ebay --client-id <id> --client-secret <secret>"
            )

        cached = self.credentials.get("access_token")
        expires_at = self.credentials.get("access_token_expires_at") or 0
        if cached and time.time() < float(expires_at) - 60:
            return cached

        async with _token_lock:
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            response = await self.client.post(
                self.config.get("auth_url", "https://api.ebay.com/identity/v1/oauth2/token"),
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": self.config.get("scope", "https://api.ebay.com/oauth/api_scope"),
                },
            )
            if response.status_code in (400, 401):
                raise NeedsAuth("eBay rejected the keyset — check it is a *production* keyset, not sandbox.")
            response.raise_for_status()
            payload = response.json()
            token = payload["access_token"]
            # Persist so restarts and other engines reuse it.
            vault.set_credentials(
                self.market.id,
                access_token=token,
                access_token_expires_at=time.time() + float(payload.get("expires_in", 7200)),
            )
            self.credentials["access_token"] = token
            return token

    async def _search_one(self, marketplace: str, token: str, query: SearchQuery, limit: int) -> list[Listing]:
        condition_ids = "|".join(self.config.get("condition_ids", ["3000", "4000", "5000", "6000", "7000"]))
        filters = [f"conditionIds:{{{condition_ids}}}"]
        if query.min_price_eur or query.max_price_eur:
            low = int(query.min_price_eur or 0)
            high = int(query.max_price_eur) if query.max_price_eur else ""
            filters.append(f"price:[{low}..{high}]")
            filters.append("priceCurrency:EUR")

        response = await self.client.get(
            self.config.get("search_url", "https://api.ebay.com/buy/browse/v1/item_summary/search"),
            params={"q": query.q, "limit": str(limit), "filter": ",".join(filters)},
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept": "application/json",
            },
        )
        if response.status_code == 400:
            # A marketplace can reject a filter combination; skip it rather than
            # failing the whole fan-out.
            return []
        response.raise_for_status()
        summaries = response.json().get("itemSummaries") or []

        country = _MARKETPLACE_COUNTRY.get(marketplace, "EU")
        listings: list[Listing] = []
        for item in summaries:
            price: dict[str, Any] = item.get("price") or {}
            shipping_options = item.get("shippingOptions") or []
            listing = self.make_listing(
                id=str(item.get("itemId")),
                title=item.get("title") or "",
                url=item.get("itemWebUrl") or "",
                price=price.get("value"),
                currency=price.get("currency"),
                query=query,
                image=(item.get("image") or {}).get("imageUrl"),
                location=(item.get("itemLocation") or {}).get("country"),
                seller=(item.get("seller") or {}).get("username"),
                condition=item.get("condition"),
                ships=bool(shipping_options),
                raw={"marketplace": marketplace, "host": _SITE_HOST.get(marketplace)},
            )
            if listing:
                # Attribute the row to the selling country, not to "EU".
                listing.country = country
                listing.marketplace_name = f"eBay {country}"
                listings.append(listing)
        return listings

    async def search(self, query: SearchQuery) -> list[Listing]:
        token = await self._token()
        marketplaces: list[str] = self.config.get("marketplaces", ["EBAY_DE"])
        if query.countries:
            wanted = {c.upper() for c in query.countries}
            filtered = [m for m in marketplaces if _MARKETPLACE_COUNTRY.get(m) in wanted]
            marketplaces = filtered or marketplaces

        per_site = max(4, query.limit // max(len(marketplaces), 1))
        batches = await asyncio.gather(
            *(self._search_one(m, token, query, per_site) for m in marketplaces),
            return_exceptions=True,
        )
        listings: list[Listing] = []
        errors: list[str] = []
        for marketplace, batch in zip(marketplaces, batches):
            if isinstance(batch, BaseException):
                errors.append(f"{marketplace}: {type(batch).__name__}")
                continue
            listings.extend(batch)
        if not listings and errors:
            raise EngineError("all eBay sites failed — " + "; ".join(errors))
        return listings
