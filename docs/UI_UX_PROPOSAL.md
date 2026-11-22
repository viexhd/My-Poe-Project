# UI / UX Proposal

Tags: **[V]** verified, **[R]** recommendation, **[A]** assumption.

This builds on, rather than replaces, the token-based theme already written on the unmerged branch (`ui/styles.py` on `origin/claude/design-review-icon-nS8OE`). The colours below keep its values so that work isn't thrown away.

---

## 1. Review of the current UI (on `main`)

The review treats the app as a commercial product. File references are to `main`.

| Area | Problem (specific) | Fix |
|---|---|---|
| Theme | No app theme. The window uses the default Windows light style, while the slot grid and overlay hard-code dark greys (`#333`/`#555`, `ui/slot_selector.py:148-152`) and green (`#4a8`). Buttons are hard-coded red `#c00` (`main_window.py:79-80`) and blue `#28a` (`slot_selector.py:129-130`). | One global QSS from design tokens (§3). Remove every inline `setStyleSheet`. |
| Labels | Macro toggles show internal ids (`life_flask`, `inventory_dump`, `map_stash_dump`, `coord_picker`) as checkbox text (`main_window.py:86`). | Human labels, descriptions and compliance badges, from page metadata. |
| Hotkey editing | Free-text `QLineEdit` 90 px wide. You type `ctrl+alt+c` by hand, with no capture, validation or conflict check until after binding. | A **key-capture field** ("Press a key…"), with inline conflict errors and reset-to-default. |
| Hierarchy | The Macros tab opens with a full-width red EMERGENCY STOP button. Danger is the loudest thing on screen even when nothing is running. | Move stop to a persistent **header status pill** ("● Idle" / "● Running: 2"). It turns red with a Stop action only while something runs. F12 still works everywhere. |
| Feedback | Errors and info use modal `QMessageBox` (for example "Macro is disabled", `slot_selector.py:207-219`). Successes such as "trade link opened" give no feedback at all. | Non-blocking **toasts**. Inline validation. Disabled controls with tooltips that explain *why*. |
| Unlabelled controls | The flask interval is two bare spinboxes under one label (`main_window.py:114-122`). | A labelled range ("Min" / "Max", with units). Moot if the flask macro is removed (COMPLIANCE §2). |
| Slot grid | 28 px toggle squares with no row or column hints. It doesn't look like the inventory and has no hover preview. | A grid that looks like the inventory (cell aspect, 12 × 5 with the quad-tab variant), selection colour from the accent, drag-to-paint selection, and a counter chip. |
| Calibration | A multi-line label with hand-placed `\n` (`calibrate_dialog.py:491-494`). Steps are text only. | A **stepper** (1 Top-left → 2 Top-right → 3 Bottom-left) with a live cursor readout and a "test overlay" preview. |
| Map Search | Category colours come from Flat-UI hexes in YAML (`#c0392b`, `#8e44ad`, …), unrelated to the app palette. | Map categories onto semantic tokens (`danger`, `warn`, `info`, `success`). |
| Navigation | Four flat tabs with no icons. A fifth and sixth (Flipper, Pricer) exist on the branch. Tabs won't scale past about seven. | **Grouped sidebar** (§4). |
| Onboarding | Calibration is required for the overlay, but nothing prompts for it. The default origin `[800,200]` is labelled "PLACEHOLDER" only in YAML. | A first-run checklist card on Home: league, calibrate, hotkeys, transparency. |
| Discoverability | Hotkeys appear only on the Macros tab. The overlay and Calibrate buttons are buried at the bottom of each grid tab. | Shortcuts are shown inline on buttons ("Open overlay · Alt+O"), plus a Hotkeys page and command palette. |
| Branding | The branch's icon pipeline is built around a **Piplup** (Pokémon) mascot (`assets/README.md` on the branch). | **[R]** Don't ship third-party characters, for IP and trademark reasons. Commission or draw an original mark. GGG also asks tools not to imitate its branding [V] <https://www.pathofexile.com/developer/docs>. |

---

## 2. Visual direction

The aim is a **quiet, dark, gold-accented workspace**. It should feel like the game's own UI at rest, without the ornament.

- **Dark-fantasy cues, used sparingly.** Warm gold for the accent and focus states only. A display serif for page titles only. No parchment textures or ornamental frames, because they cost legibility and look dated at small sizes.
- **Premium-software cues.** Generous spacing, a 1 px hairline border instead of heavy boxes, consistent 6/10 px radii, and tabular numbers.
- **PoE semantics as information, not decoration.** Item-rarity colours appear *only* where they mean rarity (price rows, item chips). Players read them instantly.

References (study the pattern, don't copy the identity):

| Pattern | Where to see it |
|---|---|
| Minimal overlay that blends in with the game | PoE Overlay CE README: *"core aspect is to blend in with the game"* [V] <https://github.com/PoE-Overlay-Community/PoE-Overlay-Community-Fork> (screenshots and demo video linked there) |
| Minimal, low-hotkey toolkit with a transparency notice | Exile-UI README and wiki screenshots [V] <https://github.com/Lailloken/Exile-UI> |
| Freshness label, Total/Hourly toggle, snapshot range | Wealthy Exile stash page [V] <https://wealthyexile.com> |
| Visible rate-limit state | APT `RateLimiterState.vue` [V] <https://github.com/SnosMe/awakened-poe-trade/tree/master/renderer/src/web/price-check/trade> |
| Dense tables with sparklines | poe.ninja economy pages <https://poe.ninja> |
| Progressive disclosure (one slider, then "advanced") | FilterBlade strictness <https://www.filterblade.xyz> |
| Stash pick-order highlight overlay | Chaos Recipe Enhancer README screenshots [V] <https://github.com/ChaosRecipeEnhancer/ChaosRecipeEnhancer> |

---

## 3. Design system

### 3.1 Colour tokens

Surface, text and accent values are kept from the branch's `styles.py`.

| Token | Hex | Use |
|---|---|---|
| `bg/0` | `#0E1116` | App background |
| `bg/1` | `#151A22` | Sidebar, page background |
| `bg/2` | `#1C222C` | Cards, inputs |
| `bg/3` | `#242B37` | Hover, raised |
| `line` | `#2A3240` | Hairline borders |
| `line/strong` | `#3A4454` | Focused or selected borders |
| `fg/0` | `#E6EAF2` | Primary text |
| `fg/1` | `#A9B2C3` | Secondary text |
| `fg/2` | `#6B7486` | Muted, captions |
| `accent` | `#E8B057` | Primary actions, focus ring, selected nav |
| `accent/hi` | `#F5C879` | Accent hover |
| `info` | `#4FA7E3` | Links, informational |
| `success` | `#3FB27A` | OK, "compliant" badge |
| `warn` | `#E0A24A` | Stale data, conditional badge |
| `danger` | `#D9544A` | Errors, stop, "excluded" |

Item-semantic colours, used only in item contexts. **[A]** These approximate the in-game frame colours. Check contrast against `bg/2` before finalising.

| Token | Hex | Meaning |
|---|---|---|
| `item/normal` | `#C8C8C8` | Normal |
| `item/magic` | `#8888FF` | Magic |
| `item/rare` | `#FFFF77` | Rare |
| `item/unique` | `#AF6025` | Unique |
| `item/currency` | `#AA9E82` | Currency |
| `item/gem` | `#1BA29B` | Gem |
| `item/divination` | `#0EBAFF` | Divination card |

Accessibility:

- **[R]** Body text `fg/0` on `bg/1` must be at least 4.5:1, and `fg/1` on `bg/1` at least 4.5:1. Verify both with a contrast checker before shipping.
- Never encode state by colour alone. Always pair it with an icon or label.

### 3.2 Typography

| Role | Font | Size / weight |
|---|---|---|
| UI text | **Segoe UI Variable**, fallback Segoe UI (ships with Windows, no bundling) | 13 px / 400 |
| Captions | Same | 11 px / 400, `fg/2` |
| Section title | Same | 16 px / 600 |
| Page title | Display serif, e.g. **Cinzel** (SIL OFL) **[A: confirm the licence before bundling]** | 20 px / 600, letter-spacing 0.5 |
| Numbers (prices, timers) | Segoe UI with tabular figures (`QFont.setFeature("tnum")`, Qt ≥ 6.7) | inherits |

### 3.3 Spacing, radius, borders, elevation

- **Spacing scale (4 px base):** 4 · 8 · 12 · 16 · 24 · 32. Page padding 24, card padding 16, control gap 8.
- **Radius:** 4 for cells and chips, 6 for controls (matches the branch), 10 for cards, 14 for dialogs.
- **Borders:** 1 px `line`. Focus is a 2 px `accent` outline offset by 1.
- **Elevation:** no drop shadows inside the window. Use a `bg` step instead. Overlays get a 1 px `line/strong` border so they stay readable over the game.

### 3.4 Components

| Component | Spec |
|---|---|
| **Button** | Variants are `primary` (accent fill, dark text), `secondary` (`bg/2` fill, `line` border), `ghost` (text only) and `danger` (outline, which fills red when "armed": a two-step confirm, as the branch already has). Height 32, or 28 compact. Icon plus label, and a shortcut hint on the right in `fg/2`. |
| **Input** | `bg/2`, 1 px `line`, radius 6, height 32. Focus ring in accent. Error shows a `danger` border plus a caption message below. Units are shown as suffix text. |
| **Key-capture field** | Shows a key chip (`Ctrl` `Alt` `C`). Click it to record. Esc cancels and Backspace clears. Conflicts appear inline: "Used by Overlay: toggle". |
| **Tabs** (inside a page) | Underline style from the branch, used only for sub-views (Economy → Dashboard / Stash / History / Market). |
| **Sidebar** | 220 px, collapsible to a 56 px icon rail. Groups have muted caps labels. The selected item has a 3 px accent bar on the left and a `bg/3` fill. Badges on the right show counts or alerts. |
| **Card** | `bg/2`, radius 10, padding 16. The header row holds a title, optional freshness chip and an overflow menu. |
| **Stat tile** | Big number (24 px, tabular), label caption, delta chip (▲ green / ▼ red with a sign, never colour alone). |
| **Status indicator** | A dot plus a word: `Idle` (fg/2), `Running` (accent, pulsing), `Stale` (warn), `Error` (danger), `Offline` (fg/2 with a slash icon). |
| **Freshness chip** | "Updated 4 min ago", turning warn after 2× the expected refresh. Hover shows the source and exact time. |
| **Compliance badge** | `No game input` (success), `1 action / key` (info), `Reads clipboard on key` (info), `Reads Client.txt` (info), `Use at own risk` (danger, only for legacy features). |
| **Tooltip** | `bg/3`, radius 6, max width 320, 400 ms delay. A shortcut line goes at the bottom. |
| **Toast** | Bottom-right, stacked, 4 s auto-dismiss (errors persist until dismissed), with an optional action ("Open log"). |
| **Modal dialog** | Only for destructive or blocking decisions. Title plus one sentence of consequence. Primary action on the right, Esc cancels. Calibration becomes a stepper dialog. |
| **Empty state** | Icon, one line explaining why it's empty, and one primary action ("Import Wealthy Exile CSV"). |

### 3.5 Implementation notes [R]

- Merge `styles.py` from the branch. Add tokens as a Python `dataclass` so widgets can read colours for `QPainter` (overlay and charts) from the same source.
- Use dynamic properties (`role="primary"`, `state="error"`) with `repolish()`, as the branch already does. No per-widget stylesheets.
- Ship icons as one SVG set (for example Lucide, ISC licence **[A: confirm]**) recoloured at runtime through `QIcon` and `QSvgRenderer`.
- Charts: `QtCharts` is part of `PySide6-Addons`, which is already installed with `PySide6`, so it adds no new dependency [V]. `pip list` shows `PySide6_Addons 6.11.0`.

---

## 4. Application structure

### 4.1 Proposed navigation

The brief's flat list (Macros, Inventory, Stash, Mapping, Trading, Economy, Calculators, Profiles, Settings) is organised by *feature type*. The research suggests organising by **player intent** instead, because in-game use happens in transient overlays and the main window is for *planning and review* (RESEARCH_REPORT §2.1).

```
┌ PoE QoL ─────────────────────────── [League: Mirage ▾] [Profile: Mapping ▾] ● Idle  ─ □ ✕ ┐
│ ┌──────────────┐                                                                        │
│ │ ⌂ Home       │                                                                        │
│ │──── PLAY ────│                                                                        │
│ │ ▦ Overlays   │  (slot highlighter, reference overlays, timers)                        │
│ │ ◷ Sessions   │  (Client.txt session tracker, run history)                             │
│ │ ⚑ Map Check  │  (clipboard map-mod verdict, build profiles)                           │
│ │──── TRADE ───│                                                                        │
│ │ ⌕ Map Search │                                                                        │
│ │ ¤ Price Check│                                                                        │
│ │ ⇄ Bulk Calc  │                                                                        │
│ │ ✎ Ledger     │                                                                        │
│ │── ECONOMY ───│                                                                        │
│ │ ◈ Wealth     │  (Dashboard / Stash / History tabs)                                     │
│ │ ↗ Market     │  (rates, watchlist, exchange history, flipper)                         │
│ │──── PLAN ────│                                                                        │
│ │ ⚔ Build      │  (PoB import, gem checklist, resist calc)                               │
│ │ ☑ Checklists │                                                                        │
│ │ ✐ Notes      │                                                                        │
│ │ ∑ Calculators│  (sustain, ROI, crafting cost)                                          │
│ │              │                                                                        │
│ │──────────────│                                                                        │
│ │ ⌨ Hotkeys    │                                                                        │
│ │ ⚙ Settings   │  (Profiles, Integrations, Paths, Updates)                               │
│ │ ⓘ About      │  (Transparency notice, GGG disclaimer, licences)                        │
│ └──────────────┘                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

Why this structure:

- **Inventory and Map Stash merge into Overlays.** After the compliance change they're the same tool (a highlighted grid) with different calibration presets. A segmented control picks "Inventory · Map tab · Quad tab".
- **Macros disappears as a page.** Hotkeys live on their owning page and are listed together under **Hotkeys**. Any remaining legacy macros sit behind Settings → *Legacy (non-compliant)*, off by default.
- **League and profile live in the header** because every page depends on them.
- **The status pill** replaces the giant stop button. It's always visible, red only while something is running, and clicking it stops everything.

### 4.2 How users move between tools

1. **Sidebar** for deliberate navigation, with Ctrl+1…9 for the first nine items.
2. **Command palette** (Ctrl+K inside the app; optional global hotkey) to type "map search", "rf safe", "import csv" and jump straight there.
3. **Cross-links:** a ninja price row has "Open on trade". A session links to its wealth delta. Map Check has "Exclude on Map Search".
4. **Summoned panels in game:** one **Quick Action** hotkey reads the clipboard once and opens the right small panel (map → Map Check, currency → Bulk Calc). This follows the "context beats configuration" lesson (RESEARCH_REPORT §2.2).

### 4.3 Key layouts

**Home**

```
┌ Home ─────────────────────────────────────────────────────────────────┐
│ ┌ 1 div = 186c ─┐ ┌ Wealth ───────┐ ┌ This session ─┐ ┌ Alerts ─────┐ │
│ │ ▲ 2.1% 24h    │ │ 412 div       │ │ 1h 12m · 9 maps│ │ 2 price ↑   │ │
│ │ ninja · 4m ago│ │ CSV · 2h ago  │ │ 38 div/h est. │ │ 1 whisper   │ │
│ └───────────────┘ └───────────────┘ └───────────────┘ └─────────────┘ │
│ ┌ Get started (3/5) ──────────────┐ ┌ Quick launch ─────────────────┐ │
│ │ ✓ League detected              │ │ [Map Search] [Overlay] [Bulk]  │ │
│ │ ✓ Hotkeys reviewed             │ │ [poe.ninja] [Trade] [PoB]      │ │
│ │ ○ Calibrate inventory  [Start] │ │ [Wealthy Exile] [FilterBlade]  │ │
│ │ ○ Import Wealthy Exile CSV     │ └───────────────────────────────┘ │
│ │ ○ Read transparency notice     │                                   │
│ └────────────────────────────────┘                                   │
└───────────────────────────────────────────────────────────────────────┘
```

**Overlays → Slot highlighter**

```
┌ Overlays ─ [Inventory | Map tab | Quad] ──────────────── badge: No game input ┐
│  ┌ grid 12×5 (looks like inventory, drag to paint) ┐  ┌ Profile ───────────┐ │
│  │ ▢▢▢▢▢▢▢▢▢▢▢▢                                     │  │ [maps_only ▾] Save │ │
│  │ ▢■■■▢▢▢▢▢▢▢▢                                     │  │ All · None · Invert│ │
│  │ ...                                              │  ├ Calibration ───────┤ │
│  └──────────────────────────────────────────────────┘  │ ✓ calibrated 2d ago│ │
│  14 selected                                            │ [Recalibrate]      │ │
│  [ Show overlay · Alt+O ]  [ Next highlight · Alt+N ]   └────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```

Economy layouts are in `WEALTHY_EXILE_INTEGRATION.md` §6.

### 4.4 In-game panels (summoned)

- A frameless, always-on-top `Tool` window, ≤ 360 px wide, placed near the cursor but clamped on-screen.
- It closes on Esc, on clicking away, or when the game regains focus (configurable).
- It follows the same tokens at 90 % opacity, with a 1 px `line/strong` border for contrast on bright scenes.
- **[V]** It works only in windowed or borderless mode. That's a general limit of top-level overlays, also noted by stashvision <https://github.com/darvid/stashvision>. Tell users in onboarding.
