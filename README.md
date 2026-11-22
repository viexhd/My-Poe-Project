# My PoE Project: poe_qol

A desktop quality-of-life companion for **Path of Exile**, built with Python and PySide6. It brings map-search trade links, inventory and stash slot tools, calibration and overlays together in one window, and is being developed into a fuller companion app. The roadmap is in [`docs/`](docs/).

> **This product isn't affiliated with or endorsed by Grinding Gear Games in any way.**

> ⚠️ **Compliance notice: read this before using the macros.**
> GGG's published macro rules (<https://www.pathofexile.com/developer/docs>) forbid timer-driven input and allow at most **one game action per key press**. Three existing macros break those rules: **Life flask** (timer) and **Inventory / Map Stash dump** (up to 60–72 clicks per press). They are kept unchanged pending a decision on how to replace them. Use them at your own risk. See [`docs/COMPLIANCE_REVIEW.md`](docs/COMPLIANCE_REVIEW.md) for the assessment and the proposed compliant replacements.

## Features

| Tab | What it does | Compliance |
|---|---|---|
| **Macros** | Global on/off switch, per-macro toggles and hotkeys. **F12** emergency stop is always bound, and **Pause** toggles everything. | Stop and Pause send no game input ✅ |
| **Macros → Life flask** | Presses your flask key every 4–5 s while toggled on. | ❌ timer-driven |
| **Inventory** | Clickable 12×5 grid, named slot profiles, click-through overlay that highlights the selected slots, cursor-and-hotkey calibration. F1/F2 runs the Ctrl-click dump. | Overlay and calibration ✅; dump ❌ |
| **Map Stash** | Same grid tools for a 12×6 map stash tab (F3/F4). | Same as Inventory |
| **Map Search** | Pick map mods to exclude, with presets (RF Safe, No Reflect…), rarity, corrupted and tier. Opens the search on pathofexile.com/trade. | ⚠️ uses the trade site's internal search API; see the compliance doc |
| **Coordinate picker** | Ctrl+Alt+C saves the cursor position, Ctrl+Alt+V lists the saved positions. | ✅ |

**Under the hood**

- **Plugin-style macros.** One file in `src/poe_qol/macros/`: subclass `Macro` and add `@register`.
- **Layered YAML config.** `config/default.yaml`, then a profile (`config/profiles/*.yaml`), then your personal overrides (`config/user.yaml`, written by the UI and ignored by git).
- **Window-relative calibration**, so grid positions survive moving the game window.
- **Input** goes through `pydirectinput` (SendInput scancodes). Global hotkeys use `keyboard`. The optional OpenCV/mss template anchor is off by default.

## Requirements

- Windows 10/11
- Python **3.11+** (tested on 3.12 and 3.14)
- PoE in **windowed** or **windowed fullscreen** mode, for the overlay

## Install and run

### Quick start

Double-click **`poe_qol/run.bat`**. On first launch it creates `poe_qol/.venv`, installs `requirements.txt` and the package, then starts the app.

PoE usually runs elevated, and Windows blocks input and hotkeys from non-elevated programs. If hotkeys do nothing in game, use **`poe_qol/run-admin.bat`**.

### Manual setup

```powershell
cd poe_qol
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt   # full install (includes the optional vision extra)
pip install -e .
python -m poe_qol                 # or: poe-qol
```

Dependency options:

| Command | Installs |
|---|---|
| `pip install -e .` | Core only: PySide6, PyYAML, keyboard, pydirectinput-rgx |
| `pip install -e .[vision]` | Adds numpy, opencv-python and mss (only needed for `anchor_template`) |
| `pip install -r requirements-lock.txt` then `pip install -e . --no-deps` | The exact verified versions |

## Configuration

| File | Purpose | Edit it? |
|---|---|---|
| `poe_qol/config/default.yaml` | Every setting with comments (hotkeys, timings, grid geometry, trade league) | Yes, but prefer a profile or the UI |
| `poe_qol/config/profiles/<name>.yaml` | Partial overrides. `app.profile` in `default.yaml` picks one (`mapping`, `bossing`). | Yes |
| `poe_qol/config/user.yaml` | Written by the UI: calibration, slot selections, Map Search state. **Not tracked by git.** | Usually not |
| `poe_qol/config/map_mods.yaml` | Map Search mod catalogue (trade stat ids, categories, presets) | Yes, when stat ids change between leagues |
| `poe_qol/config/slot_profiles*/` | Named slot selections saved from the UI | Via the UI |
| `poe_qol/logs/` | Rotating log file and captured coordinates. **Not tracked.** | No |

Known limitation: the app must be started from the `poe_qol` folder (`run.bat` does this), because some config paths resolve against the working directory. A fix is planned; see [`docs/TECHNICAL_AUDIT.md`](docs/TECHNICAL_AUDIT.md) §3.2.

## Development

```powershell
# run the tests (from the repo root)
poe_qol\.venv\Scripts\python -m unittest discover -s poe_qol/tests -v
```

- Architecture, the macro plugin guide and the Map Search data format are in [`poe_qol/README.md`](poe_qol/README.md).
- Before adding features, read [`docs/COMPLIANCE_REVIEW.md`](docs/COMPLIANCE_REVIEW.md). No feature may run on a timer against the game or do more than one game action per key press.

## Documentation

| Document | Contents |
|---|---|
| [`docs/RESEARCH_REPORT.md`](docs/RESEARCH_REPORT.md) | Survey of community tools, design lessons, feature ideas |
| [`docs/TECHNICAL_AUDIT.md`](docs/TECHNICAL_AUDIT.md) | Architecture review, bugs, technical debt, refactoring plan |
| [`docs/FEATURE_ROADMAP.md`](docs/FEATURE_ROADMAP.md) | Prioritised roadmap and final recommendations |
| [`docs/UI_UX_PROPOSAL.md`](docs/UI_UX_PROPOSAL.md) | Design system, navigation, layouts |
| [`docs/COMPLIANCE_REVIEW.md`](docs/COMPLIANCE_REVIEW.md) | GGG policy and per-feature risk assessment |
| [`docs/WEALTHY_EXILE_INTEGRATION.md`](docs/WEALTHY_EXILE_INTEGRATION.md) | Wealthy Exile integration feasibility and proposal |
| [`docs/REPOSITORY_AUDIT.md`](docs/REPOSITORY_AUDIT.md) | What the cleanup changed and why |
| [`docs/VERIFICATION_REPORT.md`](docs/VERIFICATION_REPORT.md) | What was tested, known issues |

## Repository layout

```
docs/                     research, audit, roadmap and design documents
legacy/                   archived original AHK/C++ scripts (reference only, not used)
poe_qol/
    config/               default.yaml, profiles, slot profiles, map mod catalogue
    src/poe_qol/
        core/             config, shared state, logging
        engine/           Macro base class, registry, scheduler
        macros/           one file per macro (auto-discovered)
        input/            global hotkeys, input sending
        vision/           screen capture, template matching, window lookup
        trade/            Map Search query builder and trade URL
        ui/               Qt main window and tab widgets
    tests/                unittest suite
    pyproject.toml        package metadata and dependencies
    requirements*.txt     full install / exact lock
    run.bat, run-admin.bat
```
