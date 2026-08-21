"""Getting it to Portugal — deliverable (f).

Given where an item is and roughly what it is, rank the realistic ways to move
it to Portugal: the platform's own shipping, a prepaid label posted to a
reluctant seller, a Correos office in a Spanish border town, a diaspora van out
of Paris, or a friend's hold luggage. Every option carries a cost estimate, a
lead time, and an honest effort/risk score, because the cheapest route is very
often the one that costs you a Saturday.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .models import Listing
from .settings import DATA_DIR

# Rough shipping weight (kg) and bulk flag by what the thing obviously is.
# Deliberately coarse — this only has to be right enough to pick a strategy.
_WEIGHT_HINTS: list[tuple[str, float, bool]] = [
    (r"\b(sofa|couch|sofá|wardrobe|armário|schrank|kast|divano|mesa|table|desk|bed|cama|bett)\b", 45.0, True),
    (r"\b(fridge|frigorific|geladeira|kühlschrank|washing machine|máquina de lavar|waschmaschine|lavadora)\b", 65.0, True),
    (r"\b(bicicleta|bike|bicycle|fahrrad|vélo|bici|e-bike|mtb|gravel|roadbike)\b", 15.0, True),
    (r"\b(chair|cadeira|stuhl|stoel|silla|sedia|armchair|cadeirão)\b", 12.0, True),
    (r"\b(piano|drum kit|bateria acústica|amplifier|amplificador|cabinet)\b", 40.0, True),
    (r"\b(tv|televis|monitor|ecrã|bildschirm)\b", 12.0, True),
    (r"\b(lathe|torno|mill|fresadora|generator|gerador|compressor|engine|motor)\b", 90.0, True),
    (r"\b(laptop|macbook|notebook|portátil|thinkpad)\b", 3.5, False),
    (r"\b(desktop|pc tower|workstation|gpu|graphics card|placa gráfica)\b", 8.0, False),
    (r"\b(camera|câmara|kamera|dslr|mirrorless|nikon|canon|sony a7|fuji|leica|lens|objetiva|objektiv)\b", 2.0, False),
    (r"\b(turntable|gira-discos|plattenspieler|receiver|speaker|coluna|lautsprecher)\b", 10.0, True),
    (r"\b(vinyl|lp|record|disco de vinil|schallplatte|book|livro|buch)\b", 1.2, False),
    (r"\b(iphone|samsung|pixel|smartphone|telemóvel|handy|tablet|ipad)\b", 0.6, False),
    (r"\b(lego|puzzle|boardgame|jogo de tabuleiro|console|playstation|xbox|nintendo)\b", 2.5, False),
    (r"\b(watch|relógio|uhr|jewel|jóia|ring|anel)\b", 0.3, False),
    (r"\b(jacket|casaco|dress|vestido|shoes|sapatos|schuhe|bag|mala|clothes|roupa|sneaker)\b", 1.0, False),
    (r"\b(drill|berbequim|bohrmaschine|tool|ferramenta|werkzeug|saw|serra)\b", 5.0, False),
    (r"\b(stroller|carrinho de bebé|kinderwagen|cot|berço)\b", 12.0, True),
]

_DEFAULT_WEIGHT = 2.5


class Provider(BaseModel):
    name: str
    url: str | None = None


class ShippingOption(BaseModel):
    id: str
    name: str
    kind: str
    cost_eur: float
    cost_low_eur: float
    cost_high_eur: float
    days_min: int
    days_max: int
    effort: int
    risk: int
    confidence: str
    overlay: bool = False       # layers on top of another route rather than replacing it
    summary: str
    steps: list[str] = Field(default_factory=list)
    providers: list[Provider] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    landed_cost_eur: float | None = None
    recommended: bool = False


class ShippingPlan(BaseModel):
    country: str
    zone: int
    weight_kg: float
    bulky: bool
    item_price_eur: float | None = None
    options: list[ShippingOption]

    @property
    def best(self) -> ShippingOption | None:
        return self.options[0] if self.options else None


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return yaml.safe_load((DATA_DIR / "shipping.yaml").read_text(encoding="utf-8"))


def estimate_weight(text: str | None) -> tuple[float, bool]:
    """Guess shipping weight and bulkiness from a title/description.

    Multilingual by necessity: the title of a German washing machine will not
    contain the word "washing machine".
    """
    low = (text or "").lower()
    for pattern, weight, bulky in _WEIGHT_HINTS:
        if re.search(pattern, low):
            return weight, bulky
    return _DEFAULT_WEIGHT, False


def zone_for(country: str) -> int:
    return int(_data()["zones"].get((country or "").upper(), 4))


def _cost(strategy: dict[str, Any], zone: int, weight_kg: float) -> float:
    cost = strategy.get("cost") or {}
    base = float(cost.get("base", 0.0))
    per_kg = float(cost.get("per_kg", 0.0))
    fixed = float(cost.get("fixed_extra", 0.0))
    total = base + per_kg * max(weight_kg, 0.5) + fixed

    # Strategies without their own distance pricing scale with the zone table.
    multiplier = cost.get("zone_multiplier")
    if multiplier is not None:
        zone_row = _data()["zone_costs"][zone]
        total = (float(zone_row["base"]) + float(zone_row["per_kg"]) * weight_kg) * float(multiplier)
    elif strategy.get("kind") in ("broker", "carrier", "forwarder") and zone >= 3:
        total *= 1.15  # the far corners of the EU really are dearer
    return round(total, 2)


def _applies(
    strategy: dict[str, Any],
    country: str,
    weight_kg: float,
    bulky: bool,
    native_shipping: bool,
) -> bool:
    countries = strategy.get("countries") or []
    if "ALL" not in countries and country.upper() not in countries:
        return False
    if strategy.get("requires_marketplace_native") and not native_shipping:
        return False
    if weight_kg > float(strategy.get("max_weight_kg", 999)):
        return False
    if weight_kg < float(strategy.get("min_weight_kg", 0)):
        return False
    if bulky and not strategy.get("bulky_ok", False):
        return False
    # Domestic Portugal only ever needs the domestic answer.
    if country.upper() == "PT" and strategy["id"] != "local_pickup":
        return False
    return True


def plan(
    country: str,
    *,
    title: str | None = None,
    weight_kg: float | None = None,
    bulky: bool | None = None,
    item_price_eur: float | None = None,
    native_shipping: bool = False,
) -> ShippingPlan:
    """Rank every viable route from `country` to Portugal."""
    guessed_weight, guessed_bulky = estimate_weight(title)
    weight = weight_kg if weight_kg is not None else guessed_weight
    is_bulky = guessed_bulky if bulky is None else bulky
    zone = zone_for(country)

    options: list[ShippingOption] = []
    for strategy in _data()["strategies"]:
        if not _applies(strategy, country, weight, is_bulky, native_shipping):
            continue
        cost = _cost(strategy, zone, weight)
        days = strategy.get("days", [3, 10])
        options.append(
            ShippingOption(
                id=strategy["id"],
                name=strategy["name"],
                kind=strategy["kind"],
                cost_eur=cost,
                cost_low_eur=round(cost * 0.75, 2),
                cost_high_eur=round(cost * 1.45, 2),
                days_min=int(days[0]),
                days_max=int(days[1]),
                effort=int(strategy.get("effort", 3)),
                risk=int(strategy.get("risk", 3)),
                confidence=strategy.get("confidence", "medium"),
                overlay=bool(strategy.get("overlay")),
                summary=" ".join((strategy.get("summary") or "").split()),
                steps=strategy.get("steps") or [],
                providers=[Provider(**p) for p in (strategy.get("providers") or [])],
                caveats=strategy.get("caveats") or [],
                landed_cost_eur=round(item_price_eur + cost, 2) if item_price_eur is not None else None,
            )
        )

    # Rank by money first, then by how much of your life it costs. The penalty
    # keeps a €4-cheaper option from beating a one-click one. Overlays always
    # sort last: they are an add-on cost, not an alternative to a real route.
    options.sort(key=lambda o: (o.overlay, o.cost_eur + o.effort * 2.5 + o.risk * 2.0, o.days_max))
    primary = [o for o in options if not o.overlay]
    if primary:
        primary[0].recommended = True
    return ShippingPlan(
        country=country.upper(),
        zone=zone,
        weight_kg=weight,
        bulky=is_bulky,
        item_price_eur=item_price_eur,
        options=options,
    )


def plan_for_listing(listing: Listing, native_shipping: bool | None = None) -> ShippingPlan:
    text = " ".join(part for part in (listing.title, listing.description) if part)
    return plan(
        listing.country,
        title=text,
        item_price_eur=listing.price_eur,
        native_shipping=bool(listing.ships) if native_shipping is None else native_shipping,
    )


def cheapest_cost(country: str, title: str | None = None, native_shipping: bool = False) -> float | None:
    """Shorthand used to annotate every row in a result list with a landed cost."""
    options = [o for o in plan(country, title=title, native_shipping=native_shipping).options if not o.overlay]
    return min((o.cost_eur for o in options), default=None)
