# Putting it online

## What can and cannot be hosted

GitHub Pages serves **files, not servers**. The Python backend — the part that
queries 31 marketplaces in parallel and merges the results — cannot run there.
So the project ships two builds:

| | Static build (`site/`) | Backend (`backend/`) |
| --- | --- | --- |
| Marketplace catalogue, all 64 sites | ✅ | ✅ |
| Shipping resolver, all 14 routes | ✅ (same logic, ported to JS) | ✅ |
| Search **launcher** — your query as a real search URL on every site | ✅ | ✅ |
| **Aggregated** results: 31 sites merged, EUR-normalised, de-duplicated | ❌ | ✅ |
| Sort by landed cost to Portugal | ❌ | ✅ |

The missing row is not a shortcut — a browser genuinely cannot call Vinted's or
OLX's API cross-origin, because those hosts send no CORS headers. Any "static
aggregator" you have seen is quietly proxying through a server somewhere.

The hosted page bridges the gap: the **Live results** tab takes the URL of a
running backend (yours, local or self-hosted) and renders real merged results
through it.

## Publishing to GitHub Pages

`.github/workflows/pages.yml` does the whole build — including regenerating
`site/data.json` from the YAML catalogue, so the published site can never drift
from what the app searches. Two settings have to be right first:

**1. The repository must be public.** GitHub Pages on a *private* repository
requires a paid plan (Pro/Team/Enterprise). On the free plan the only way to get
a `github.io` URL is to make the repo public — which publishes the source, so
it is your call. There are no credentials in the repo (`.gitignore` excludes the
vault, and secrets live in `~/.local/state/ufeu/`, never here), so it is safe to
publish from that angle.

*Settings → General → Danger Zone → Change repository visibility → Public.*

**2. Pages source must be "GitHub Actions".**

*Settings → Pages → Build and deployment → Source → **GitHub Actions**.*

Then merge this branch into `main`. The workflow runs on push and the site
lands at:

```
https://renaissanceape.github.io/used-finds-eu/
```

If the deploy fails with *"Branch is not allowed to deploy to github-pages due
to environment protection rules"*, the `github-pages` environment is restricted
to the default branch — either merge to `main` (simplest) or add the branch
under *Settings → Environments → github-pages → Deployment branches*.

## Free domains, if `github.io` is not weird enough

A `renaissanceape.github.io` subdomain is already free and permanent. If you
want something shorter, these are genuinely free but all require a pull request
to somebody else's repository and a human to approve it — days, not minutes:

| Domain | How | Fit |
| --- | --- | --- |
| `is-a.dev` | PR to [is-a-dev/register](https://github.com/is-a-dev/register) | `used-finds.is-a.dev` — easiest, usually days |
| `js.org` | PR to [js-org/js.org](https://github.com/js-org/js.org) | `used-finds.js.org` — must be JS-related, which this is |
| `eu.org` | form at [nic.eu.org](https://nic.eu.org) | `used-finds.eu.org` — very on-theme, manual review, slowest |
| `.dpdns.org`, `.freeddns.org` | [DigitalPlat FreeDomain](https://domain.digitalplat.org) | instant-ish, but flaky reputation |

Whichever you pick: add a `CNAME` file containing the domain to `site/`, point a
`CNAME` DNS record at `renaissanceape.github.io`, and tick *Enforce HTTPS* in
Settings → Pages.

## Hosting the backend too (free tiers)

If you want the aggregated view online rather than on your laptop:

- **Fly.io** or **Render** free tier — `pip install -r backend/requirements.txt`,
  then `uvicorn ufeu.api:app --host 0.0.0.0 --port $PORT`.
- Set `UFEU_ALLOWED_ORIGINS` to your Pages origin, e.g.
  `https://renaissanceape.github.io`, or the browser will block the calls.
- Set `UFEU_VAULT_PASSPHRASE` so the credential vault is not readable from the
  container's disk alone.

Then paste that backend's URL into the **Live results** tab once; it is
remembered in your browser.

**Think before you do this.** A public backend is an open proxy that makes
requests to 30 marketplaces on behalf of anyone who finds it — which is how you
get an IP banned. Put it behind auth, or keep it on your laptop, where the
traffic looks like one person shopping. Which it is.

## No server at all

`site/standalone.html` is the entire static build inlined into one file —
catalogue, shipping calculator, launcher, ~110 KB. Double-click it. It works
offline, and you can email it to yourself.
