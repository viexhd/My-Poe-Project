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

`autoclicker.cpp` used to live in `poe mini project/` at the repo root. Nothing in the build or the app references any of these files. They can be deleted once you no longer need them, and git history keeps them either way.
