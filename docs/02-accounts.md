# (b) Accounts: what this tool does, and what it deliberately does not

## The short version

**The tool does not create accounts for you, and it should not.** It gives you a
per-site signup playbook, an encrypted local vault for whatever credential each
site issues, and — importantly — the finding that **for most of the catalogue you
do not need an account at all to search.**

## Why automated signup is off the table

Every platform in the catalogue puts at least one of these in front of
registration:

| Barrier | Where you hit it |
| --- | --- |
| CAPTCHA (reCAPTCHA / hCaptcha / DataDome) | Vinted, OLX, Wallapop, Kleinanzeigen, Marktplaats, willhaben, Subito, Blocket, leboncoin, Njuškalo, Jófogás |
| SMS / phone verification | Wallapop (mandatory for messaging), OLX, Vinted (risk-triggered), Subito |
| Email confirmation loop | essentially all of them |
| Device / IP reputation checks | leboncoin, Milanuncios, Kleinanzeigen, Facebook Marketplace |

And every one of them prohibits automated account creation in its terms. Two
practical consequences, not just legal ones:

1. **It does not work.** Scripted signups fail at the CAPTCHA, or succeed and
   then get flagged and banned within days — often taking the phone number and
   IP with them, which then poisons your *legitimate* account on that site.
2. **The banned account is the one you needed.** These platforms are where you
   message sellers and pay. Losing the account loses the purchase.

So the honest design is: you register by hand, once, and the tool never touches
the signup flow.

## What you actually need, ranked by payoff

### Tier 1 — do this first (20 minutes, unlocks most of Europe)

**1. eBay developer keyset.** The single best-value step in this whole project.
Free, self-service, no scraping, and it covers nine EU marketplaces
(DE/FR/IT/ES/IE/NL/AT/BE/PL) through a documented, supported API with a real
"used condition" filter.

```
open https://developer.ebay.com/my/keys     # sign in, create a PRODUCTION keyset
ufeu accounts set ebay --client-id <id> --client-secret <secret>
```

Application tokens last two hours and the tool caches them in the vault, so a
day's searching costs one auth call. Note *production*, not sandbox — a sandbox
keyset authenticates fine and then returns no listings, which is a confusing
half-hour if you do not know to look for it.

**2. Nothing else.** Really. Vinted, OLX (PT/PL/RO/BG), Marktplaats, 2dehands,
Subito, willhaben, Bazoš, SS.lv, Njuškalo, Bolha, Bazaraki, MaltaPark, Jófogás,
Skelbiu, Okidoki, Adverts.ie, Tori, DBA and Kleinanzeigen are all **searchable
anonymously**. The Vinted engine bootstraps an anonymous session cookie by
itself. You only need accounts on these to *message a seller and buy* — which
you will do in the browser anyway, on the sites where you actually find
something.

### Tier 2 — the one site that needs a token to search

**Blocket (Sweden)** wants a bearer token even for anonymous search. Get it once
from your own browser:

1. Open <https://www.blocket.se> and search for anything.
2. DevTools → Network → filter `search_bff` → click the request.
3. Copy the value after `Bearer ` in the `Authorization` request header.

```
ufeu accounts set blocket_se --bearer '<token>'
```

It lasts weeks. When it expires the marketplace comes back as `needs_auth` in
the results panel rather than failing silently.

### Tier 3 — accounts you create when you are ready to buy

Create these by hand, on the site, in your browser, when a search actually turns
something up. Signup links are in the **Accounts** tab of the UI and in
`backend/ufeu/data/marketplaces.yaml`.

| Platform | Signup | Notes |
| --- | --- | --- |
| Vinted | email / Google / Apple | One account works across the whole connected pool — you do not need one per country domain. |
| OLX (PT/PL/RO/BG) | email or phone | One OLX account per country domain. |
| Wallapop | phone | Phone verification is effectively mandatory to message sellers. |
| Kleinanzeigen | email | Aggressive fraud checks on new accounts; expect limits in week one. |
| Marktplaats / 2dehands | email | Shared identity across the two. |
| Subito, willhaben, Blocket, DBA, Tori | email | Standard. |

## Storing a session cookie (for sites with no API)

If you want an engine to act as your logged-in self — to see member-only
listings, or because a site has started requiring it — export the cookie from
your own browser session and store it:

1. Log in normally in your browser.
2. DevTools → Application → Cookies → copy the whole cookie header value
   (or use a "copy as cURL" on any XHR and take the `Cookie:` line).
3. `ufeu accounts set <marketplace_id> --cookie '<the cookie string>'`

The engine will send it on that marketplace's requests and nowhere else.

**Do not paste a cookie for a site you are not willing to have this tool act
as.** A session cookie is a bearer credential: whoever holds it is you.

## How the vault works

- Location: `~/.local/state/ufeu/vault.enc`, mode `0600`.
- Encryption: Fernet (AES-128-CBC + HMAC). The key lives beside it at
  `vault.key`, also `0600`.
- **Better:** set `UFEU_VAULT_PASSPHRASE` and the key is derived with scrypt
  instead, so the file on disk is useless without the passphrase.
- Credentials are sent **only** to the marketplace they belong to. Nothing is
  transmitted to any third party, and the `/api/accounts` endpoint returns field
  *names* and timestamps, never values (there is a test asserting exactly that).
- `ufeu accounts list` shows what is stored; `ufeu accounts delete <id>` removes it.

## "Browser-session engines" — the escape hatch for leboncoin and friends

Three entries (leboncoin, Milanuncios, Facebook Marketplace) are `manual` on
purpose: they sit behind DataDome or forbid automation outright, and hammering
them from a server gets your IP blocked in minutes without returning anything.
The app folds your query into a real search URL and gives you a one-click link,
so the country still appears in your results — honestly labelled rather than
faked.

If you want them automated anyway, the supported route is to drive **your own
browser**, not a server: a Playwright script against your logged-in profile, or
a userscript that posts results back to `POST /api/search`. That keeps the
traffic indistinguishable from your normal browsing, which is the only version
of this that actually keeps working. It is out of scope here because it needs a
browser on your machine, not a headless container — but the engine registry in
`backend/ufeu/adapters/__init__.py` has an obvious place to plug one in.
