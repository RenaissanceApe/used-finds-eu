"""Engine registry: marketplace → the code that can query it."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..catalog import Marketplace
from .base import BaseEngine, EngineError, NeedsAuth
from .demo import DemoEngine
from .ebay import EbayEngine
from .html import HtmlEngine
from .json_api import JsonApiEngine
from .manual import ManualEngine
from .olx import OlxEngine
from .vinted import VintedEngine

ENGINES: dict[str, type[BaseEngine]] = {
    "vinted": VintedEngine,
    "olx": OlxEngine,
    "ebay_browse": EbayEngine,
    "json_api": JsonApiEngine,
    "html": HtmlEngine,
    "manual": ManualEngine,
    "demo": DemoEngine,
}


def demo_mode() -> bool:
    return os.environ.get("UFEU_DEMO", "").lower() in ("1", "true", "yes")


def build_engine(
    market: Marketplace,
    client: httpx.AsyncClient,
    credentials: dict[str, Any] | None = None,
) -> BaseEngine:
    if demo_mode():
        return DemoEngine(market, client, credentials)
    engine_class = ENGINES.get(market.engine)
    if engine_class is None:
        raise EngineError(f"unknown engine {market.engine!r} for {market.id}")
    return engine_class(market, client, credentials)


__all__ = ["ENGINES", "BaseEngine", "EngineError", "NeedsAuth", "build_engine", "demo_mode"]
