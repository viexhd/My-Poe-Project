# Feature Roadmap

Feature ids such as `A1` and `G4` refer to RESEARCH_REPORT §4. Compliance tags follow COMPLIANCE_REVIEW §3.

## Scoring criteria

| Criterion | Scale |
|---|---|
| **Value**: usefulness to regular players | 1–5 |
| **Effort** | Small (≤ 1 day) · Medium (2–5 days) · Large (1–3 weeks) · Very Large (> 3 weeks). Assumes one developer working part-time. **[A]** |
| **Maintenance**: churn across patches | Low · Med · High |
| **Uniqueness**: differentiates the app | 1 (common) – 3 (rare or unique) |
| **Compliance** | ✅ clear · ⚠️ conditional (with the condition stated) |
| **Dependencies** | APIs, services, libraries |

---

## Priority 0: Prerequisites (do these before any new feature)

These aren't features. They unblock everything else and remove risk.

| Item | Why | Effort |
|---|---|---|
| ✅ **P0.1 Compliance fixes. Done 2026-11-23:** `life_flask`, `inventory_dump` and `map_stash_dump` retired. GGG disclaimer added (Help → About). Product renamed to **Twice Corrupted**. | COMPLIANCE_REVIEW §2.1. The current defaults break GGG's macro rules. | Small |
| **P0.2 Rebase and merge the design branch** (`styles.py`, Flipper, Pricer), fixing its compliance issues during the merge. | Avoids two diverging UIs. TECHNICAL_AUDIT §3.15. | Medium |
| **P0.3 Foundations:** `core/paths.py` (user-data dir plus copy-migration), `ConfigStore` UTF-8 + atomic writes + validation, a shared `HttpClient` (honest UA, rate limiter, ETag cache, worker thread), F12 kept bound during calibration. | Fixes audit bugs §3.2, §3.3, §3.5–3.7, §3.10. Every later network feature reuses the HTTP client. | Medium |
| **P0.4 App shell:** sidebar plus page registry, header (league, profile, status pill), toasts. | UI_UX_PROPOSAL §4. New pages stop touching `MainWindow`. | Medium |

---

## Priority 1: Essential

| Id | Feature | Value | Effort | Maint. | Uniq. | Compliance | Dependencies |
|---|---|---|---|---|---|---|---|
| A1 | **Slot highlighter**, replacing the dump sweep and keeping calibration and profiles | 4 | Small | Low | 2 | ✅ | none (existing overlay) |
| B1 | **Map Search, compliant**: browser pre-fill path, honest-UA POST as fallback | 5 | Small–Med | Med (stat ids) | 2 | ⚠️ → ✅ via browser | trade site |
| G1 | **League auto-detect** | 4 | Small | Low | 1 | ✅ | poe.ninja leagues (documented) |
| E1 | **Divine ⇄ chaos widget** with a freshness label | 5 | Small | Low | 1 | ✅ | poe.ninja exchange overview |
| B2 | **Bulk / exchange ratio calculator** | 4 | Small | Low | 2 | ✅ | E1 rates (optional) |
| F1 | **Hotkeys page**: key capture, conflicts, scopes, F12 always on | 4 | Medium | Low | 1 | ✅ | none |
| G2 | **Transparency page + per-feature compliance badges** | 3 | Small | Low | **3** | ✅ | none |
| C1 | **Map mod check** from a clipboard read on hotkey, with a build profile | 5 | Medium | Med | 2 | ✅ one read per key press | `map_mods.yaml` |

## Priority 2: High-value additions

| Id | Feature | Value | Effort | Maint. | Uniq. | Compliance | Dependencies |
|---|---|---|---|---|---|---|---|
| E2 | **Economy dashboard** fed by **Wealthy Exile CSV import** | 5 | Medium–Large | Med (CSV format may change) | 2 | ✅ | user CSV, poe.ninja, SQLite (stdlib) |
| E3 | **Profit-per-hour session ledger** | 4 | Medium | Low | 2 | ✅ | E2 snapshots or manual entry |
| C5 | **Session tracker** (Client.txt) | 4 | Medium | Med (log format) | 2 | ✅ with opt-in, user aware | Client.txt path |
| C2 | **Map Search selection → in-game regex** | 4 | Medium | Med | **3** | ✅ | regex snippets in `map_mods.yaml` |
| A2 | **Stash search-string library**, one paste per key press | 4 | Small | Low | 1 | ⚠️ one paste per press | none |
| B5 | **Price check** (rework of the branch Pricer): explicit hotkey, ignores non-item text | 5 | Medium | High | 1 | ⚠️ internal trade API; prefer the browser | trade site |
| — | **Flipper**, moved to documented poe.ninja endpoints with ETag | 3 | Small | Med | 2 | ✅ | poe.ninja |
| G4 | **Stale-stat doctor** for `map_mods.yaml` | 3 | Small–Med | Low | **3** | ✅ | ninja `tradeInfo` or bundled data |
| C4 / E4 | **Map sustain + strategy ROI calculators** | 3 | Small / Med | Low | 2 | ✅ | E1 prices |
| F4 / F5 / F7 | **Notes, checklists, command palette** | 3 | Small each | Low | 1 | ✅ | none |

## Priority 3: Advanced

| Id | Feature | Value | Effort | Maint. | Uniq. | Compliance | Dependencies |
|---|---|---|---|---|---|---|---|
| D1 | **PoB import → build card** (offline decode) | 4 | Medium | Med (PoB XML) | 2 | ✅ | stdlib zlib/xml |
| D2 | **Build → map-mod rules** | 4 | Medium | Med | **3** | ✅ | D1, C1 |
| E6 | **Official Currency Exchange history** (GGG public endpoint, hourly) | 3 | Medium | Low | **3** | ✅ | GGG public API |
| E5 / F8 | **Price watchlist + notification centre** | 3 | Medium | Low | 1 | ✅ (≥ 15 min refresh) | poe.ninja |
| B3 / G21 | **Trade ledger + personal price history** | 3 | Medium | Low | 2 | ✅ | SQLite |
| F6 | **Reference overlays** (user images) | 3 | Medium | Low | 1 | ✅ | none |
| B4 | **Whisper inbox** (read-only; one command per click) | 4 | Medium–Large | Med | 1 | ⚠️ never auto-act | Client.txt |
| G8 | **Div-card set board** | 3 | Medium | Med | 2 | ✅ | E2 CSV, ninja |
| — | **Packaging** (PyInstaller one-folder), **update check**, **CI** | 4 (indirect) | Medium | Low | — | ✅ | PyInstaller (dev-only) |

## Priority 4: Experimental

| Id | Feature | Why experimental |
|---|---|---|
| G6 | Smart Quick-Action router | The UX needs validating first. It depends on C1, B2 and B5 existing. |
| G18 | Build comparison (two PoB codes) | Large. Its value depends on what PoB's XML exposes. |
| D3 | Gem / leveling checklist | Needs vendor data upkeep every league. Linking to exile-leveling may be enough. |
| E7 | Crafting cost estimator | The probabilities have to come from somewhere; Craft of Exile does it better. |
| G19 | Stream mini-overlay | Niche. |
| — | GGG OAuth stash sync | **Blocked:** GGG says it is *"currently unable to process new applications"* [V] <https://www.pathofexile.com/developer/docs>. Revisit when registration reopens. |
| — | Flask-duration *visual* timer | ❓ Compliance is uncertain (COMPLIANCE_REVIEW §3.3). **Not recommended.** |

## Excluded (compliance)

| Feature | Reason |
|---|---|
| Life-flask auto-press (existing) | Timer invocation (GGG macro rule 1) |
| Inventory / map-stash bulk Ctrl-click (existing) | More than one action per key press (rule 3) |
| Multi-flask, "craft until", one-key multi-craft, chained chat commands | Rule 3 |
| Threshold-triggered actions (auto-logout, auto-guard) | Rule 1, and the community guide's explicit example |
| Auto-invite, auto-accept, auto-reply to whispers | Automated interaction with other players |
| Screen-OCR loot or map tracking | Overlay rule (one read per key press) plus brittleness |
| Writing loot-filter files, reading game config files | "Interact with the game or game files" (ToS 7b/7c/7i) |
| POESESSID cookie stash sync | Unsupported auth. Security risk. |
| Calling Wealthy Exile's private endpoints | Not documented. See `WEALTHY_EXILE_INTEGRATION.md`. |
| Spoofed browser UA | Breaks GGG's UA requirement. Gets around Cloudflare. |

---

## Suggested implementation order

Each milestone ends in a shippable, tested build.

| Milestone | Contents | Exit criteria |
|---|---|---|
| **M0: Safe baseline** (≈ 1 week) | P0.1, P0.3, plus G2 (transparency) | No non-compliant feature is enabled by default. `HttpClient` exists. Tests green. User data lives in `%APPDATA%` with migration. |
| **M1: One app** (≈ 1–2 weeks) | P0.2 (merge the branch), P0.4 (shell), F1 (Hotkeys page) | A themed sidebar app containing every existing page. No inline styles. |
| **M2: Daily drivers** (≈ 2 weeks) | A1, B1, G1, E1, B2, C1 | A player can map all session long using only compliant features. |
| **M3: Economy** (≈ 2–3 weeks) | E2 (Wealthy Exile CSV), E3, Flipper rework, C4/E4 | Wealth over time and profit per hour working from user-exported CSVs. |
| **M4: Mapping intelligence** (≈ 2 weeks) | C5, C2, A2, G4, F4/F5/F7 | Session history, regex from Map Search, stat doctor. |
| **M5: Planning and polish** | D1, D2, E6, E5/F8, packaging, CI, update check | Installer build. Release notes. |
| **Later** | P3 remainder, P4 experiments | |

---

## Final recommendations (Phase 8)

### 1. What are the biggest weaknesses of the current application?

1. **The headline features break GGG's published macro rules.** That's the timer flask and the 60-click sweep, and it contradicts the project's own non-negotiable requirement.
2. **There is no product shell.** Tabs are hard-coded, styles are inline, internal ids are shown as labels, and the theme is mixed light and dark.
3. **Fragile foundations.** Paths depend on the working directory, user data sits in the source tree, writes are non-atomic and not UTF-8, network calls run on the UI thread with retry storms, and the User-Agent is spoofed.
4. **Split development.** About 3,300 lines (theme, Flipper, Pricer) sit on an unmerged branch, and 5 of 13 tests on `main` were failing.

### 2. Which design ideas should I adopt?

- Summoned in-game panels plus a planning-oriented main window (APT, Sidekick, Exile-UI).
- A transparency notice and **per-feature compliance badges** (Exile-UI's notice, taken further).
- Freshness labels and a visible rate-limit state (Wealthy Exile, APT).
- Snapshot-first economy views with income per hour as the headline (Exilence, Wealthy Exile).
- Shared overlay primitives (PoE Overlay CE's stash grid).
- Lean on the game's own search box through regex (poe.re).

### 3. What are the 10 most valuable features to add?

C1 Map mod check · E2 Economy dashboard (WE CSV) · B1 compliant Map Search · E1 Div ⇄ chaos widget · A1 Slot highlighter · E3 Profit per hour · C5 Session tracker · B2 Bulk ratio calc · C2 Map Search → in-game regex · B5 Price check (compliant rework).

### 4. Which features could make the app stand out?

- **Per-feature compliance badges and a transparency page (G2).** I found no other tool that does this per feature **[A]**.
- **One mod selection driving both trade search and in-stash regex (C2).**
- **Build-aware map checks (D1 → D2 → C1).**
- **Official GGG Currency Exchange history (E6).** It's auth-free and rarely used by desktop tools **[A]**.
- **Stale-stat doctor (G4)** and the **patch-day safety switch (G11)**.

### 5. What's easy to build but high value?

League auto-detect (G1), Div ⇄ chaos widget (E1), bulk ratio calculator (B2), slot highlighter (A1, since the overlay already exists), transparency page (G2), search-string library (A2) and preset share codes (G15).

### 6. What should I remove, replace or refactor?

| Item | Decision |
|---|---|
| Life-flask timer | **Remove.** No compliant equivalent sends input. |
| Inventory / map-stash dump sweep | **Replace** with the slot highlighter (A1). |
| Focus-clicks before a sweep | **Remove** along with the sweep. |
| Spoofed UA + 16× retry POST | **Replace** with `HttpClient` (honest UA, limiter, no auto-retry) and the browser pre-fill path. |
| Passive clipboard watcher (branch) | **Replace** with an explicit hotkey. |
| Old poe.ninja route (branch) | **Replace** with the documented `/poe1/api/economy/...` endpoints. |
| v1 regex trade pipeline, `TradeWidget` | **Removed** in this cleanup. |
| `config/user.yaml`, slot profiles and logs in the source tree | **Move** to `%APPDATA%` / `%LOCALAPPDATA%` (copy-migration). |
| Piplup mascot icon (branch) | **Replace** with an original mark. |
| Root-level AHK/C++ scripts | **Archived** to `legacy/` in this cleanup. Delete once you're comfortable. |

### 7. What should the finished app look like?

A dark, gold-accented, **tray-resident** companion:

- **Home** shows the league, divine rate, wealth, session and alerts at a glance.
- **In-game help** comes from one or two hotkeys that summon small context panels: map verdict, bulk maths, price check. Each panel does one manual action at most.
- An **Economy** section turns Wealthy Exile exports and poe.ninja prices into income-per-hour and wealth-over-league charts, with clear freshness labels.
- **Planning tools** (build card, checklists, notes, calculators) work offline.
- Every page says what it reads and sends. Nothing runs on a timer against the game.

### 8. What's the best development order?

**M0 Safe baseline → M1 One app (merge the branch, shell) → M2 Daily drivers → M3 Economy → M4 Mapping intelligence → M5 Planning and polish.**

Compliance and foundations come first. Without them every feature inherits the risk and the path, threading and UA bugs.
