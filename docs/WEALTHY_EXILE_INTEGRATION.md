# Wealthy Exile Integration: Research and Proposal

**Status (2026-11-23): Option B is partly built.** The **Wealth** tab and overlay compute divine-per-hour from the two newest CSV exports in a user-chosen folder (`economy/wealthy_exile_csv.py`, `economy/wealth_rate.py`). There is no SQLite history yet, and the dashboard, stash and history pages are still to come. **The real CSV layout is still unconfirmed.** Headers are matched loosely (a quantity column plus a price or total column), so please send a real export to lock it down. A live, logged-in feed is **not** built; it needs Wealthy Exile's permission.

Tags: **[V]** verified (source and date), **[R]** recommendation, **[A]** assumption.

---

## 1. What Wealthy Exile is (research)

Observed on <https://wealthyexile.com> on 2026-11-23, using an already signed-in browser session. I recorded only **navigation and control labels**, not any account data. **[V]**

| Area | Observed |
|---|---|
| Top navigation | **Stash**, **Trade**, **Services**, **Strategies** (public), **Atlas**, **Economy**, **Dust**, **Go premium** (paid tier) |
| Stash page | **Wealth** toggle **Total / Hourly**, a time range (presets from "-10d" to "133d"), **Tabs & snapshots**, **Filters**, **Sync stash**, freshness text ("Synced an hour ago"), and an item table with columns **Name · Tab · Quantity · Price · Total** plus a **Sell** action |
| Stash "more actions" menu | **Edit synced tabs**, **Delete history**, **Export CSV** |
| Economy page | A table with league selection and a "Profit margin" column (details not inspected) |
| Platform | A Next.js app served by Vercel (`Server: Vercel`, `X-Powered-By: Next.js` response headers) |
| Account | Sign-in uses a pathofexile.com account [V third-party listing, <https://exile.party/tools/wealthy-exile>]. The same listing describes it as free, web-based and PoE1-only. **[A]** PoE2 support may have changed since. |

Documentation, API and export research:

- No public API, developer page or terms page was found. `/api`, `/terms`, `/privacy`, `/faq`, `/about`, `/tos` and `/legal` all return **404** [V, checked 2026-11-23].
- Web search found no documented API, no community client library and no integration on GitHub [V search, see RESEARCH_REPORT].
- The **only user-facing data-out mechanism is "Export CSV"** on the Stash page [V].
- **[A]** The CSV column set is unknown. The on-screen table suggests *Name, Tab, Quantity, Price, Total*, but this must be confirmed from a real export file.

What this means: **Wealthy Exile does not offer a public API.** Its own front-end obviously calls internal endpoints. Using those from our app would be reverse-engineering a private interface and would need the user's session. The brief rules that out, and so does this proposal.

---

## 2. Feasibility of each integration method

| Option | Method | Classification | Recommendation |
|---|---|---|---|
| **A1** | "Open in browser" deep links (`/stash`, `/strategies/public`, `/economy`, `/atlas`) from a Wealthy Exile card | ✅ **Officially supported**: it's ordinary website use | **Do it** (Small) |
| **A2** | Embedded browser view (QtWebEngine) of the site | ⚠️ **Technically possible**. No `X-Frame-Options` or CSP `frame-ancestors` header was seen on the homepage, but our process would then host the user's pathofexile.com login session. | **Don't.** It adds a ~150 MB+ runtime dependency **[A]**. It goes against RFC 8252, which says native apps should use the *system* browser for sign-in. It raises the question of whether we can read their cookies. It adds nothing over A1. |
| **B** | **Import the user's "Export CSV" file** | ✅ **Supported through a user-provided export** | **Primary integration path** |
| **C** | Dashboard built from imported snapshots | ✅ (derived from B) | **Do it**, built on B |
| **D** | Combine with poe.ninja (documented economy endpoints) and GGG's public Currency Exchange | ✅ under each source's usage rules [V] <https://poe.ninja/docs/api>, <https://www.pathofexile.com/developer/docs/reference> | **Do it**, labelling the source on every number |
| **X1** | Call Wealthy Exile's internal JSON endpoints | ❓ **Technically possible but undocumented** | **Not recommended.** Private interface, no permission, would break without notice. |
| **X2** | Reuse a session cookie copied from the browser | ❌ **Not recommended** (security and ToS) | **Will not implement** without your explicit approval *and* written permission from Wealthy Exile's developer. |
| **X3** | Sync the stash from GGG directly via OAuth (`account:stashes`) | ✅ officially supported in principle, but ⛔ **blocked**: GGG is *"currently unable to process new applications"* [V] | Revisit when registration reopens. It would replace B for users who want automatic syncing. |

**[R] Decision proposed:** **A1 + B + C + D.** Nothing else.

---

## 3. Data sources and their limits

| Source | What we get | Limits |
|---|---|---|
| **Wealthy Exile CSV** (user-exported) | Item rows for the user's synced tabs at export time. Expected: name, tab, quantity, unit price, total **[A]**. | Point-in-time only. One file is one snapshot. Prices are Wealthy Exile's valuation at export time. Freshness depends on when the user last pressed *Sync stash* on the site. The format may change without notice. |
| **poe.ninja economy** (documented) | Current exchange rates (`exchange/current/overview`), stash item prices (`stash/current/item/overview`), leagues list, sparklines | No SLA. ~5-minute HTTP cache and ~15-minute PoE1 refresh. They ask desktop apps to proxy through a backend. We have none, so we **must** cache aggressively (ETag), send a descriptive UA and refresh at most every 15 minutes [V]. |
| **GGG Currency Exchange** (public) | Hourly digests of exchange volume and stock per currency pair, across leagues | History arrives one hour at a time. Fetch at most hourly [V]. Its ids are metadata paths, which need mapping to names. |
| **User input** | Session start and stop, notes, strategy tags | Manual. |

---

## 4. Data model (local, normalised)

SQLite (stdlib `sqlite3`) in `%LOCALAPPDATA%\poe_qol\data.sqlite`:

```text
source(id, kind['wealthy_exile_csv'|'manual'|...], label)
snapshot(id, source_id, league, taken_at, imported_at, file_sha256, row_count,
         total_chaos, total_divine, divine_rate_chaos, note)
snapshot_item(snapshot_id, name, base_type?, tab, quantity, unit_price_chaos,
              total_chaos, category?)          -- category inferred via ninja name match
price_point(source['ninja'|'ggg_cx'], league, item_key, at, chaos_value, divine_value, volume?)
session(id, league, started_at, ended_at, start_snapshot_id?, end_snapshot_id?, maps?, note)
```

Rules:

- **Idempotent import.** The same `file_sha256` is never imported twice.
- **`taken_at`** comes from the user, defaulting to the file's modified time. The import dialog shows it and lets the user edit it.
- **Provenance is kept.** Every displayed value carries its source: "WE export" or "poe.ninja · 7 min ago".
- **Re-valuation is optional.** Snapshot values from the CSV are shown as exported. A separate "re-value at current ninja prices" column is labelled as an *estimate*.

## 5. Synchronisation and data management

| Requirement | Design |
|---|---|
| User-initiated | Import is an explicit action: drag and drop, "Import CSV…", or optionally a **watched folder** the user picks, which imports only files the user saves there. No unattended requests to Wealthy Exile, ever. |
| Last-updated timestamps | Every card has a freshness chip (snapshot time *and* import time). |
| Loading and error states | A progress row while importing. A per-row validation report ("3 rows skipped: missing quantity") with a downloadable error list. |
| Rate limiting | Not applicable to Wealthy Exile, since we make no requests. poe.ninja and GGG calls go through the shared `HttpClient` limiter. |
| Caching | ETag disk cache for ninja and GGG responses. A ≥ 15-minute minimum between ninja refreshes and 1 hour for GGG CX. |
| Unavailable services | Pages render from the last cache with a "stale" badge. CSV features need no network at all. |
| Local storage and history | SQLite as above. Snapshots can be deleted one at a time (with confirmation) and exported back to CSV. |
| Validation | Header sniffing (case and whitespace insensitive). Required columns: name + quantity + (price or total). Numbers are parsed locale-safely (`1,234.5`, `1 234,5`). Unknown columns are kept in a JSON side-field. Unrecognised headers produce a clear error that names the columns expected. |
| League selection | Inferred from the file name or header if present, otherwise picked in the import dialog, defaulting to the auto-detected league (roadmap G1). |

## 6. Proposed UI (Economy section)

Uses the design system in `UI_UX_PROPOSAL.md`. The Economy item in the sidebar opens tabs **Dashboard · Stash · History · Market**.

**Dashboard**

```
┌ Economy ─ Dashboard ─────────────────────── League: Mirage ▾ ─ [Import CSV] ┐
│ ┌ Total wealth ──┐ ┌ Divine rate ──┐ ┌ Change 24h ───┐ ┌ Last sync ──────┐ │
│ │ 412.6 div      │ │ 1 div = 186c  │ │ ▲ +18.2 div   │ │ WE export 2h ago│ │
│ │ ≈ 76 744 c     │ │ ninja · 6m    │ │ ▲ +4.6%       │ │ imported 1h ago │ │
│ └────────────────┘ └───────────────┘ └───────────────┘ └─────────────────┘ │
│ ┌ Wealth over time (snapshots) ─────────────────────────┐ ┌ By category ─┐ │
│ │      ▁▂▃▃▅▆▆▇█   [7d|30d|League]  [Total|Per hour]    │ │ Currency 62% │ │
│ └───────────────────────────────────────────────────────┘ │ Scarabs  14% │ │
│ ┌ Most valuable items ───────────────────────────────────┐ │ Fragments 9% │ │
│ │ Name            Tab      Qty   Unit     Total   Δ ninja │ │ Other    15% │ │
│ └────────────────────────────────────────────────────────┘ └──────────────┘ │
│ Source: Wealthy Exile export (values as exported) · prices: poe.ninja       │
└────────────────────────────────────────────────────────────────────────────┘
```

**Stash** holds the per-tab totals table, then the item table for the selected tab (filter, sort, search), a currency distribution chart and a quantity × value view.

**History** has a snapshot list (date, total, delta, rows, source), a line chart of total and per-category values, daily and weekly delta bars, a **session comparison** (pick two snapshots, or a session, to get duration, Δ wealth and chaos/h), and a profit-and-loss table.

**Market** has currency rates with sparklines (ninja), a watchlist, GGG Currency Exchange volume charts, and strategy ROI (roadmap E4). **Ninja and GGG figures are visually tagged so they can't be mistaken for Wealthy Exile data.**

Empty state: *"Export your stash from Wealthy Exile (Stash → ⋯ → Export CSV), then drop the file here."* It includes a button that opens `https://wealthyexile.com/stash` in the browser.

## 7. Authentication and security

| Concern | Position |
|---|---|
| Passwords | **Never requested or stored.** We never handle pathofexile.com or Wealthy Exile credentials. |
| Tokens and cookies | **None used.** Option B needs no authentication. Session-cookie approaches (X2) are rejected. |
| Hard-coded credentials | None. No API keys are needed for poe.ninja or GGG's public CX endpoint. |
| What is stored | Only the CSV rows the user imports, plus derived snapshots, in the local SQLite file. Optionally a hash of the imported file. |
| What is sent | No Wealthy Exile data ever leaves the machine. Price lookups send only **item names or league ids** to poe.ninja. |
| "Disconnect" | Settings → Integrations → Wealthy Exile → **Remove imported data**. It deletes the snapshots and items from SQLite, with confirmation and a count shown. There's no account link to revoke. |
| Disclosure | The Transparency page states: "Wealthy Exile: reads only CSV files you choose. Sends nothing." |
| Git hygiene | `*.csv` exports and `data.sqlite` live outside the repo. `.gitignore` also blocks `*.sqlite` and `exports/` as a safety net. |

## 8. Technical architecture

This is adapted to the existing package (TECHNICAL_AUDIT §5.1). Create only what is needed:

```
src/poe_qol/
  services/
    http.py              # shared HttpClient (UA, rate limit, ETag cache, worker)
    storage.py           # sqlite connection + migrations
  integrations/
    wealthy_exile/
      importer.py        # CSV sniffing/parsing/validation -> list[SnapshotRow]
      models.py          # dataclasses: Snapshot, SnapshotItem, ImportReport
      service.py         # import_file(), list_snapshots(), delete_snapshot(), totals()
    poe_ninja/
      client.py          # documented /poe1/api/economy/* endpoints only
      service.py         # rates(), item_prices(), leagues() with cache
    ggg_public/
      currency_exchange.py  # hourly CX digests
  pages/economy/
    dashboard.py  stash.py  history.py  market.py
```

- No `synchronizer.py` or `client.py` for Wealthy Exile, because there is no API to call. Adding them would be speculative.
- UI pages only talk to `service.py` objects passed in through `AppContext`. No HTTP or SQL in widgets.
- The branch's `economy/ninja.py` gets **ported** into `integrations/poe_ninja/` and switched to the documented endpoints.

Tests:

- Importer: fixtures for a minimal CSV, extra columns, locale numbers, a bad header, and duplicate imports.
- Service: totals and deltas.
- poe.ninja client: recorded JSON fixtures, with no live network in tests.

## 9. Implementation roadmap

| Step | Work | Effort | Needs from you |
|---|---|---|---|
| **W0** | **Send me one real Wealthy Exile CSV export.** You can scrub the item names, but keep the headers and a few rows. The importer must match the real format, not a guess. | — | **A sample CSV** |
| W1 | `services/storage.py` + `integrations/wealthy_exile/importer.py` + tests | Small–Med | — |
| W2 | Economy → Dashboard and Stash pages (read-only from snapshots) | Medium | — |
| W3 | poe.ninja client (documented endpoints) + divine-rate card + re-valuation column | Small–Med | — |
| W4 | History tab: charts, deltas, session comparison, P&L | Medium | — |
| W5 | Market tab: rates, watchlist, GGG CX volume | Medium | — |
| W6 | Optional watched-folder import, remove-data control, transparency entry | Small | Approve the watched-folder idea |

**Prerequisites:** roadmap P0.3 (`HttpClient`, paths) and P0.4 (shell) should land first. W1 does not depend on them and can start immediately after W0.

## 10. Questions to approve

1. Approve **A1 + B + C + D** as the integration approach, rejecting A2, X1 and X2?
2. Provide a **sample CSV export** (W0)?
3. Is a **watched folder** acceptable (W6), or should import stay manual-only?
