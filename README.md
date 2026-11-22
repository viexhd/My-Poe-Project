# My PoE Project

Quality-of-life tools for **Path of Exile**. The project started as a few AutoHotkey scripts and a small C++ autoclicker. It grew into **poe_qol**, a Python desktop app that combines those tools with trade-site search in one window.

> poe_qol only sends normal keyboard and mouse input, the same way AutoHotkey does. It never reads or changes game memory. Grinding Gear Games' rules on macros still apply, so check them and use these tools at your own risk.

## poe_qol (the main app)

A PySide6 app with global hotkeys, screen capture and a tab for each tool.

| Tab | What it does |
|---|---|
| **Macros** | Turn each macro on or off and see its hotkey. Includes a **life flask** timer that presses your flask key at random 4–5 s intervals. |
| **Inventory** | A clickable 12×5 grid of your inventory. Pick slots (or load a saved slot profile), then press **F1** (left) or **F2** (right) and the **inventory dump** Ctrl-clicks only those slots. A see-through overlay can show the selected slots over the game. |
| **Map Stash** | The same grid sweep for the map stash tab. |
| **Map Search** | Choose map mods to require or exclude, then open a ready-made search on the official trade site. Settings include rarity, corrupted and a minimum mod count. |

**Under the hood**

- **Plugin-style macros**: each macro is one file in `macros/`. Subclass `Macro`, add `@register`, and the scheduler picks it up on the next launch.
- **All settings live in YAML** (`config/default.yaml` plus `mapping` and `bossing` profiles): timings, coordinates, hotkeys and the trade league. No magic numbers in the code.
- **Calibration**: grid positions are relative to the game window, and you set them up with a cursor-and-hotkey dialog, so they survive moving the window or changing resolution.
- **Safety first**: **F12** is a stop switch that is always bound and halts every macro mid-action. **Pause** turns everything off. A macro cannot be started twice at once.
- **Input** goes through `pydirectinput` (`SendInput` with scancodes, which PoE accepts). Global hotkeys use `keyboard`, and screen capture and template matching use `mss` and OpenCV.

### Run it (Windows)

Double-click `poe_qol/run.bat`. On first launch it creates a virtual environment, installs the dependencies and starts the app.

PoE usually runs as administrator, and Windows blocks input from programs that are not. Use `run-admin.bat` (or right-click `run.bat` and choose **Run as administrator**) if hotkeys do nothing in game.

Manual setup:

```bash
cd poe_qol
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m poe_qol
```

Requires Python 3.11+ on Windows.

### Tests

```bash
python -m unittest discover -s poe_qol/tests -v
```

More detail on the architecture, the trade-query syntax and the slot selector is in [`poe_qol/README.md`](poe_qol/README.md).

## Original scripts

The first versions of each tool are kept in the root of the repo. poe_qol replaces all of them.

| File | What it did | Replaced by |
|---|---|---|
| `Life Flask.ahk` | Press <kbd>`</kbd> to toggle pressing `1` every 4–5 s | `macros/life_flask.py` |
| `inventory.ahk` | Ctrl-click through a fixed 12×5 inventory grid with random delays | `macros/inventory_dump.py` |
| `poe mini project/autoclicker.cpp` | Win32 GUI version of the inventory clicker with adjustable start position and delays | `macros/inventory_dump.py` |
| `getcoords.ahk` | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>C</kbd> saves the cursor position and <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>V</kbd> lists them, for finding grid coordinates | `macros/coord_picker.py` |

## Repository layout

```
Life Flask.ahk, inventory.ahk, getcoords.ahk   Original AutoHotkey scripts
poe mini project/autoclicker.cpp               Original C++ autoclicker
poe_qol/
    config/        default.yaml, profiles, slot profiles, map mod list
    src/poe_qol/
        core/      config, shared state, logging
        engine/    Macro base class, registry, scheduler
        macros/    one file per macro
        input/     global hotkeys and input sending
        vision/    screen capture, template matching, window lookup
        trade/     trade-site query builder and map search
        ui/        Qt main window and tab widgets
    tests/
    run.bat, run-admin.bat
```
