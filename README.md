# Twice Corrupted

A desktop quality-of-life companion for **Path of Exile**, built with Python and PySide6. It brings map-search trade links, inventory and map-stash slot highlighting, calibration and overlays together in one window, and is being developed into a fuller companion app. The roadmap is in [`docs/`](docs/).

**Repository:** <https://github.com/viexhd/Twice-Corrupted> (formerly `My-Poe-Project`; old links redirect).

> **This product isn't affiliated with or endorsed by Grinding Gear Games in any way.**

**Compliance first.** Twice Corrupted follows GGG's published rules for third-party tools (<https://www.pathofexile.com/developer/docs>). It never reads or changes game memory or game files. Nothing sends game input on a timer, and no key press performs more than one game action. The earlier life-flask timer and bulk Ctrl-click "dump" macros were retired for breaking those rules. See [`docs/COMPLIANCE_REVIEW.md`](docs/COMPLIANCE_REVIEW.md). GGG doesn't certify any third-party tool, so use any tool at your own discretion.

## Features

| Tab | What it does | Game input |
|---|---|---|
| **Macros** | Master on/off switch, per-macro toggles and hotkeys, **F12** emergency stop, **Pause** master toggle | None |
| **Inventory** | Clickable 12×5 grid, named slot profiles, a click-through **overlay** that highlights the chosen slots over the game, cursor-and-hotkey **calibration**. You click the highlighted slots yourself. | None |
| **Map Stash** | The same highlighter for a 12×6 map stash tab | None |
| **Map Search** | Pick map mods to exclude, with presets (RF Safe, No Reflect…), rarity, corrupted and tier. Opens the search on pathofexile.com/trade. | None. It uses the trade site's search API (see the compliance doc §2) |
| **Coordinate picker** | Ctrl+Alt+C saves the cursor position, Ctrl+Alt+V lists the saved positions | None |
| **Help → About** | Version and the GGG disclaimer | — |

**Under the hood**

- **Plugin-style macros.** One file in `src/poe_qol/macros/`: subclass `Macro` and add `@register`.
- **Layered YAML config.** `config/default.yaml`, then a profile (`config/profiles/*.yaml`), then your personal overrides (`config/user.yaml`, written by the UI and ignored by git).
- **Window-relative calibration**, so the overlay follows the game window.

## Requirements

- Windows 10/11
- Python **3.11+** (tested on 3.12 and 3.14)
- PoE in **windowed** or **windowed fullscreen** mode, for the overlay

## Install and run

### Get the code

```powershell
git clone https://github.com/viexhd/Twice-Corrupted.git
cd Twice-Corrupted
```

If you cloned the repo under its old name, point the existing clone at the new URL:

```powershell
git remote set-url origin https://github.com/viexhd/Twice-Corrupted.git
```

### Quick start

Double-click **`poe_qol/run.bat`**. On first launch it creates `poe_qol/.venv`, installs the dependencies and the app, then starts it.

PoE usually runs elevated, and Windows blocks global hotkeys from non-elevated programs. If hotkeys (F12, Ctrl+Alt+C, the calibration key) do nothing while the game has focus, use **`poe_qol/run-admin.bat`**.

### Manual setup

```powershell
cd poe_qol
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m poe_qol                 # or: twice-corrupted
```

| Command | Installs |
|---|---|
| `pip install -e .` | Runtime: PySide6, PyYAML, keyboard, pydirectinput-rgx |
| `pip install -e .[vision]` | Adds numpy, opencv-python and mss (not used by any shipped feature yet) |
| `pip install -r requirements-lock.txt` then `pip install -e . --no-deps` | The exact verified versions |

> **Naming:** the product and distribution are called **Twice Corrupted** (`twice-corrupted`). The Python import package and the `poe_qol/` folder keep their original name for now, so existing installs and the unmerged design branch keep working.

## Configuration

| File | Purpose | Edit it? |
|---|---|---|
| `poe_qol/config/default.yaml` | Every setting with comments (hotkeys, grid geometry, trade league) | Yes, but prefer a profile or the UI |
| `poe_qol/config/profiles/<name>.yaml` | Partial overrides. `app.profile` in `default.yaml` picks one. | Yes |
| `poe_qol/config/user.yaml` | Written by the UI: calibration, slot selections, Map Search state. **Not tracked by git.** | Usually not |
| `poe_qol/config/map_mods.yaml` | Map Search mod catalogue (trade stat ids, categories, presets) | Yes, when stat ids change between leagues |
| `poe_qol/config/slot_profiles*/` | Named slot selections saved from the UI | Via the UI |
| `poe_qol/logs/` | Rotating log file and captured coordinates. **Not tracked.** | No |

The inventory and map-stash grids still live under `macros.inventory_dump` and `macros.map_stash_dump` in config. The names are historical and kept so your existing calibration carries over.

Known limitation: start the app from the `poe_qol` folder (`run.bat` does this), because some config paths resolve against the working directory. A fix is planned in [`docs/TECHNICAL_AUDIT.md`](docs/TECHNICAL_AUDIT.md) §3.2.

## Development

```powershell
# run the tests (from the repo root)
poe_qol\.venv\Scripts\python -m unittest discover -s poe_qol/tests -v
```

- Architecture, the macro plugin guide and the Map Search data format are in [`poe_qol/README.md`](poe_qol/README.md).
- `tests/test_compliance.py` enforces the compliance decisions. Read [`docs/COMPLIANCE_REVIEW.md`](docs/COMPLIANCE_REVIEW.md) before adding a feature.

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
Twice-Corrupted/
docs/                     research, audit, roadmap and design documents
legacy/                   archived scripts and retired macros (reference only, not used)
poe_qol/
    config/               default.yaml, profiles, slot profiles, map mod catalogue
    src/poe_qol/
        core/             config, shared state, logging
        engine/           Macro base class, registry, scheduler
        macros/           one file per macro (auto-discovered)
        input/            global hotkeys, input sending
        vision/           window lookup (+ optional capture / template matching)
        trade/            Map Search query builder and trade URL
        ui/               Qt main window and tab widgets
    tests/                unittest suite
    pyproject.toml        package metadata and dependencies
    requirements*.txt     runtime install / exact lock
    run.bat, run-admin.bat
```
