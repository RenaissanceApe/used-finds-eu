"""Command line entry point: `ufeu serve`, `ufeu search`, `ufeu accounts`, `ufeu ship`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import shipping, vault
from .catalog import load_catalog
from .models import ResultStatus, SearchQuery
from .orchestrator import search as run_search


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("ufeu.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    query = SearchQuery(
        q=args.query,
        countries=args.country,
        marketplaces=args.marketplace,
        max_price_eur=args.max_price,
        min_price_eur=args.min_price,
        limit=args.limit,
        sort=args.sort,
        include_disabled=args.all,
        fresh=args.fresh,
    )
    response = asyncio.run(run_search(query))
    if args.json:
        print(response.model_dump_json(indent=2))
        return 0

    stats = response.stats
    print(
        f"\n{stats.listings_total} listings from {stats.markets_ok}/{stats.markets_queried} "
        f"marketplaces in {stats.elapsed_ms/1000:.1f}s "
        f"({stats.duplicates_removed} duplicates removed)\n"
    )
    for listing in response.listings:
        price = f"€{listing.price_eur:,.0f}" if listing.price_eur is not None else "—"
        landed = f"€{listing.landed_cost_eur:,.0f}" if listing.landed_cost_eur is not None else "—"
        print(f"  {listing.country:<3} {listing.marketplace_name:<24} {price:>9} → {landed:>9} landed")
        print(f"      {listing.title[:88]}")
        print(f"      {listing.url}")
        if listing.shipping_strategy:
            print(f"      ship: {listing.shipping_strategy}")
        print()

    problems = [r for r in response.results if r.status not in (ResultStatus.OK, ResultStatus.EMPTY)]
    if problems:
        print("Needs attention:")
        for result in problems:
            print(f"  {result.marketplace_name:<26} {result.status.value:<11} {result.error or ''}")
            if result.status == ResultStatus.MANUAL and result.search_url:
                print(f"      {result.search_url}")
    return 0


def _cmd_accounts(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    if args.action == "list":
        configured = vault.status()
        for market in catalog.marketplaces:
            if market.account.kind == "none":
                continue
            mark = "✓" if market.id in configured else " "
            need = "required" if market.account.required_for_search else "optional"
            print(f" [{mark}] {market.id:<22} {market.account.kind:<8} {need:<8} {market.name}")
        return 0

    if args.id not in catalog.by_id:
        print(f"Unknown marketplace {args.id!r}", file=sys.stderr)
        return 1

    if args.action == "set":
        fields = {
            k: v
            for k, v in {
                "cookie": args.cookie,
                "bearer": args.bearer,
                "client_id": args.client_id,
                "client_secret": args.client_secret,
                "app_id": args.app_id,
                "app_key": args.app_key,
                "username": args.username,
            }.items()
            if v
        }
        if not fields:
            print("Nothing to set — pass at least one credential flag.", file=sys.stderr)
            return 1
        vault.set_credentials(args.id, **fields)
        print(f"Stored {', '.join(sorted(fields))} for {args.id}.")
        return 0

    if args.action == "delete":
        print("Deleted." if vault.delete_credentials(args.id) else "Nothing stored for that id.")
        return 0
    return 1


def _cmd_ship(args: argparse.Namespace) -> int:
    plan = shipping.plan(
        args.country, title=args.item, item_price_eur=args.price, weight_kg=args.weight
    )
    if args.json:
        print(json.dumps(plan.model_dump(), indent=2))
        return 0
    print(
        f"\n{args.country.upper()} → PT  ·  zone {plan.zone}  ·  "
        f"~{plan.weight_kg:g}kg{' · bulky' if plan.bulky else ''}\n"
    )
    for option in plan.options:
        star = "★" if option.recommended else " "
        landed = f"  landed €{option.landed_cost_eur:,.0f}" if option.landed_cost_eur else ""
        print(
            f" {star} €{option.cost_eur:>6,.0f} ({option.cost_low_eur:.0f}-{option.cost_high_eur:.0f})  "
            f"{option.days_min}-{option.days_max}d  effort {option.effort}/5  risk {option.risk}/5  "
            f"{option.name}{landed}"
        )
        print(f"      {option.summary}")
        for step in option.steps:
            print(f"        · {step}")
        for caveat in option.caveats:
            print(f"        ! {caveat}")
        print()
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    for code, country in sorted(catalog.countries.items(), key=lambda kv: kv[1].name):
        markets = catalog.for_country(code)
        if not markets:
            continue
        print(f"\n{country.name} ({code})  ·  {country.currency}  ·  shipping zone {shipping.zone_for(code)}")
        for market in markets:
            flags = []
            if market.default_enabled:
                flags.append("on")
            if market.shipping.native_to_pt:
                flags.append("ships→PT")
            if market.engine == "manual":
                flags.append("manual")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            print(f"   {market.rank}. {market.name:<28} {market.site}{suffix}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ufeu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    search = sub.add_parser("search", help="search every enabled marketplace")
    search.add_argument("query")
    search.add_argument("-c", "--country", action="append", help="restrict to country code (repeatable)")
    search.add_argument("-m", "--marketplace", action="append", help="restrict to marketplace id (repeatable)")
    search.add_argument("--min-price", type=float)
    search.add_argument("--max-price", type=float)
    search.add_argument("-n", "--limit", type=int, default=24)
    search.add_argument(
        "--sort", default="relevance",
        choices=["relevance", "price_asc", "price_desc", "newest", "landed_asc"],
    )
    search.add_argument("--all", action="store_true", help="include marketplaces that are off by default")
    search.add_argument("--fresh", action="store_true", help="bypass the cache")
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=_cmd_search)

    accounts = sub.add_parser("accounts", help="manage stored credentials")
    accounts.add_argument("action", choices=["list", "set", "delete"])
    accounts.add_argument("id", nargs="?")
    accounts.add_argument("--cookie")
    accounts.add_argument("--bearer")
    accounts.add_argument("--client-id")
    accounts.add_argument("--client-secret")
    accounts.add_argument("--app-id")
    accounts.add_argument("--app-key")
    accounts.add_argument("--username")
    accounts.set_defaults(func=_cmd_accounts)

    ship = sub.add_parser("ship", help="how do I get it to Portugal?")
    ship.add_argument("country")
    ship.add_argument("-i", "--item", help="item title, used to guess weight and bulk")
    ship.add_argument("-p", "--price", type=float)
    ship.add_argument("-w", "--weight", type=float)
    ship.add_argument("--json", action="store_true")
    ship.set_defaults(func=_cmd_ship)

    catalog = sub.add_parser("catalog", help="show the marketplace catalogue by country")
    catalog.set_defaults(func=_cmd_catalog)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
