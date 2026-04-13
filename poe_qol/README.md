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
