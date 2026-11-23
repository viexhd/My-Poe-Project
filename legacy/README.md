# Legacy scripts (archived)

These are the original scripts that `poe_qol` replaced. They are kept for reference and history only. **They are not part of the app, and you shouldn't run them.**

> ⚠️ **Compliance warning.** Three of the four scripts break Grinding Gear Games' published macro rules (<https://www.pathofexile.com/developer/docs>):
>
> - `Life Flask.ahk` presses a key **on a timer** (forbidden: "automated invocations such as … timers").
> - `inventory.ahk` and `autoclicker.cpp` perform **up to 60 clicks per key press** (forbidden: "may only perform one action that interacts with the game").
>
> See `docs/COMPLIANCE_REVIEW.md`.

| File | What it did | Replaced by | Compliant? |
|---|---|---|---|
| `Life Flask.ahk` | Backtick toggles pressing `1` every 4–5 s | `macros/life_flask.py` | ❌ |
| `inventory.ahk` | Ctrl-click through a fixed 12×5 grid | `macros/inventory_dump.py` | ❌ |
| `autoclicker.cpp` | Win32 GUI version of the inventory clicker | `macros/inventory_dump.py` | ❌ |
| `getcoords.ahk` | Ctrl+Alt+C / Ctrl+Alt+V cursor-coordinate capture | `macros/coord_picker.py` | ✅ (no game input) |

## `poe_qol_macros/`: retired Python macros

These are the Python ports of the scripts above. They were retired from the app on 2026-11-23 for the same compliance reasons, with the owner's approval. They are copies of the last working versions, kept for reference. They are **not** on the import path and won't run as-is.

| File | What it did | Replaced by |
|---|---|---|
| `life_flask.py` | Backtick toggles pressing the flask key every 4–5 s | Nothing (no compliant equivalent sends input) |
| `inventory_dump.py` | F1/F2: focus clicks, then Ctrl+click up to 60 inventory slots. Also held `GridDumpMacro` and the grid helpers. | Inventory tab slot **highlighter** (overlay only; you click) |
| `map_stash_dump.py` | F3/F4: the same sweep over a 12×6 map stash tab | Map Stash tab slot **highlighter** |

The Alt+drag **Area Select** feature (`docs/AREA_SELECT.md`) now covers what `inventory_dump.py` did. Its experimental mode Ctrl-clicks the selected slots (also not compliant), and its manual mode replaces the click loop with highlighting. These legacy copies are kept until that experimental mode has been confirmed in-game. After that they can be deleted.

`autoclicker.cpp` used to live in `poe mini project/` at the repo root. Nothing in the build or the app references any of these files. They can be deleted once you no longer need them, and git history keeps them either way.
