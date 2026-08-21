"""HTTP API + static hosting for the UI. Deliverable (c)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache, fx, shipping, vault
from .adapters import demo_mode
from .catalog import load_catalog
from .models import SearchQuery, SearchResponse
from .orchestrator import search as run_search
from .settings import FRONTEND_DIR, HOME_COUNTRY

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="used-finds-eu",
    description="One search box over Europe's second-hand marketplaces, priced to your door in Portugal.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    rates = fx.load()
    return {
        "ok": True,
        "demo_mode": demo_mode(),
        "home_country": HOME_COUNTRY,
        "fx_stale": rates.stale,
        "fx_as_of": rates.as_of.date().isoformat() if rates.as_of else None,
        "catalog_updated": load_catalog().updated,
    }


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    cat = load_catalog()
    configured = vault.status()
    return {
        "updated": cat.updated,
        "countries": [
            {
                "code": code,
                "name": country.name,
                "currency": country.currency,
                "zone": shipping.zone_for(code),
                "marketplaces": [m.id for m in cat.for_country(code)],
            }
            for code, country in sorted(cat.countries.items(), key=lambda kv: kv[1].name)
        ],
        "marketplaces": [
            {
                "id": m.id,
                "name": m.name,
                "country": m.country,
                "rank": m.rank,
                "scope": m.scope,
                "site": m.site,
                "focus": m.focus,
                "engine": m.engine,
                "enabled": m.default_enabled,
                "confidence": m.confidence,
                "why": m.why,
                "ships_to_pt": m.shipping.native_to_pt,
                "shipping_notes": m.shipping.notes,
                "account": m.account.model_dump(),
                "configured": m.id in configured,
            }
            for m in cat.marketplaces
        ],
    }


@app.post("/api/search", response_model=SearchResponse)
async def search(query: SearchQuery) -> SearchResponse:
    if not query.q.strip():
        raise HTTPException(status_code=400, detail="Give me something to search for.")
    query.limit = max(1, min(query.limit, 100))
    return await run_search(query)


@app.get("/api/shipping")
def shipping_plan(
    country: str = Query(..., min_length=2, max_length=2),
    title: str | None = None,
    price_eur: float | None = None,
    weight_kg: float | None = None,
    native: bool = False,
) -> dict[str, Any]:
    return shipping.plan(
        country,
        title=title,
        weight_kg=weight_kg,
        item_price_eur=price_eur,
        native_shipping=native,
    ).model_dump()


@app.get("/api/accounts")
def accounts() -> dict[str, Any]:
    cat = load_catalog()
    configured = vault.status()
    rows = []
    for market in cat.marketplaces:
        if market.account.kind == "none" and market.id not in configured:
            continue
        rows.append(
            {
                "id": market.id,
                "name": market.name,
                "country": market.country,
                "kind": market.account.kind,
                "required_for_search": market.account.required_for_search,
                "signup_url": market.account.signup_url,
                "signup_method": market.account.signup_method,
                "credentials": market.account.credentials,
                "captcha": market.account.captcha,
                "automatable": market.account.automatable,
                "notes": market.account.notes,
                "configured": market.id in configured,
                "fields": configured.get(market.id, {}).get("fields", []),
                "updated_at": configured.get(market.id, {}).get("updated_at"),
            }
        )
    return {"accounts": rows}


class CredentialPayload(BaseModel):
    """Whatever a given site needs: cookie, bearer, or an API keypair."""

    cookie: str | None = None
    bearer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    app_id: str | None = None
    app_key: str | None = None
    username: str | None = None
    note: str | None = None


@app.put("/api/accounts/{marketplace_id}")
def set_account(marketplace_id: str, payload: CredentialPayload = Body(...)) -> dict[str, Any]:
    if marketplace_id not in load_catalog().by_id:
        raise HTTPException(status_code=404, detail=f"Unknown marketplace {marketplace_id!r}")
    fields = {k: v for k, v in payload.model_dump().items() if v}
    if not fields:
        raise HTTPException(status_code=400, detail="No credential fields supplied.")
    vault.set_credentials(marketplace_id, **fields)
    return {"ok": True, "id": marketplace_id, "fields": sorted(fields)}


@app.delete("/api/accounts/{marketplace_id}")
def delete_account(marketplace_id: str) -> dict[str, Any]:
    return {"ok": vault.delete_credentials(marketplace_id), "id": marketplace_id}


@app.post("/api/cache/purge")
def purge_cache() -> dict[str, Any]:
    return {"removed": cache.purge(0)}


@app.exception_handler(vault.VaultError)
def vault_error(_request, exc: vault.VaultError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# The UI is plain static files — no build step, no toolchain, no npm.
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
