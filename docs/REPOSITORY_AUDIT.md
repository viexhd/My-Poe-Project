# Repository Audit and Cleanup

Branch: `chore/research-audit-cleanup`, based on `main` at `a0979ea`. Every change is a separate commit, so each one can be reviewed or reverted on its own.

## 1. Original structure (53 tracked files)

```
Life Flask.ahk                 legacy AHK: timer flask
inventory.ahk                  legacy AHK: 12×5 Ctrl-click sweep
getcoords.ahk                  legacy AHK: cursor coordinate capture
poe mini project/autoclicker.cpp   legacy Win32 C++ sweep GUI
README.md
poe_qol/
  .gitignore
  README.md
  pyproject.toml               (declared no dependencies)
  requirements.txt             (lower bounds only)
  run.bat, run-admin.bat
  config/
    default.yaml, map_mods.yaml (v2)
    profiles/{mapping,bossing}.yaml
    slot_profiles/{Inventory,maps_only}.yaml
    slot_profiles_map_stash/{.gitkeep,123.yaml}
  src/poe_qol/  (33 .py files: core, engine, input, macros, trade, ui, vision)
  tests/test_trade_parser.py   (5 of 13 tests failing)
```

Untracked or ignored, but present on disk:

- `poe_qol/.venv/`
- `poe_qol/config/user.yaml`
- `poe_qol/logs/poe_qol.log`
- `poe_qol/src/poe_qol.egg-info/`
- stale `__pycache__` from the unmerged design branch (`economy/`, `pricer/`, `ui/{branding,styles,flipper_widget,pricer_widget}`)

## 2. Categorisation

| Category | Files |
|---|---|
| Essential app code | `poe_qol/src/poe_qol/**` (except the dead files below) |
| Plugins | `src/poe_qol/macros/*.py`, discovered dynamically by `engine/registry.py: discover()` via `pkgutil` |
| Config | `config/default.yaml`, `config/profiles/*.yaml`, `config/map_mods.yaml` |
| Required data | `config/map_mods.yaml` (Map Search catalogue) |
| User data (committed) | `config/slot_profiles/Inventory.yaml`, `config/slot_profiles_map_stash/123.yaml` (commit `b6fbfe8` "my settings"), and `slot_profiles/maps_only.yaml` (an example) |
| User data (ignored) | `config/user.yaml`, `logs/` |
| Manifests | `pyproject.toml`, `requirements.txt` |
| Build / launch scripts | `run.bat`, `run-admin.bat` |
| Documentation | `README.md`, `poe_qol/README.md` |
| Tests | `poe_qol/tests/` |
| UI assets | none on `main`. The branch adds `assets/README.md` and an icon build script. `vision.template_dir: assets/templates` is configured, but the directory doesn't exist and `anchor_template` is `null`. |
| Deprecated | the four root-level legacy scripts, `ui/trade_widget.py`, `trade/parser.py`, v1 parts of `trade/builder.py` |
| Temporary / generated | the ignored items listed above |

## 3. How each removal was checked

For every candidate I checked:

1. **Static imports.** `grep` for the module and class names across `src/`, `tests/` and the unmerged branch (`git grep … origin/claude/design-review-icon-nS8OE`).
2. **Dynamic imports.** `registry.discover()` only walks `poe_qol.macros`, so nothing removed lives there.
3. **Config references.** `grep` in `config/*.yaml`. `trade.presets` and `trade.item_category` were read only by `TradeWidget`, and neither key exists in `default.yaml`.
4. **Packaging and runtime.** `run.bat` and `pyproject.toml` reference none of the removed files. There is no PyInstaller spec yet.
5. **Behaviour.** The removed code was unreachable from the UI. Characterisation tests for the *live* trade code were written first and passed before and after the removal.

## 4. Changes made

| Commit | Change | Reason |
|---|---|---|
| `docs: add research, …` | `docs/` (6 reports) | Phase 1–8 and 10 deliverables |
| `chore: archive legacy …` | `Life Flask.ahk`, `inventory.ahk`, `getcoords.ahk` and `poe mini project/autoclicker.cpp` moved to `legacy/`, with a README and a compliance warning | Superseded by poe_qol and referenced by nothing. **Moved, not deleted**, so they stay discoverable. Three of the four break GGG's macro rules. |
| `refactor(trade): remove dead v1 …` | Deleted `ui/trade_widget.py` and `trade/parser.py`. Removed `ModMap`, `build_query`, `_atom_filter` and `_group_stat` from `trade/builder.py`. Replaced `tests/test_trade_parser.py` with `test_map_query.py` (new characterisation tests) and `test_inventory_grid.py` (the existing grid tests, kept). | `TradeWidget` was never mounted. The v1 pipeline needed a `map_mods.yaml` schema that no longer exists, which is why 5 tests failed. Nothing on `main` or the design branch uses it. |
| `build: declare deps …` | `pyproject.toml` declares its dependencies (plus a `vision` extra and a `poe-qol` script). Version upper bounds in `requirements.txt`. New `requirements-lock.txt`. Root `.gitignore` replaces `poe_qol/.gitignore`. | `pip install .` used to install nothing. Heavy optional dependencies are now opt-in. Reproducible environment. One ignore file covering runtime data, secrets and IDE files. |
| `docs: update READMEs …` | Root and package READMEs rewritten. This audit and the verification report added. | Documentation matches the code. |

## 5. Files kept on purpose, and why

| File | Why it stays |
|---|---|
| `config/slot_profiles/Inventory.yaml`, `config/slot_profiles_map_stash/123.yaml` | **Your personal data.** Deleting it would silently discard it. **[R]** Move these into the planned per-user data directory (TECHNICAL_AUDIT §5.4) and remove them from git once that migration exists. |
| `config/slot_profiles_map_stash/.gitkeep` | Keeps the directory present for the default `slot_profile_dir`. |
| `vision/detect.py: find_all, pixel_is` and `capture.Region` | Unused today, but they are small, cheap primitives meant for macros, and `Region` is part of `Capture.grab()`'s signature. |
| `hotkeys.toggle_ui`, `input.backend`, `vision.capture_backend` config keys | Unused (TECHNICAL_AUDIT §3.13), but removing keys could break existing `user.yaml` expectations. They're documented as no-ops. Remove them with the config-schema work. |
| `trade/builder.py: build_url, _post_url, _strip_stat_id` | Live, used by Map Search. |
| The non-compliant macros | **Deliberately untouched.** Changing or removing them is a product decision awaiting your approval (COMPLIANCE_REVIEW §2.1). |
| `run.bat`, `run-admin.bat` | Primary launchers. |

## 6. Structural decisions

- **No mass move into `app/…`.** The brief's example layout would rename nearly every file, which would make rebasing the unmerged design branch (about 3,300 lines in 23 files) very painful. The current `poe_qol/src/poe_qol/{core,engine,input,macros,trade,ui,vision}` layout is already clean. Planned additions (`services/`, `integrations/`, `pages/`) slot in beside it (TECHNICAL_AUDIT §5.1).
- **`docs/` at the repo root** holds all design and audit documents.
- **`legacy/`** keeps the history readable without cluttering the root.
- **Runtime data separation** (moving `user.yaml`, logs and slot profiles to `%APPDATA%` / `%LOCALAPPDATA%`) needs code changes and a migration step, so it is **proposed, not done** (roadmap P0.3).

## 7. Things I did *not* touch (need your decision)

| Item | Recommendation |
|---|---|
| `git stash@{1}` ("On main: GitHub Desktop", April 2026) | It holds **6,289 files of `.venv/`**. Probably safe to drop after a look: `git stash show --stat stash@{1}`, then `git stash drop stash@{1}`. |
| `git stash@{0}` (design branch, today) | It holds `logs/ninja_cache/mirage.currency.json`, which is a cache. Probably safe to drop. |
| Branch `claude/design-review-icon-nS8OE` | Rebase onto this branch and merge (roadmap P0.2). |
| Stale `__pycache__` folders from the branch | Harmless and ignored. Delete them if you like: `Get-ChildItem -Recurse -Directory __pycache__ \| Remove-Item -Recurse`. |
