# Compliance Review: Twice Corrupted

> **Status, 2026-11-23:** the §2.1 plan was **approved and implemented** (commit `d5e5be1`, branch `feat/twice-corrupted-compliance`). The life-flask timer and both dump sweeps are retired, the slot tabs are highlight-only, Help → About shows the GGG disclaimer, and `tests/test_compliance.py` guards all of it. Still open: the Map Search trade-API call (honest UA, rate limiting) and the branch's Pricer and Flipper.
>
> **Later on 2026-11-23:** the owner allowed opt-in experimental features that break GGG's rules, provided they are isolated and documented honestly. The Alt+drag area selection ships a compliant manual mode and a **non-compliant** experimental bulk Ctrl-click mode. See §7.

> **Not legal advice, no guarantees.** This review applies a *conservative* reading of Grinding Gear Games' (GGG) published rules. GGG does not certify third-party tools, and nothing here guarantees an account will not be actioned. When this document says "compliant" it means "consistent with the conservative reading of the published text", nothing more.

Legend used throughout the docs:

| Tag | Meaning |
|---|---|
| **[V]** | Verified fact, with a source URL |
| **[R]** | Recommendation (my judgement) |
| **[A]** | Assumption that still needs checking |

---

## 1. The rules that matter

### 1.1 GGG Developer Docs: "API Policies and Third-Party Requirements" [V]

Source: <https://www.pathofexile.com/developer/docs> (read 2026-11-23)

This is the most specific public text GGG has published about local tools. Paraphrased closely:

**Executable apps that run independently from the game** are "not encouraged" but "permitted". When they interact with GGG's APIs they must use a *public* OAuth client.

**Macro rules.** Automating key strokes or other input that affects the game must follow all three:

1. Macros must be **invoked manually by the user**. Automated invocation is not allowed, including (but not limited to) **timers**, **reacting to file changes** and **reading the screen**.
2. Each macro invocation must have **one set function**. It cannot cycle between actions.
3. That function may perform **only one action that interacts with the game**. Sending a single chat message or command counts as one action.

**Overlay rules.** These apply to apps that use information from the screen, the clipboard or the game's logs:

- You may only read this information while the user is aware of what you are doing with it.
- Reading from the screen or clipboard is limited to **once per manual key press**.

**Executable apps that interact with the game or its files** are "strictly against our Terms of Use (sections 7b, 7c, 7i)" and lead to immediate account termination.

**Available resources.** Only endpoints in the API Reference or the Data Exports are supported. *"Requests for access to any other internal website APIs or in-game resources will be denied. It is against our Terms of Use (section 7i) to reverse-engineer endpoints outside of this documentation."*

**User-Agent.** Any app that uses the API must send `User-Agent: OAuth {clientId}/{version} (contact: {contact})`.

**Third-party notice.** Every public tool should show: *"This product isn't affiliated with or endorsed by Grinding Gear Games in any way."*

**Rate limits.** Clients must parse the `X-Rate-Limit-*` and `Retry-After` headers. Too many 4xx responses (including 429) lead to restriction.

**Registration.** At the time of reading, the docs said *"We are currently unable to process new applications."* For this project, that means **new OAuth clients cannot be registered right now**.

### 1.2 Terms of Use, section 7 [V, partial]

Source: <https://www.pathofexile.com/legal/terms-of-use-and-privacy-policy>

Search-indexed excerpts of section 7 ("Restrictions") ban the following without GGG's written approval:

- modifying or adapting the game client or its data, including through third-party tools
- using "automated software or 'bots'"
- reverse-engineering the services or seeking to establish their "communication protocols"

I could not confirm the exact sub-clause lettering from the live page. **[A]** Re-read the live page before quoting clause numbers publicly.

### 1.3 Community and staff interpretations (non-binding) [V]

- The long-running community guide [What a macro is allowed to do](https://www.pathofexile.com/forum/view-thread/2077975) summarises the rule as "one action per key press". It gives *"pops a flask … when you reach a specific health threshold"* as a forbidden example.
- Staff replies in support threads repeat that GGG *"cannot comment on the legality of third-party tools"*. Example: [clarification on ToS](https://web.poecdn.com/forum/view-thread/3734853).
- Exile-UI's author states that *"to my knowledge, GGG has never approved any (local) 3rd-party tool"*. Source: <https://github.com/Lailloken/Exile-UI>.

### 1.4 poe.ninja usage rules [V]

Source: <https://poe.ninja/docs/api> (read 2026-11-23)

- The **economy overview endpoints** are the "supported public surface". Builds, profiles, character, PoB and auth endpoints are internal and *not* for third-party use.
- No SLA, and breaking changes can happen without notice.
- Send a descriptive User-Agent with a contact. Respect the ~5-minute HTTP cache (ETag/conditional requests). Don't poll faster than a few minutes, because PoE1 data refreshes about every 15 minutes.
- *"Desktop apps … should proxy these requests through their own backend rather than calling the endpoints directly from end-user machines."*
- Clients that misbehave or use the endpoints excessively are blocked.

---

## 2. Assessment of existing functionality

The assessment covers `main` and the unmerged branch `claude/design-review-icon-nS8OE`.

| Feature | What it actually does (from source) | Verdict | Why |
|---|---|---|---|
| **Life flask** (`macros/life_flask.py`) | Backtick toggles a loop that presses `1` every 4–5 s until stopped. | ❌ **Not compliant** | Timer-driven invocation is named explicitly as forbidden (rule 1). It is also a repeated action without a key press per action. |
| **Inventory dump** (`macros/inventory_dump.py`) | F1/F2 → 2 "focus" clicks with no modifier, then hold Ctrl and click **up to 60 slots**. | ❌ **Not compliant** | One key press produces up to 62 game-affecting actions (breaks rule 3). The focus clicks also pick up and drop an item with no modifier. |
| **Map stash dump** (`macros/map_stash_dump.py`) | Same as above over 72 slots (F3/F4, or the "Dump" buttons). | ❌ **Not compliant** | Same reason. The UI "Dump" button is the same automation started from our window. |
| **Coordinate picker** (`macros/coord_picker.py`) | Ctrl+Alt+C reads the cursor position and saves it to JSON. Ctrl+Alt+V logs the saved points. | ✅ Compliant | Sends no game input and reads no screen content. |
| **Calibration dialog** | F8 reads the cursor position. Nothing is clicked. | ✅ Compliant | Sends no game input. |
| **Slot overlay** | Click-through, always-on-top window that draws highlights. Polls the PoE window *rectangle* every 250 ms. | ✅ Compliant | It doesn't read screen pixels, clipboard or logs. A window rectangle is OS window metadata, not game data. **[A]** GGG has not commented on window-rect polling specifically. |
| **Template anchor** (`vision/`, off by default) | Grabs the screen once per sweep to find the inventory. | ⚠️ Compliant in isolation | One screen read per manual key press is allowed. It is only used by the non-compliant sweep, though. |
| **Emergency stop / Pause** | Stops threads and sends key-up for Ctrl/Shift/Alt. | ✅ Compliant | Releases keys only. Keep it. |
| **Map Search → trade link** | Builds a query, **POSTs it to `/api/trade/search`** with a **spoofed Chrome User-Agent**, retries up to 16× when a stat id is rejected, then opens the result in the browser. | ⚠️ **Uncertain, needs changes** | `/api/trade/search` is **not** in the API Reference, which the docs class as an "internal website API". The spoofed User-Agent goes against the identifiable-UA requirement and exists to get past Cloudflare. Automatic retries add 4xx responses that count toward the invalid-request threshold. Widely used tools (APT, Sidekick) call the same endpoint, but **[A]** that tolerance is not a published permission. |
| **Pricer** (branch only) | Listens to `QClipboard.dataChanged`. On every copy it auto-queries trade search + fetch (or bulk exchange) with a spoofed UA. | ⚠️ **Uncertain** | One clipboard read per user Ctrl+C fits the overlay rule. But it fires on *any* copy in *any* app, which may send unrelated clipboard text over the network. It uses the same internal endpoints and spoofed UA as Map Search. |
| **Flipper** (branch only) | Ranks currencies from poe.ninja `currencyoverview` data. Optional auto-refresh. | ✅ Mostly compliant | Purely informational. It uses the **old undocumented** `/api/data/currencyoverview` route rather than the documented `/poe1/api/economy/exchange/...`. Its 10-minute cache is polite but should honour ETag. |
| **Legacy AHK/C++ scripts** (repo root) | `Life Flask.ahk` (timer), `inventory.ahk` and `autoclicker.cpp` (multi-click sweep), `getcoords.ahk` (cursor reader). | ❌ Three of four are not compliant | Same reasons as their Python replacements. They are archived under `legacy/` with a warning. |

### 2.1 Uncomfortable conclusion

**The app's two headline macros, the flask timer and the bulk Ctrl-click sweep, are the textbook examples GGG prohibits.** The README's line "only sends normal input, like AutoHotkey" does not make them safe. As the project brief itself says, AutoHotkey is a technology choice, not an exemption. Keeping them as default-on, prominently branded features is incompatible with the project's own non-negotiable compliance requirement.

**[R] Recommended handling (needs your approval, nothing changed yet):**

1. Set `life_flask`, `inventory_dump` and `map_stash_dump` to `enabled: false` by default, and add a visible "non-compliant: use at your own risk" label. Or, better, remove them from the shipped app and keep them in `legacy/` for reference only.
2. Replace the **sweep** with **compliant assists** that keep the investment already made in calibration and the slot grid:
   - **Slot highlighter overlay.** The existing overlay already works. The user Ctrl-clicks manually, with clear "click these" highlights and an "N remaining" counter.
   - **Optional "advance highlight" hotkey** that moves the highlight to the next slot *without* sending any input to the game. That is UI state only.
3. Replace the **flask timer** with nothing input-related. Point users to in-game mechanics such as flask enchantments that trigger automatically on charge gain (Instilling Orbs). **[A]** Mechanic names vary by patch, so verify them in-game. An *opt-in visual* flask-duration timer is possible but not recommended (see 3.3).

---

## 3. Risk assessment of proposed features

### 3.1 Clearly within boundaries ✅

Features that send **no input to the game** and read **no screen, clipboard or log data**, or that only read logs with user awareness:

- Calculators: currency conversion, bulk ratio, sustain, resists, profit per hour.
- Reference data: dangerous-mod database, atlas notes, gem and checklist planners, cheat sheets.
- Session timers, notes, checklists and profiles that the user drives entirely in our window.
- Opening websites (trade, poe.ninja, PoB, FilterBlade, Wealthy Exile) in the user's browser.
- Importing user-exported files (Wealthy Exile CSV, PoB codes, ladder CSV).
- Displaying data from poe.ninja's **documented economy endpoints**, following their usage rules.
- Displaying data from GGG's **documented public Currency Exchange endpoint** (`GET https://web.poecdn.com/api/currency-exchange`, hourly digests) [V] <https://www.pathofexile.com/developer/docs/reference>.
- Overlays that only *draw* (slot highlights, reference panels).
- **Client.txt log reading** for area changes and session tracking, provided the user is told and opts in. The overlay rules allow log reading with user awareness. Exile-UI, Exile Diary and PoE Lurker all do this [V].

### 3.2 Within boundaries if built carefully ⚠️

| Feature | Condition to stay compliant |
|---|---|
| Chat-command hotkeys (`/hideout`, `/exit`-style commands, a canned whisper reply) | **Exactly one** chat message or command per key press [V rule 3]. No "type message + press enter + another command" chains. A single command needs Enter, chat-open and paste, which together are one *message*. That is how GGG phrases it. |
| Price check on hotkey | **One** clipboard read per manual key press. Prefer an explicit hotkey over a passive clipboard watcher. Use the trade site only via a user-opened browser, or via rate-limited, honest-UA requests (see 3.4). |
| Stash search string paste (poe.re-style regex) | One key press pastes one string into the focused search box = one action. The user writes or chooses the string. |
| Stash or account data via GGG OAuth (`account:stashes`) | Only with a registered **public** OAuth client. **Registration is currently closed** [V]. Until it reopens, rely on Wealthy Exile's CSV export (see `WEALTHY_EXILE_INTEGRATION.md`). |

### 3.3 Uncertain, needs more investigation ❓

| Feature | Why it's uncertain | Safer alternative |
|---|---|---|
| Flask-duration *visual* timer started by watching the user's own key press | No input is sent, but it is a gameplay-reactive aid built on a global key hook. GGG hasn't addressed it. | Leave it out. If it's built, make it opt-in and visual only. |
| "Move cursor to next slot" hotkey (no click) | Forum threads call cursor-positioning macros unclear. Moving the cursor isn't a server action, but it is automated input. | Highlight only, so the user moves the mouse. |
| Calling `/api/trade/search` / `fetch` / `exchange` from the desktop app | Not in GGG's documented API. Tolerated in practice for APT and Sidekick, but not published as allowed. | Open the trade site in the user's browser with the query pre-filled. **[A]** Whether `pathofexile.com/trade/search/<league>?q=<json>` still pre-fills could not be verified: Cloudflare challenged the automated browser. Test it manually first. |
| Screen OCR of map mods (Exile Diary, Exile-UI) | Allowed only once per manual key press with user awareness. OCR pipelines are heavy and brittle. | Use the clipboard (Ctrl+C on the map → one read per key press) instead of OCR. |

### 3.4 Should not be implemented ❌

- Any timer, threshold or screen-triggered input (auto-flask, auto-guard, auto-logout on low life, auto-loot).
- Any single key press that performs more than one game action (bulk Ctrl-click, "craft until mod", "spam alteration", multi-flask, chained chat commands, auto-trade-accept).
- Automated trading or interactions with other players (auto-invite on whisper, auto-reply, auto-kick).
- Reading or writing game memory, or patching or reading the GGPK/bundles for hidden data.
- Changing game config files such as `production_Config.ini`. Writing *loot filter* files is a grey area. Chaos Recipe Enhancer does it "offline" [V], but **[R]** keep it out of scope.
- Reverse-engineering private endpoints: Wealthy Exile's internal API, poe.ninja builds/profiles, the trade site's undocumented routes beyond what's already used.
- Spoofing a browser User-Agent to get past Cloudflare or rate limits.
- Storing or replaying `POESESSID` session cookies.

---

## 4. Safer implementation alternatives (summary) [R]

| Current / proposed | Safer alternative |
|---|---|
| Bulk Ctrl-click sweep | Visual slot highlighter with a manual-click workflow and an "N remaining" counter. |
| Life flask timer | Remove it. Document in-game auto-trigger flask mechanics. |
| POST to `/api/trade/search` with a spoofed UA | Open the browser with a pre-filled query, plus "Copy query JSON". If server-side search is kept: **honest UA**, a client rate limiter that follows `X-Rate-Limit-*` (APT defaults to 1 request per 5 s and adjusts from headers [V] `awakened-poe-trade/renderer/src/web/price-check/trade/common.ts`), no automatic retries, user-initiated only. |
| Passive clipboard price watcher | Explicit "price check" hotkey or button. Ignore clipboard text that isn't a PoE item. Never send non-item clipboard text over the network. |
| Undocumented poe.ninja routes | Documented `/poe1/api/economy/...` endpoints with ETag caching, a ≥15-minute refresh and a descriptive UA. |
| OAuth stash sync (closed) | Wealthy Exile CSV import, done by the user. |

## 5. Required notices [R]

Add to the About page, README and first-run dialog:

> This product isn't affiliated with or endorsed by Grinding Gear Games in any way.

Add a **Transparency** panel listing exactly what the app reads and sends. Model it on Exile-UI's "Transparency Notice" [V] <https://github.com/Lailloken/Exile-UI>, and keep it in sync with the actual features.

---

## 6. Update 2026-11-23: Trade Browser, Map Search default, wealth overlay

| Feature | What it does | Verdict |
|---|---|---|
| **Map Search default changed to `url_mode: copy`** | "Open Trade" now opens `pathofexile.com/trade/search/<league>?q=<json>`, and the trade site runs the search on page load. This is the same link format Awakened PoE Trade opens [V] `renderer/src/web/price-check/trade/TradeListing.vue:240`. No API call or spoofed UA on the default path. | ✅ Resolves the §2 Map Search concern by default. `post` mode remains opt-in. |
| **Trade Browser** (QtWebEngine window) | An ordinary browser the user drives. It loads only `https://*.pathofexile.com` plus Steam's OpenID sign-in page, and sends any other link to the system browser. No script injection, no cookie reads. Cookies stay in its private profile, and "Sign out & clear" wipes them. | ✅ Website use by the player. We do **not** copy APT's approach of reusing the browser's cookies for app-made API calls [V] `main/src/proxy.ts` (`useSessionCookies: true`), because that reuses a Cloudflare clearance to automate requests (§3.4). |
| **Divine-per-hour overlay** | Display-only, always-on-top window. Data comes only from Wealthy Exile CSV files the user exports. It re-reads a local folder on an interval (minimum 5 min). | ✅ No game input. No screen, clipboard or log reads. No requests to Wealthy Exile. |
| Live Wealthy Exile feed (logged-in scraping or private endpoints) | — | ❌ Not built. Needs Wealthy Exile's permission (WEALTHY_EXILE_INTEGRATION §2, X1/X2). |


---

## 7. Update 2026-11-23: Alt+drag area selection

On 2026-11-23 the owner set a new policy for this personal, local-only project. Features that break GGG's rules may be built, but they must stay isolated, be off by default, be acknowledged explicitly, and never be described as compliant. The engineering is documented in [`AREA_SELECT.md`](AREA_SELECT.md). This section covers only the policy side.

| Part | What it does | Verdict |
|---|---|---|
| **Gesture + overlay** (`input/mouse_hook.py`, `area_select/`) | A global low-level mouse/keyboard hook *observes* input. It swallows only the left-button down/up of an Alt+drag that starts on the calibrated grid while PoE is focused, plus Esc during that drag. It draws a click-through overlay. | ✅ No input is sent to the game, and no game memory or files are read. Swallowing our own gesture's clicks is the same class of behaviour as any overlay hotkey. |
| **Empty-slot detection** (`area_select/occupancy.py`) | One screenshot of the grid per drag, classified by brightness and texture | ✅ Reads only pixels that are already on screen, like other overlays. No memory reads. |
| **Manual transfer** (`ManualTransfer`, default) | Highlights and numbers the selected slots. The player Ctrl-clicks each one, and the app only *observes* those clicks to tick slots off. | ✅ One player click = one game action. This is the compliant alternative proposed in §2.1 (2). |
| **Experimental transfer** (`experimental/bulk_ctrl_click.py`) | After one Alt+drag, holds Ctrl and clicks every selected slot (up to `max_slots`, ≥20 ms apart) | ❌ **Not compliant.** One user gesture triggers many game actions, which is the same reason the F1/F2 dump sweep was retired (§2). GGG may treat it as a macro or bot and action the account. |

Safeguards around the experimental transfer. These limit accidents, but they don't make it compliant:

- **Off by default.** `transfer_mode: manual` and `experimental.acknowledged: false` ship in `default.yaml`. Selecting it in the Area Select tab shows a warning that must be accepted, and the tab then shows a permanent red notice. `tests/test_compliance.py` pins these defaults.
- **Isolated.** The code lives only in `poe_qol/experimental/`. Nothing imports it at module level (enforced by an AST check in `test_compliance.py`), and the controller imports it only when the acknowledged mode is used. The class declares `GGG_COMPLIANT = False`.
- **Stops on:** F12 or the master switch, Esc, a new gesture, loss of game focus, and real mouse movement by the player. Ctrl is always released. It waits for Alt to be released, so PoE never gets Ctrl+Alt+click.
- **No disguise.** The delays are fixed (no randomised "human-like" timing), and nothing hides the tool from the game or from GGG.

The README and Help → About now state that the optional experimental transfer breaks the one-action rule. The rest of the app's compliance claims (no timers, no memory reads, one action per key press for every non-experimental feature) still hold.
