# Verification Report

Date: 2026-11-23 · Branch: `chore/research-audit-cleanup` · Machine: Windows 11 Pro, no PoE client running.

**Principle:** a feature counts as "verified" only if a check actually exercised it. Launching the app is not proof that a feature works.

## 1. Tests performed

| # | Check | How | Result |
|---|---|---|---|
| 1 | **Unit tests, before the cleanup** | `python -m unittest discover -s poe_qol/tests` on `main` | ❌ 13 run, **4 failures + 1 error**. All in the v1 `BuilderTests`, caused by the stale schema. |
| 2 | **Unit tests, after the cleanup** | Same command, existing `.venv` (Python 3.14.2, PySide6 6.11.0) | ✅ **12 run, 0 failures** |
| 3 | **Characterisation tests written before removing dead code** | `test_map_query.py` run against the *unchanged* code first | ✅ 10/10, then still 10/10 after the removal |
| 4 | **All module imports** | Smoke script walks `poe_qol.*` with `pkgutil.walk_packages` | ✅ 30/30 (full install). ✅ 28/30 on core-only, where only `vision.capture` and `vision.detect` are skipped, as designed (they need the optional `numpy`/`cv2`). |
| 5 | **Entry point** | `poe_qol.app` imports. A fresh install created `Scripts\poe-qol.exe`, renamed to `twice-corrupted` in the addendum below. | ✅ |
| 6 | **Macro plugin discovery** | `Scheduler.load()` finds `coord_picker`, `inventory_dump`, `life_flask`, `map_stash_dump` | ✅ |
| 7 | **Global hotkey registration and cleanup** | After `load()`, 9 bindings / 9 `keyboard` handles, including `emergency_stop` and `toggle_global`. After `shutdown()`, 0 / 0. | ✅ Real `keyboard` hooks were installed and removed. The keys were not pressed. |
| 8 | **Config load / save** | On a temp copy of `config/`: load defaults, `set`, `save_user_overrides`, then reload. The override persists and the defaults still merge. | ✅ |
| 9 | **UI construction** | `MainWindow` built offscreen (`QT_QPA_PLATFORM=offscreen`). Tabs are `Macros, Inventory, Map Stash, Map Search`. The Map Search dataset loads 21 mods. | ✅ |
| 10 | **Fresh dependency install** | New venv on **Python 3.12.10**: `pip install -e .` (core), then tests and smoke, then `pip install -e .[vision]`, then smoke, then `pip check` | ✅ All pass. `pip check`: "No broken requirements found". It resolved **PySide6 6.12.0**, numpy 2.5.5, opencv 4.14.0 and mss 10.2.0, all newer than the lock file, and still passed. |
| 11 | **Vision stack** | In the existing venv: `Capture(1).grab()` gave a 1080×1920×3 frame. `match_template` on a cut-out patch returned score 1.0. `-W error::DeprecationWarning` was clean with mss 10.1.0. | ✅ |
| 12 | **`.gitignore`** | `git check-ignore -v` on `user.yaml`, `logs/`, `.venv`, `egg-info`. `default.yaml` is not ignored. | ✅ |
| 13 | **Packaging script** | None exists in the repo | N/A |
| 14 | **External integrations** | No live network calls were made by the tests. The trade POST path was **not** exercised. | ⚠️ Not verified |

The smoke script is not committed, because it lives in the session scratch directory. It's reproduced below so the checks can be re-run. **[R]** Commit it as `tests/test_smoke_offscreen.py` when CI is added.

<details><summary>Smoke script outline</summary>

1. Copy `config/` (minus `user.yaml`) to a temp dir and `chdir` there.
2. `pkgutil.walk_packages(poe_qol.__path__)` and import each module.
3. `ConfigStore(tmp)` → `set("trade.league", …)` → `save_user_overrides` → reload → assert.
4. `Scheduler(cfg, AppState(), InputSender(), HotkeyRouter()).load()` → assert the macro names and bindings.
5. `MainWindow(cfg, state, scheduler)` offscreen → assert the tab titles and `dataset.mods`.
6. `scheduler.shutdown()` → assert no bindings or handles remain.

No step calls `on_hotkey`, `trigger` or `InputSender.press/click`, so **no input is ever sent**.

</details>

## 2. Features verified vs. still needing manual testing

| Feature | Status | What's still needed (manual, with PoE running) |
|---|---|---|
| App start, tabs, config layering | ✅ automated | — |
| Hotkey bind/unbind | ✅ automated | Confirm F12 fires in game when elevated (`run-admin.bat`) |
| Map Search query building | ✅ automated (payload shape, copy URL) | Click **Open on trade** once to confirm the POST still returns a hash URL this league |
| Slot selector / profiles | ⚠️ UI built, not clicked | Toggle slots, save and delete a profile, restart, check persistence |
| Overlay | ❌ not exercised (needs the game window) | Show the overlay over PoE and move the window |
| Calibration dialog | ❌ not exercised | Run the three-point calibration |
| Inventory / map stash dump | ❌ **deliberately not exercised** (sends input; non-compliant) | — |
| Life flask | ❌ **deliberately not exercised** (sends input; non-compliant) | — |
| Coordinate picker | ⚠️ discovered and bound, not triggered | Press Ctrl+Alt+C / V |
| Template anchor | ⚠️ primitives verified, end-to-end not | Requires a template PNG |

## 3. Known issues (not fixed in this cleanup)

These are tracked in TECHNICAL_AUDIT §3 and roadmap P0.

1. The **non-compliant macros** (life flask, inventory and map stash dumps) are unchanged and awaiting your decision.
2. **Config paths resolve against the working directory** (§3.2). Start from `poe_qol/`, which `run.bat` does.
3. **Map Search networking** runs on the UI thread, retries up to 16 times and uses a **spoofed browser User-Agent** (§3.5, §3.6).
4. **F12 is unbound during calibration** (§3.7).
5. **Macros-tab edits aren't persisted** (§3.8).
6. **Config I/O doesn't specify UTF-8** and isn't atomic (§3.10).
7. **Window lookup** can match non-game windows titled "…Path of Exile…" (§3.4).
8. **`app.py` assumes a source checkout**, so a frozen or installed build won't find `config/` (§3.3).
9. **Design branch is unmerged**, with its own issues: an old poe.ninja route, a passive clipboard watcher, a spoofed UA, and an unhandled "Unknown item name" 400 in the log (§3.15).
10. `requirements.txt` resolves PySide6 6.12, which brings the `PySide6_WebEngine` and `PySide6_Pdf` add-on wheels (large). **[R]** Depending on `PySide6-Essentials` + `PySide6-Addons` instead of the `PySide6` meta-package could shrink installs. Test QtCharts availability first.

## 4. Remaining technical debt (summary)

User data in the source tree · no config schema or version · no shared HTTP client, rate limiter or cache · no page registry (tabs hard-coded) · inline stylesheets · daemon threads not joined on shutdown · no CI · no packaging or update pipeline. The ordered plan is in `FEATURE_ROADMAP.md` (M0–M1).

---

## Addendum: compliance retirement and rename (branch `feat/twice-corrupted-compliance`)

| # | Check | Result |
|---|---|---|
| A1 | **Red first.** `tests/test_compliance.py` written before the change | ❌ 8/8 failed for the expected reasons (retired macros registered, F1–F4 hotkeys in config, Dump buttons present, title `PoE QoL`, no About) |
| A2 | **Green.** Full suite after the change | ✅ 18 run, 0 failures (10 map-query + 8 compliance) |
| A3 | **Offscreen smoke** (temp config copy) | ✅ 27 modules import. Only `coord_picker` is registered (4 hotkey bindings, all unbound on shutdown). Window title `Twice Corrupted`. Help menu present. 4 tabs. 21 map mods. |
| A4 | **Backward compatibility with your real `config/user.yaml`** (read-only) | ✅ Saved `selected_slots`, `active_slot_profile`, map-stash `grid` and `origin_relative_to_window` overrides are all still applied |
| A5 | **Renamed distribution** in your `.venv` (Python 3.14): `pip uninstall poe_qol`, then `pip install -e . --no-deps`, then delete the stale git-ignored `src/poe_qol.egg-info` | ✅ `pip list` shows only `twice-corrupted 0.1.0` (editable). `Scripts\twice-corrupted.exe` exists. `pip check` clean. 18/18 tests. |
| A6 | **Fresh Python 3.12 venv** from the new `requirements.txt` (runtime only) plus `pip install -e .` | ✅ PySide6 6.12.0. **No numpy/opencv/mss pulled in.** `twice-corrupted.exe` created. 18/18 tests. Smoke 5/5 (vision modules correctly skipped as optional). `pip check` clean. |

Still manual: open the overlay over the running game and run the calibration once. The highlight-only flow sends no input, so there is nothing else to exercise.
