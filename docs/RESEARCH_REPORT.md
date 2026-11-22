# Research Report: Path of Exile Companion Tools

Research date: **2026-11-23**. Tags: **[V]** verified against the cited source, **[R]** recommendation, **[A]** assumption or unverified.

Method:

- Read official GGG and poe.ninja documentation pages directly.
- Pulled GitHub metadata and READMEs through the GitHub API, and read source files where a claim depended on implementation (for example APT's rate limiter).
- Used web search for websites I couldn't inspect in depth.
- Opened Wealthy Exile's public navigation in a browser.

I did **not** install or run third-party desktop apps, so statements about their look and feel come from their READMEs or wikis, and are marked as such.

---

## 1. Landscape at a glance

### 1.1 Desktop apps and overlays

GitHub data was fetched 2026-11-23. Stars are approximate.

| Application | Main purpose | Best features | Best design elements | Ideas worth adopting |
|---|---|---|---|---|
| **Awakened PoE Trade** · [repo](https://github.com/SnosMe/awakened-poe-trade) · [site](https://snosme.github.io/awakened-poe-trade/quick-start) · MIT, TypeScript (Electron + Vue), ~2.6k★, active | Price checking | Hotkey price check parses the game's copied item text. Uses trade search, fetch and bulk exchange. Official trade links. [V README / quick-start] | A **visible rate-limit state** component (`RateLimiterState.vue`). Conservative client limiter (1 request per 5 s) that **re-tunes from server `X-Rate-Limit-*` headers** (`trade/common.ts`) [V source]. | Copy the rate-limit design wholesale. Show "requests left / cooldown" in the UI so users understand delays. |
| **Exiled Exchange 2** · [repo](https://github.com/Kvan7/Exiled-Exchange-2) · ~1.2k★ | APT fork for PoE2 | Same as APT, PoE2 data. Migration path for APT configs. [V README] | Proves a clean data/config separation (`%APPDATA%\…\apt-data\config.json`) [V README]. | Keep user config in `%APPDATA%`, never in the install folder. |
| **Sidekick** · [repo](https://github.com/Sidekick-Poe/Sidekick) · C#, ~0.5k★, active | Trade companion for PoE1 and PoE2 | Price check, **dangerous map modifier check**, wealth view, chat commands [V README / winget]. | The **same Blazor UI runs as a desktop app (Avalonia WebView) or as a web app** [V README]. Closing the window hides it to the tray [V]. | A dangerous-map-mod check from the clipboard. Tray-resident lifecycle. Note that web-based dev mode speeds UI iteration. |
| **PoE Overlay CE** · [repo](https://github.com/PoE-Overlay-Community/PoE-Overlay-Community-Fork) · TypeScript (Electron + Angular), ~0.5k★, active | General overlay | Item evaluation via official trade. **Stash grid overlay** for normal and quad tabs. **Trade Companion** whisper cards with quick actions. Vendor-recipe set highlighting. Hotkeyed chat commands (`/hideout` on F5). Bind websites to hotkeys [V README]. | Stated core aspect: *"blend in with the game"* [V]. Grid overlay is a *shared primitive* reused by trade and recipe features [V]. | Make our existing slot overlay a **shared primitive** (highlight N cells) that trade, recipe and map-sorting helpers all reuse. |
| **Exile-UI** (formerly Lailloken UI) · [repo](https://github.com/Lailloken/Exile-UI) · AutoHotkey, ~1.4k★, active | Minimalist QoL overlay toolkit | Item-info tooltip, map-info panel, **Map-Tracker (CSV export)**, Stash-Ninja price overlay, search-strings menu, chat macros and chat wheels, cheat-sheet overlays, notepad, countdown/stopwatch, Vaal Street exchange logging [V README]. | *"Ease-of-use, minimalist design, **low hotkey requirements**"* [V]. A **Transparency Notice** that lists exactly what the tool reads (Client.txt, screen-on-keypress) and sends (copy key presses, chat commands) [V]. Context-sensitive behaviour on key press [V]. | ① The transparency panel. ② Few hotkeys with context instead of one hotkey per feature. ③ Search-string menu. ④ Map tracker CSV export. |
| **Poe Lurker** · [repo](https://github.com/C1rdec/Poe-Lurker) · C# (.NET 8, MahApps), ~0.6k★ | Trade manager | Whisper and offer management overlay. Patreon "Pro" tier. Signed builds via SignPath [V README]. | MahApps "modern UI" [V]. | Free OSS code signing reduces SmartScreen friction. |
| **Exilence CE** · [repo](https://github.com/exilence-ce/exilence-ce) · TypeScript (Electron/React/mobx + .NET Core 3.1), ~170★ | Net-worth tracking | Values character, inventory and stash. **Summarised over time with hourly income**. Group net worth with friends [V README]. | Snapshots over time leading to per-hour income is the core loop [V]. | Our economy page should be snapshot-centred, not item-centred. |
| **Exile Diary Reborn** · [repo](https://github.com/Qt-dev/exile-diary) (original [briansd9/exile-diary](https://github.com/briansd9/exile-diary)) · TypeScript | Map run tracker | Loot per map and its value, map IIR/IIQ via **screenshot OCR**, kill counts, combining log-reading, screenshots, GGG API and timers [V README]. | Shows the GGG notice [V]. | Log-reading for sessions is valuable. **Avoid the OCR/screenshot path** (brittle, and compliance-sensitive). |
| **Chaos Recipe Enhancer** · [repo](https://github.com/ChaosRecipeEnhancer/ChaosRecipeEnhancer) · C# WPF, GPL-3.0, ~0.5k★ | Vendor recipe sets | Stash query (via **OAuth**, replacing POESESSID), set tracker overlay, **stash item pick-order highlighting**, offline loot-filter manipulation, sound on set complete [V README]. | GGG disclaimer at the top of the README [V]. "2-click OAuth" onboarding [V]. | The highlight-pick-order idea maps directly onto our slot overlay (compliant: the user clicks). |
| **Path of Building Community** · [repo](https://github.com/PathOfBuildingCommunity/PathOfBuilding) · Lua, ~5.5k★ | Offline build planner | The standard build share code [V]. | Fully offline, so it is dependable. | Accept PoB codes as an *input* (decode offline) for build-aware features. |
| **exile-leveling** · [repo](https://github.com/heartofphos/exile-leveling) | Leveling guide | Generates route guides; Exile-UI consumes them [V Exile-UI README]. | | Link out; don't rebuild it. |

### 1.2 Websites and online utilities

| Site | Main purpose | Best features | Best design elements | Ideas worth adopting |
|---|---|---|---|---|
| **poe.ninja** · <https://poe.ninja> · [API docs](https://poe.ninja/docs/api) | Economy and build stats | Economy overviews (exchange plus stash items, with `sparkline`, `volumePrimaryValue`, `tradeFilter` for trade links) [V API docs]. Builds and atlas trees [V nav]. | Sparklines in dense tables. Clear *supported vs internal* API policy [V]. | Use the **documented economy endpoints** only. Reuse the `tradeFilter` field to build "open on trade" links. |
| **Wealthy Exile** · <https://wealthyexile.com> | Stash wealth analytics | Observed in nav (2026-11-23): **Stash** (Total/Hourly toggle, time range, "Tabs & snapshots", Filters, "Sync stash", "Synced an hour ago", **Export CSV**, Delete history), Trade, Services, **Strategies** (public farming strategies), Atlas, Economy, Dust, Premium [V]. Requires a pathofexile.com login [V via [exile.party](https://exile.party/tools/wealthy-exile)]. | A **freshness label** ("Synced an hour ago"). A Total vs Hourly toggle. Snapshot timeline. | See `WEALTHY_EXILE_INTEGRATION.md`. The CSV export is the integration path. |
| **PoeStash** · <https://www.poestash.com> | Wealth tracker | Wealth history, currency per hour [V search]. | | Proves there is demand for income-per-hour. |
| **FilterBlade** · <https://www.filterblade.xyz> | Loot-filter editor (NeverSink based) | Strictness levels, per-character adjustment, save via PoE account [V search]. | A strictness *slider* simplifies a huge rule set. | Use the progressive-disclosure pattern (one slider, then "advanced"). |
| **Craft of Exile** · <https://www.craftofexile.com> | Crafting simulator | Mod weights, probabilities, cost-effective routes [V search]. | | Link out with the item base pre-selected (via clipboard). Don't rebuild it. |
| **PoEDB** · <https://poedb.tw> | Game data wiki | Mods, bases, tools list [V search]. | | Link target for "what is this mod". |
| **PoE Antiquary** · <https://poe-antiquary.xyz> | Past-league prices | Historical prices indexed from poe.ninja [V search]. | | A "last league at this point" comparison link. |
| **PoE Planner** · <https://poeplanner.com> | Online tree and atlas planner | Passive and atlas tree planning [V search]. | | Link out. |
| **Official Trade** · <https://www.pathofexile.com/trade> | Item search and bulk exchange | Canonical search UI. | | Prefer opening it pre-filled over scraping it (see COMPLIANCE_REVIEW §3.3). |
| **poe.re / poe2.re** · <https://poe.re> · [repo](https://github.com/veiset/poe-vendor-string) | In-game search regex builder | Vendor, map mods, Heist, Bestiary, scarabs, tattoos and more. *"No false positives … query shortening"* [V README]. | One page per game system. Output is a single copyable string. | **The stash regex is the compliant counterpart to automation.** The game itself highlights matching items. |
| **NeverSink filter** · [repo](https://github.com/NeverSinkDev/NeverSink-Filter) | Base loot filter | Strictness tiers [V README]. | | |

### 1.3 Smaller and independent projects worth studying

| Project | Why it's interesting |
|---|---|
| [darvid/stashvision](https://github.com/darvid/stashvision) | AHK overlay that highlights chaos-recipe items. Works only in windowed borderless [V search]. The same constraint applies to our Qt overlay. |
| [Gloorf/poewatcher](https://github.com/Gloorf/poewatcher) | A **Python** Client.txt scanner with a map recorder that exports CSV [V search]. Proves the approach in our language. |
| [shonya3/divicards](https://github.com/shonya3/divicards) | Desktop app for divination card stacks [V search]. |
| [mattsre/poeledger.com](https://github.com/mattsre/poeledger.com) | Long-term price history built from the public stash stream [V search]. Shows the cost of building history yourself. |
| [poewiki: list of related websites](https://www.poewiki.net/wiki/List_of_Path_of_Exile_related_websites) | Maintained index of the ecosystem. |

---

## 2. Why the successful tools work (design lessons)

1. **They wait to be summoned and get out of the way.** APT, Sidekick and Exile-UI are built around a hotkey that opens a panel near the cursor and closes it again. Exile-UI explicitly optimises for *low hotkey requirements* [V]. While you're playing, attention is the scarcest resource, so the "home" for in-game features is a transient panel, not a dashboard. **[R]** Keep the main window for planning and setup. In-game features become small summoned panels.
2. **Context beats configuration.** Exile-UI checks what's open on key press and changes behaviour [V]. One "smart" hotkey is better than ten. **[R]** Have one *Quick Action* hotkey that inspects the clipboard (map → mod check, currency → exchange calc, gear → open trade or wiki).
3. **Trust comes from saying exactly what the tool does.** Exile-UI's Transparency Notice and CRE's and Exile Diary's GGG disclaimers [V] address a real user fear: bans. **[R]** Add a Transparency page and per-feature compliance badges (see UI_UX_PROPOSAL). Nothing else in the ecosystem shows *per-feature* badges as far as I found **[A]**, so this is a differentiator.
4. **Show data freshness and limits.** Wealthy Exile's "Synced an hour ago" [V] and APT's rate-limiter state [V] prevent confusion when numbers are stale or requests are queued.
5. **Snapshot first, item second.** Exilence and Wealthy Exile make a time series of total wealth the core view, with item tables underneath [V]. Hourly income is the headline metric.
6. **Shared primitives.** PoE Overlay CE's stash grid overlay serves trade, recipes and highlighting [V]. Our `SlotSelector` + `_OverlayWindow` is already that primitive, but it is welded to the dump macro.
7. **Lean on the game's own features.** poe.re produces strings for the game's search box [V]. The game does the highlighting, which makes it the most compliant "automation" there is.
8. **Separate the UI from the host.** Sidekick's Blazor UI runs in a browser for development [V]. For us, keeping pages free of global hotkey and Win32 assumptions keeps them testable offscreen.

---

## 3. What users repeatedly do outside the game (pain points)

These were collected from the feature sets above, because each feature exists to solve a pain point. My own gameplay observations are marked **[A]**.

- Looking up whether a map mod bricks their build, then re-checking on every map.
- Converting between divine and chaos (and exalted in PoE2) when pricing or buying in bulk, and doing fraction maths for the currency exchange.
- Working out whether a strategy is profitable: costs in (scarabs, maps, other atlas inputs) against value out, per hour.
- Tracking wealth across a league, and whether today was better than yesterday.
- Writing and remembering stash or vendor regex strings.
- Remembering league-start progression steps and checklist items **[A]**.
- Finding the right external site for a question (wiki, PoEDB, Craft of Exile, ninja).
- Managing trade whispers while mapping (Lurker, PoE Overlay CE [V]).
- Keeping notes per build, per boss and per map.

---

## 4. Feature discovery

Every idea follows the same template. Compliance uses COMPLIANCE_REVIEW §3: ✅ clear, ⚠️ conditional, ❓ uncertain, ❌ excluded. Complexity is S/M/L/XL.

### A. Inventory and stash

| # | Feature | Problem → how it works | Why useful | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|
| A1 | **Slot highlighter** (replaces the dump sweep) | Bulk Ctrl-clicking is error-prone. The overlay highlights the chosen slots, and the user clicks. An "N left" counter and an optional "next" highlight help. | Keeps calibration and profiles, removes the ban risk. | Re-use `_OverlayWindow`. Add a pulse on the next cell. | ✅ | S |
| A2 | **Stash search-string library** | Players re-type regex strings. Save named strings, and one hotkey pastes the chosen string into the focused search box. | Fast and compliant highlighting. | `QClipboard.setText` + a *single* paste (Ctrl+V) on hotkey, or copy-only mode. | ⚠️ one paste per press | S |
| A3 | **Stash tab layout notes** | "Where did I put X?" Map item categories to tab names, shown as a reference panel. | Light, organisational. | YAML/SQLite table plus a page. | ✅ | S |
| A4 | **Recipe set planner** (manual) | Counting sets. The user enters counts, or imports from a Wealthy Exile CSV; the app shows what's missing per slot. | CRE-like value without OAuth. | CSV import then a set calculator. | ✅ | M |

### B. Trading

| # | Feature | Problem → how it works | Why useful | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|
| B1 | **Map Search, made compliant** | Existing feature. Open the browser pre-filled. Honest UA and a rate limiter if the POST is kept. | Keeps the best existing feature. | `HttpClient` service, worker thread. | ⚠️ → ✅ via browser path | S–M |
| B2 | **Bulk / exchange ratio calculator** | "Seller gives 7 for 1.3 div. Is that better than 20:4?" Normalise to per-unit and per-div, then suggest the nearest whole-number ratio. | Constant pain point in bulk trading. | Pure functions + table. | ✅ | S |
| B3 | **Trade notebook** | No memory of what you paid or sold. A manual or quick-add ledger with realised profit. | Personal records and taxes on time **[A]**. | SQLite table + page. | ✅ | M |
| B4 | **Whisper inbox** (read-only) | Whispers get lost while mapping. Parse `Client.txt` for incoming trade whispers and show cards. Buttons *copy* a reply; an optional single `/invite` is one command per click. | PoE Lurker and PoE Overlay CE proved demand [V]. | Log tailer + parser + toast. | ⚠️ one command per click, no auto-actions | M–L |
| B5 | **Clipboard price check** (branch Pricer, made compliant) | Explicit hotkey, one clipboard read per press, ignores non-item text. | Core feature of APT and Sidekick. | Rework the branch's `pricer/`. | ⚠️ internal trade API (see §3.3) | M |

### C. Mapping

| # | Feature | Problem → how it works | Why useful | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|
| C1 | **Map mod check** (clipboard) | Hover a map, press Ctrl+C (the game's own copy) then the app hotkey. The app reads the clipboard once and flags mods against the *active build profile*, with a red/amber/green verdict. | Sidekick ships this [V]. We can reuse `map_mods.yaml` categories and presets. | Parser for map item text + profile rules + small panel. | ✅ | M |
| C2 | **Map Search selection → in-game regex** | The same "excluded mods" selection that drives trade search can also produce a stash search string to highlight bad maps in your own stash. | One mental model for two tasks. **Unique.** | Add short `regex` snippets per mod in `map_mods.yaml`. | ✅ | M |
| C3 | **Dangerous mod reference** | A searchable database of map mods with build tags ("bricks RF", "bad for minions"). | Learning tool. | `map_mods.yaml` plus a richer schema. | ✅ | S |
| C4 | **Map sustain calculator** | Maps in and maps out per tier, scarab cost → sustain verdict. | Mid-league planning. | Pure maths page. | ✅ | S |
| C5 | **Session tracker** (Client.txt) | Detect area transitions, then count maps, time per map and hideout idle time, with start/stop on hotkey. | Exile-UI's map tracker shows demand [V]. | `ClientTxtTailer` + SQLite + charts. | ✅ (log reading, user aware) | M |
| C6 | **Map prep checklist** | Forgotten scarabs or settings. A per-strategy checklist you tick before a run. | Cheap and helpful. | Checklist widget. | ✅ | S |

### D. Character and build

| # | Feature | Problem → how it works | Why useful | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|
| D1 | **PoB code import → build card** | Decode the PoB code offline (base64 + zlib XML), then show the main skill, key items, resist summary and gem list. | A build dashboard with no account access. | `zlib` + `xml.etree` (stdlib). | ✅ | M |
| D2 | **Build profile → map mod rules** | Derive the dangerous-mod set from the build (RF → no regen). | Personalised C1/C2. | Rules table keyed on PoB skills and keystones. | ✅ | M (experimental) |
| D3 | **Gem / leveling checklist** | Gems to buy per act from the PoB import, plus a link to exile-leveling. | Leveling QoL. | Needs gem vendor data, which is a maintenance cost. | ✅ | L |
| D4 | **Resist / cap calculator** | "How much do I need from gear?" Inputs: current resists, act penalty, overcap. | Common question. | Pure maths. | ✅ | S |

### E. Economy and currency

| # | Feature | Problem → how it works | Why useful | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|
| E1 | **Divine ⇄ chaos converter widget** | Always-visible rate with a "fresh as of" label. | Most common calculation. | poe.ninja exchange overview (documented). | ✅ | S |
| E2 | **Economy dashboard** (Wealthy Exile CSV + ninja) | See `WEALTHY_EXILE_INTEGRATION.md`. | Headline feature. | CSV importer + SQLite + charts. | ✅ | M–L |
| E3 | **Profit-per-hour session ledger** | Start and end wealth (from CSV snapshots or manual entry) × session time → chaos/h and div/h. | Exilence's core value [V]. | SQLite. | ✅ | M |
| E4 | **Farming strategy ROI** | Inputs priced from ninja, outputs entered by hand → ROI per map. Wealthy Exile has public strategies [V]; ours are personal and offline. | Decision support. | Page + ninja prices. | ✅ | M |
| E5 | **Price watchlist** | Alert when an item or currency crosses a threshold. Refresh ≥ 15 min with ETag. | Investment tracking. | `HttpClient` + toasts. | ✅ (follow ninja's rules) | M |
| E6 | **Official currency exchange history** | GGG's *public* `currency-exchange` endpoint gives hourly volume and stock per market [V]. Chart real exchange volume. | Official, auth-free data. Rarely used by desktop tools **[A]**. | Hourly fetch + SQLite. | ✅ | M |
| E7 | **Crafting cost estimator** | Expected orbs × ninja price for simple spam crafts (probability entered or linked from Craft of Exile). | "Is it cheaper to buy?" | Pure maths + ninja. | ✅ | M |

### F. General QoL

| # | Feature | Problem → how it works | Size | Compliance |
|---|---|---|---|---|
| F1 | **Hotkey manager page** with conflict detection and scopes | S–M | ✅ |
| F2 | **Profiles** (mapping / bossing / per character) switchable from the header | S | ✅ |
| F3 | **Session timer / stopwatch / countdown** overlay | S | ✅ |
| F4 | **Notes and sticky notes** (per build, map or boss) | S | ✅ |
| F5 | **Checklists** (league start, atlas, daily) | S | ✅ |
| F6 | **Reference overlays** (user images: lab, syndicate, Heist cheat sheets), as in Exile-UI [V] | M | ✅ |
| F7 | **Quick links / command palette** (Ctrl+Shift+Space) | S | ✅ |
| F8 | **Notifications centre** (toasts for price alerts, whispers, errors) | S | ✅ |

### G. More creative ideas (beyond the categories above)

| # | Idea | Problem it solves | How it would work | Why players care | Implementation | Compliance | Size |
|---|---|---|---|---|---|---|---|
| G1 | **League auto-detect** | League names are hard-coded (`trade.league: Mirage`) and go stale. | poe.ninja `/poe1/api/economy/leagues`: the first entry is the current league [V]. | Everything "just works" at league start. | Startup fetch + cache. | ✅ | S |
| G2 | **Per-feature compliance badges** | Players fear bans and don't know what a tool does. | Every page shows a badge: *No game input*, *1 action per key*, *Reads clipboard on key press*, *Reads Client.txt*. | Trust. **Differentiator.** | Static metadata on `Page`. | ✅ | S |
| G3 | **API budget meter** | "Why is it slow?" | Header chip showing rate-limit state per host (APT does this for trade [V]). | Transparency. | From `HttpClient`. | ✅ | S |
| G4 | **Stale-stat doctor for `map_mods.yaml`** | Stat ids change between leagues (commit `d364c7d` shows this happened). | Compare against poe.ninja's `tradeInfo` / `tradeFilter` stat ids, or a bundled RePoE dataset, and flag missing ids. | Prevents silent 400s. | Offline check + report. | ✅ (no undocumented GGG endpoints) | S–M |
| G5 | **"Last league at this day" comparison** | Is this league's economy inflated? | Link to Antiquary for the same day-of-league, alongside current ninja. | Investment timing. | URL template. | ✅ | S |
| G6 | **Smart Quick-Action hotkey** | Too many hotkeys. | One hotkey reads the clipboard once and routes: map → C1, currency → B2, unique → ninja price + links, rare → open trade. | Fewer keys to learn (Exile-UI lesson [V]). | Item-class router on top of the branch's parser. | ⚠️ one clipboard read per press | M |
| G7 | **Hotkey-vs-game keybind checker** | Our F-keys collide with the user's PoE binds. | The user enters (or pastes) their in-game binds; the app warns on overlap. Never read game config files (COMPLIANCE §3.4). | Prevents "my flask pressed my macro". | Page + conflict check. | ✅ | S |
| G8 | **Divination card set board** (from WE CSV) | Which stacks are nearly complete, and what are they worth? | CSV rows filtered to div cards + ninja stack size and price. | Quick wins. | CSV + ninja `DivinationCard`. | ✅ | M |
| G9 | **Strategy journal** | Players forget why a strategy failed. | Session (C5) + inputs (E4) + notes (F4) → one "run report". | Learn from runs. | Joins existing tables. | ✅ | M |
| G10 | **Wealth goal tracker** | "When can I afford the build upgrade?" | Target value plus the hourly rate (E3) → ETA. | Motivating and simple. | Arithmetic over snapshots. | ✅ | S |
| G11 | **Patch-day safety switch** | After a patch, stat ids and mods change. | On version or league change, show a banner and disable stat-dependent features until G4 passes. | Avoids failed or wrong searches. | League detect + flag. | ✅ | S |
| G12 | **Offline mode** | Flaky internet or poe.ninja down. | All pages work from the last cache with "as of" labels. | Reliability. | Cache layer. | ✅ | S (with the services layer) |
| G13 | **Diagnostics bundle** | Bug reports with no information. | One click collects version, OS, log tail and redacted config. | Maintainability. | Stdlib zip. | ✅ | S |
| G14 | **Trade price sanity hint** | Mis-pricing by 10× with the wrong currency. | When a typed price in B2/B3 deviates more than X % from ninja, warn. | Prevents costly typos. | Ninja lookup. | ✅ | S |
| G15 | **Map Search "share code"** | Sharing exclusion presets with friends. | Export or import a preset as a short base64 string. | Social, low cost. | Base64 of a JSON list. | ✅ | S |
| G16 | **Atlas progression tracker** | Atlas completion and voidstones are tracked in your head **[A]**. | Manual tick-list per league with progress bars. | Clear goals. | Checklist variant. | ✅ | S |
| G17 | **Boss prep cards** | Forgetting mechanics or resist needs. | Hand-written cards (user notes plus links to the wiki). Ship a template, not content, to avoid maintenance. | Bossing QoL. | Notes + templates. | ✅ | S |
| G18 | **Build comparison** (two PoB codes) | "Is the new setup better?" | Diff the decoded XML: items, gems, key stats PoB exports. | Upgrade planning. | D1 + diff view. | ✅ | M–L |
| G19 | **Stream-friendly mini overlay** | Streamers want session stats on screen. | A borderless, chroma-key-friendly window showing session, maps and income per hour. | Niche but delightful. | A QWidget with transparent background. | ✅ | S |
| G20 | **Ninja price → trade link** | Jumping from "worth X" to "buy it". | poe.ninja lines include `tradeFilter` for the official trade site [V]. Open it in the browser. | Fewer steps. | URL building. | ✅ (browser) | S |
| G21 | **Personal price history** | "What did I pay last league?" | B3 ledger with charts across leagues. | Memory. | SQLite. | ✅ | S |
| G22 | **Import-anything inbox** | Many CSV sources (Wealthy Exile, Exile-UI map tracker CSV [V], ladder CSV). | Drag-and-drop a file onto the window; detect its type and route it to the right importer. | Reduces friction. | Header sniffing. | ✅ | M |

**Deliberately excluded ideas** (COMPLIANCE_REVIEW §3.4): auto-flask variants, threshold logout, "craft until", one-key multi-craft, auto-accept trade, auto-invite, screen-OCR loot tracking, filter file auto-editing, session-cookie stash sync.

---

## 5. References

Official:

- GGG Developer Docs (policy, macro and overlay rules, UA, rate limits): <https://www.pathofexile.com/developer/docs>
- GGG API Reference (scopes, public Currency Exchange endpoint): <https://www.pathofexile.com/developer/docs/reference>
- GGG Authorization: <https://www.pathofexile.com/developer/docs/authorization>
- Terms of Use: <https://www.pathofexile.com/legal/terms-of-use-and-privacy-policy>
- poe.ninja API policy: <https://poe.ninja/docs/api>

Community:

- Macro guide: <https://www.pathofexile.com/forum/view-thread/2077975>
- ToS clarification thread: <https://web.poecdn.com/forum/view-thread/3734853>
- "Is APT allowed?" thread: <https://www.pathofexile.com/forum/view-thread/3474232>

Projects: all repository links are listed in §1.
