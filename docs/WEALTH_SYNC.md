# Wealth: stash sync from your Path of Exile account

The **Wealth** tab works like Wealthy Exile's stash page. You connect your Path of Exile account once, and the app then reads your stash tabs through GGG's official API, values them with poe.ninja prices and keeps a local history. It shows how much your wealth changed over **any time range you pick**. Automatic sync runs **every hour** by default. On Wealthy Exile, automatic syncing is a premium feature.

## Before it can work: GGG must register the app

GGG only lets **registered** applications use account sign-in (<https://www.pathofexile.com/developer/docs>; apply by email to `oauth@grindinggear.com`). Until Twice Corrupted has a client ID, the **Connect account** button stays disabled and the tab says so.

- Register a **public** client. That is the desktop-app type: it has no client secret and uses PKCE.
- Redirect URI: `http://127.0.0.1` (loopback; the app picks a free port by default). If GGG wants one exact port, register `http://127.0.0.1:<port>/oauth/callback` and set `wealth.oauth.redirect_port` to that port.
- Scopes: `account:profile`, `account:leagues` and `account:stashes`, and nothing else.
- Put the client ID in `poe_qol/config/default.yaml` → `wealth.oauth.client_id`, and a contact email in `wealth.oauth.contact`. GGG wants the contact in every request's User-Agent: `OAuth <client_id>/<version> (contact: <email>)`. A public client ID isn't a secret, so it can ship with the release. Users can also paste one under **GGG app registration** on the tab.

> **Status:** `COMPLIANCE_REVIEW.md` recorded on 2026-11-23 that GGG was *"currently unable to process new applications"*. Check the developer page for the current state before applying. Everything below is built and tested against GGG's documented API with recorded-shape fixtures. It has **not** been run against the live API yet, because that needs the client ID.

## Using it

1. **Connect account.** Your browser opens pathofexile.com's own consent page (the same screen Wealthy Exile shows). Log in there and press **Authorize**. The app never sees your password.
2. The first sync starts right away. **Sync now** runs another; manual syncs have a 60 s cooldown.
3. **Automatic sync** (on by default) runs every 1 h while the app is open. You can pick 15 min, 30 min, 1 h, 2 h, 4 h or 6 h.
4. **Range:** last 1 h / 3 h / 6 h / 12 h / 24 h / 3 d / 7 d / 14 d / 30 d, all history, or a custom *from → to*.
5. Cards: **Per hour** (div/h and c/h), **Change** (div, chaos and %), **Net worth**, and **Last sync** (with the time of the next one).
6. Chart: **Total** (net worth at each sync) or **Hourly** (gain or loss per hour between syncs).
7. **Items:** name, tab, quantity, price, total, Δ quantity and Δ value over the range. You can filter by name, and "Only changed" hides items that didn't move.
8. **Synced tabs…** is Wealthy Exile's "Edit synced tabs": all tabs, or just the ones you tick, per league.
9. **Import Wealthy Exile CSV…** adds old exports to the same history. **Delete history…** wipes a league's snapshots.
10. The **per-hour overlay** shows the selected range's div/h over the game.

### How the change is calculated

For the range *[start, end]* the tab compares:

- the **start snapshot**: the newest sync **at or before** *start*. "Last 24 h" means "compared with your stash as it was 24 h ago". If no sync is that old, it uses the first sync inside the range.
- the **end snapshot**: the newest sync at or before *end*.

*Per hour* is the change divided by the real time between those two syncs. Both ends are converted to divines with **one** rate: the end snapshot's poe.ninja Divine Orb price, or your override. That way a moving divine price isn't counted as profit or loss.

### What gets priced

Values come from poe.ninja, cached for 30 min:

| Item | How it's matched |
|---|---|
| Currency, fragments, scarabs, essences, div cards, fossils, oils, omens, tattoos, etc. | Exchange overview by name × stack size |
| Uniques | Name and base; 5- and 6-links priced separately |
| Maps | Base and tier |
| Gems | Name, level, quality and corrupted |

Rares, magic gear and anything poe.ninja doesn't list count as **unpriced**. They are shown as a count, not valued, as on Wealthy Exile.

## Data, privacy and limits

- **Requests:** pathofexile.com (sign-in, your stash) and poe.ninja (prices, by league and item type only). Nothing else is contacted.
- **Stored locally:** `%APPDATA%\twice-corrupted\`
  - `wealth.sqlite`: snapshots, aggregated per tab and item
  - `ggg_token.bin`: the sign-in token, **encrypted with Windows DPAPI**, so only your Windows user can read it
- **Disconnect** deletes the token and revokes it at pathofexile.com. Your history stays until you delete it.
- **Rate limits:** the client reads GGG's `X-Rate-Limit-*` headers, keeps one request of headroom, waits instead of exceeding a limit, and honours `Retry-After`. A big account can take a few minutes per sync; the progress bar shows each tab.
- **Expired sign-in:** when the sign-in expires and can't be refreshed, auto-sync stops and the tab asks you to connect again. A failed sync is retried no sooner than 10 min later.
- **Why not the Public Stash Tab API?** The public stash river (`service:psapi`) is a firehose of every player's *public* trade tabs. Only confidential server apps can use it, and it never contains your private tabs. `account:stashes` is the API built for reading your own stash, and Wealthy Exile uses it too.
- **Not included yet:** character inventories (`account:characters`) and guild stash (`account:guild:stashes`). Wealthy Exile asks for both. Adding either means one more scope in `ggg/oauth.py` and a fetch in `economy/stash_sync.py`.

## Code map

| File | Role |
|---|---|
| `ggg/oauth.py` | PKCE, authorize URL, loopback receiver, token exchange/refresh/revoke |
| `ggg/token_store.py` | DPAPI-encrypted token file |
| `ggg/ratelimit.py` | Header-driven rate limiter |
| `ggg/api.py` | `/profile`, `/account/leagues`, `/stash/<league>[/<id>[/<sub>]]` |
| `economy/pricing.py` | poe.ninja price book |
| `economy/stash_valuation.py` | GGG item → priced line |
| `economy/stash_sync.py` | One sync: list → fetch → price → save; CSV import |
| `economy/wealth_store.py` | SQLite history |
| `economy/wealth_history.py` | Range selection, deltas, per-item changes, hourly series |
| `economy/wealth_service.py` | Glue the UI calls |
| `ui/wealth_widget.py` | The tab |
| `ui/wealth_chart.py` | The Total/Hourly chart |

Tests are in `tests/test_wealth_sync.py` and need no network.
