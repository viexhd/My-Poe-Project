# poe_qol

Modular quality-of-life automation for Path of Exile. A refactor of
four legacy scripts (`Life Flask.ahk`, `inventory.ahk`,
`getcoords.ahk`, `poe mini project/autoclicker.cpp`) into a single
cohesive Python application.

Only simulates user input (no memory access / injection) — same
posture as AutoHotkey.

## Why Python

* **PySide6** for the UI — cross-platform, mature, trivially packaged.
* **pydirectinput** for input — uses `SendInput` with scancodes, works
  with DirectInput games like PoE.
* **keyboard** for global hotkey hooks — low-latency WH_KEYBOARD_LL.
* **OpenCV + mss** for image recognition — ~200 FPS ROI capture,
  template matching in a few ms.

See `default.yaml` for the single source of truth for every timing,
coordinate, and hotkey. No magic numbers live in code.

## Install / run

```bash
python -m pip install -r requirements.txt
python -m poe_qol
```

## Layout

```
config/                 YAML config (default + profiles)
assets/templates/       PNGs for template matching
logs/                   Log files + captured coords
src/poe_qol/
    core/               config, state bus, logger
    input/              hotkey router, input sender
    vision/             mss capture, opencv detectors
    engine/             Macro ABC, registry, scheduler
    macros/             one file per feature (plugin-style)
    ui/                 Qt main window
```

## Adding a new macro

1. Drop a new file under `src/poe_qol/macros/`.
2. Subclass `Macro`, set `NAME`, decorate with `@register`.
3. Add a `macros.<name>` section in `default.yaml`.

That's it — `Scheduler.load()` discovers it on next launch.

## Features converted

| Legacy script | Replaced by |
|---|---|
| `Life Flask.ahk` | `macros/life_flask.py` |
| `inventory.ahk` + `autoclicker.cpp` | `macros/inventory_dump.py` |
| `getcoords.ahk` | `macros/coord_picker.py` |

## Safety

* `F12` emergency stop is always bound and cannot be rebound to nothing.
* `Pause` toggles the master switch.
* Every macro checks `AppState.stop_event` every iteration — no loop
  can run away for more than one click / keystroke.
* Re-entry is guarded at the `Macro` base class, so hammering F1 never
  starts two inventory sweeps.

---

## Trade-link generator

A tiny poe.re-style parser turns regex-ish map mod queries into a PoE
trade POST payload / URL.

Syntax:

    ,  newline    – AND (all groups must match)
    |             – OR within a group
    !             – negate an atom
    "…"           – quote a multi-word mod (optional; spaces are OK
                    unquoted as long as no `,` / `|` appears inside)

Examples:

| Input | Meaning | Trade stat group |
|---|---|---|
| `!reflect` | reject reflect maps | `{type: not, filters: [reflect]}` |
| `!reflect, !no regen` | reject both | two `not` groups (AND) |
| `!reflect\|!no regen` | reject only maps with *both* | `{type: count, max: 1}` |
| `reflect\|vuln` | accept if at least one matches | `{type: count, min: 1}` |

Mod name → stat id mapping lives entirely in `config/map_mods.yaml`.
Aliases (e.g. `no regen` → `no regeneration`) and substring matching
make the input forgiving. Unknown mods log a warning and are dropped.

URL generation is config-driven:

    trade.url_mode: copy   # URL-encodes JSON into ?q= (copy/paste)
    trade.url_mode: post   # POSTs to api/trade/search, returns real URL

## Visual inventory slot selector

The **Inventory** tab renders a live 12×5 (config-driven) grid of
toggle buttons. Selection writes back to
`macros.inventory_dump.selected_slots` in config. When
`selected_slots` is non-empty, the inventory-dump sweep only visits
those slots.

Features:
* **All / None / Invert** bulk actions.
* **Save / Delete** named profiles under `config/slot_profiles/*.yaml`.
  The profile dropdown loads them on the fly, and you can set
  `macros.inventory_dump.active_slot_profile` in a top-level profile
  (mapping / bossing) to auto-select one.
* **Show overlay** — a frameless, always-on-top, click-through window
  that highlights the selected slots at the *real* inventory
  coordinates (origin + cell size from config). Drag the PoE window
  or tweak origin and the overlay moves with it.

The sweep still uses the existing vision anchor when
`anchor_template` is set, so the selector speaks in (row, col) and
the origin can be resolved from a template match at runtime.

## Tests

```
python -m unittest discover -s poe_qol/tests -v
```

Covers parser edge cases, trade-query builder (AND/OR/NOT/count),
mod-map aliasing + substring lookup, and grid generation + selection
filtering.
