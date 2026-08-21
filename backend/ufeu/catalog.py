"""Loads data/marketplaces.yaml into typed objects and answers "which sites?"."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .settings import DATA_DIR


class AccountSpec(BaseModel):
    required_for_search: bool = False
    kind: str = "none"                      # none | session | api_key
    signup_url: str | None = None
    signup_method: list[str] = Field(default_factory=list)
    credentials: list[str] = Field(default_factory=list)
    captcha: bool = False
    automatable: bool = False
    notes: str | None = None


class ShippingSpec(BaseModel):
    native_to_pt: bool = False
    notes: str | None = None


class Marketplace(BaseModel):
    id: str
    name: str
    country: str
    rank: int = 3
    scope: str = "national"                 # national | pan_eu
    site: str
    focus: list[str] = Field(default_factory=list)
    engine: str
    default_enabled: bool = False
    dedupe_group: str | None = None
    confidence: str = "medium"
    why: str | None = None
    engine_config: dict[str, Any] = Field(default_factory=dict)
    account: AccountSpec = Field(default_factory=AccountSpec)
    shipping: ShippingSpec = Field(default_factory=ShippingSpec)

    @property
    def currency(self) -> str:
        return self.engine_config.get("currency", "EUR")


class Country(BaseModel):
    code: str
    name: str
    currency: str
    lang: str


class Catalog(BaseModel):
    version: int
    updated: str
    countries: dict[str, Country]
    marketplaces: list[Marketplace]

    @property
    def by_id(self) -> dict[str, Marketplace]:
        return {m.id: m for m in self.marketplaces}

    def for_country(self, code: str) -> list[Marketplace]:
        return sorted(
            (m for m in self.marketplaces if m.country == code.upper()),
            key=lambda m: (m.rank, m.name),
        )

    def select(
        self,
        countries: list[str] | None = None,
        marketplace_ids: list[str] | None = None,
        include_disabled: bool = False,
    ) -> list[Marketplace]:
        """Resolve a UI selection into the concrete list of sites to query.

        Explicit ids always win — if you asked for a marketplace by name you get
        it whether or not it is enabled by default.
        """
        if marketplace_ids:
            wanted = set(marketplace_ids)
            return [m for m in self.marketplaces if m.id in wanted]

        pool = self.marketplaces
        if countries:
            codes = {c.upper() for c in countries}
            # Pan-EU sites are relevant to every country selection, but only if
            # the user did not deselect them explicitly.
            pool = [m for m in pool if m.country in codes or m.scope == "pan_eu"]
        if not include_disabled:
            pool = [m for m in pool if m.default_enabled]
        return sorted(pool, key=lambda m: (m.scope != "pan_eu", m.rank, m.country, m.name))


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    raw = yaml.safe_load((DATA_DIR / "marketplaces.yaml").read_text(encoding="utf-8"))
    countries = {code: Country(code=code, **body) for code, body in raw["countries"].items()}
    marketplaces = [Marketplace(**entry) for entry in raw["marketplaces"]]

    known = set(countries)
    for market in marketplaces:
        if market.country not in known:
            raise ValueError(f"{market.id}: unknown country {market.country!r}")
    return Catalog(
        version=raw["version"],
        updated=str(raw["updated"]),
        countries=countries,
        marketplaces=marketplaces,
    )
