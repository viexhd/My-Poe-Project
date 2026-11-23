# Technical Audit

> **Update, 2026-11-23:** the product is now **Twice Corrupted**. The retired macros (`life_flask`, `inventory_dump`, `map_stash_dump`) referenced below now live in `legacy/poe_qol_macros/`. Findings about them (§3.7 "flask keeps pressing", §3.12 sweep threads) are moot for the shipped app.

Scope: every tracked file on `main` (commit `a0979ea`), plus the **unmerged** branch `origin/claude/design-review-icon-nS8OE` (4 commits, about +3,300 lines). I read the source itself rather than relying on the READMEs.

Tags: **[V]** verified by running or reading code (with the command or `file:line`), **[R]** recommendation, **[A]** assumption.

---

## 1. Existing architecture

```
app.py (composition root)
 ├─ core/config.py    ConfigStore: default.yaml ⊕ profiles/<p>.yaml ⊕ user.yaml (deep merge), dot-path get/set
 ├─ core/state.py     AppState: RLock'd key/value + pub-sub listeners + stop_event (kill switch)
 ├─ core/logger.py    RotatingFileHandler(logs/poe_qol.log) + console
 ├─ input/hotkeys.py  HotkeyRouter: wraps `keyboard.add_hotkey`, named bindings, collision warning
 ├─ input/sender.py   InputSender: wraps pydirectinput (SendInput scancodes), jitter, settle delay
 ├─ engine/macro.py   Macro ABC: guard(), start() on a daemon thread, cooperative stop
 ├─ engine/registry.py  @register + pkgutil discovery of poe_qol.macros.*
 ├─ engine/scheduler.py Scheduler: instantiates macros, binds hotkeys, emergency_stop / toggle_global
 ├─ macros/           life_flask, inventory_dump (GridDumpMacro), map_stash_dump, coord_picker
 ├─ vision/           mss capture, OpenCV template match, Win32 EnumWindows window lookup
 ├─ trade/            map_query (v2 visual builder, live), parser+builder (v1 regex, dead), build_url (live)
 └─ ui/               MainWindow (QTabWidget), SlotSelector + overlay, CalibrateDialog, MapSearchWidget,
                      TradeWidget (not mounted)
```

What the unmerged branch adds: `ui/styles.py` (QSS design tokens), `ui/branding.py` + `tools/build_icon.py` (app icon), `economy/ninja.py` + `economy/flipper.py` + `ui/flipper_widget.py` (currency flip ranking), `pricer/parser.py` + `pricer/search.py` + `ui/pricer_widget.py` (clipboard price check), and 2 new test files.

### Verdict on the brief's ten questions

| # | Question | Answer |
|---|---|---|
| 1 | Is the architecture scalable? | **Partly.** The layering is sound (config → state → input → engine → UI). Two things stop it scaling: there is no notion of a *page or tool* (tabs are hard-coded in `MainWindow.__init__`), and there is no service layer for network or persistence. |
| 2 | Is the macro plugin system modular enough? | **Yes, for macros.** `@register` + `pkgutil` discovery works, and `GridDumpMacro` reuse is good. But it only covers hotkey-driven input automation, and most future features are *not* macros. |
| 3 | Is UI separated from logic? | **Mostly.** `trade/` and `macros/` are Qt-free and unit-testable. Leaks: UI calls private engine methods (`scheduler._bind_hotkeys()` at `ui/main_window.py:165` and `ui/slot_selector.py:306`). The overlay re-implements origin resolution (`ui/slot_selector.py:344-361`) instead of calling the macro's `_resolve_origin`. |
| 4 | Duplicated implementations? | **Yes.** Two trade-query pipelines (v1 regex is dead). Origin resolution exists twice (macro and overlay). Each widget has its own inline stylesheet. `keyboard`/`pydirectinput` are imported directly by `CalibrateDialog` and `coord_picker` instead of going through `HotkeyRouter`/`InputSender`. |
| 5 | Unnecessary dependencies? | **Yes.** `opencv-python` and `numpy` (≈100 MB installed) plus `mss` exist only for `anchor_template`, which is `null` by default. They are already lazy-imported, so they can become an optional extra. |
| 6 | Performance bottlenecks? | Blocking network on the UI thread (§3.5). The overlay enumerates every top-level window every 250 ms (`ui/slot_selector.py:336-338`): cheap but wasteful. Nothing CPU-heavy otherwise. |
| 7 | Easy to extend? | For a new macro, yes. For a new *page* you must edit `MainWindow`. For a new network integration there is no shared HTTP client, rate limiter or cache, so every integration re-invents them (the branch already has two copies of the spoofed-UA header block). |
| 8 | Is config flexible enough? | The layered YAML is a good idea. Missing: schema/version, validation, path resolution, atomic writes, and a separate user-data location. |
| 9 | Security or reliability concerns? | Spoofed browser UA, retry storms against GGG, non-atomic config writes, path traversal in profile names, F12 unbound during calibration, and daemon threads that may skip `key_up`. Details in §3. |
| 10 | Bugs or incomplete features? | Yes. **5 of 13 tests fail**, there is CWD-dependent path resolution, a window-title false match, unused config keys and a dead `TradeWidget`. Details in §3. |

---

## 2. Code quality: what's good (keep it)

- **Composition root** in `app.py`. Dependencies are passed in, not imported as globals.
- **Cooperative cancellation.** Every wait in a sweep is `self._stop.wait(...)`, so F12 interrupts mid-delay (`macros/inventory_dump.py:181,224`). Modifiers are released in `finally` (`:227-232`).
- **Re-entrancy guard** at the base class (`engine/macro.py:52-62`).
- **Fallback F12** as a Qt `ApplicationShortcut` for when the global hook fails under UIPI (`ui/main_window.py:54-57`).
- **Corner-to-corner calibration** divides capture error by `(cols-1)` (`ui/calibrate_dialog.py:633-641`). This is a nice, non-obvious idea.
- **Data-driven map mods** (`config/map_mods.yaml` v2): stat ids live in data, not code.
- **Docstrings explain *why*** (for example why `count(max=0)` and why no `value` on inner filters).

---

## 3. Bugs and technical debt (prioritised)

### 3.1 Test suite is red [V]

```
> .venv\Scripts\python -m unittest discover -s poe_qol/tests
Ran 13 tests ... FAILED (failures=4, errors=1)
```

All five failures are in `BuilderTests`. They load `config/map_mods.yaml` through the **v1** `ModMap` (`map_mods:` + `aliases:` keys), but the file was migrated to **v2** (`mods:` / `presets:`). The v1 pipeline therefore resolves nothing. Root cause: the v1 pipeline is dead code and its tests weren't retired. **Fixed in this cleanup** (§6).

### 3.2 Paths resolve against the working directory, not the project root [V]

Several config paths are passed straight into `Path(...)`:

- `ui/map_search_widget.py:203`
- `ui/slot_selector.py:225`
- `macros/inventory_dump.py:106,154`
- `macros/coord_picker.py:40`

Run from the repo root, `config\map_mods.yaml` does not exist from CWD but does exist under the project root. That was verified by constructing `ConfigStore` from the repo root. It only works today because `run.bat` does `cd /d "%~dp0"`.

**[R]** Add `ConfigStore.path(key)` that resolves relative values against `root`. Better still, use the user-data directory (§5.4).

### 3.3 Packaging assumes a source checkout [V]

`app.py:19` sets `root = Path(__file__).resolve().parents[2]`. In an installed (non-editable) or frozen build, that points into `site-packages` or the bundle, so `config/` and `logs/` are not found. `pyproject.toml` also declared **no dependencies**, so `pip install .` produced a broken install. (Dependencies were added to `pyproject.toml` in this cleanup.)

**[R]** Use `importlib.resources` for bundled defaults and `QStandardPaths.AppDataLocation` for user data.

### 3.4 Window lookup can latch onto the wrong window [V by reading]

`vision/window.py:61-88` takes the **first visible window whose title matches the regex `Path of Exile`, case-insensitive, anywhere in the title**. A browser tab titled "… - Path of Exile", a PoB window, or this app's own future windows can come first in Z-order. The overlay and the window-relative origin then land in the wrong place.

**[R]** Match the game's window class. **[A]** It is believed to be `POEWindowClass`; verify with Spy++. Also use an anchored title (`^Path of Exile$` / `^Path of Exile 2$`) and prefer the foreground window.

### 3.5 Network I/O on the UI thread [V by reading]

`MapSearchWidget._build_url` (`ui/map_search_widget.py:440-457`) calls `build_url(mode="post")` synchronously. `_post_url` (`trade/builder.py:192-250`) can make **up to 16 POSTs**, each with a 10 s timeout. That can freeze the window for over two minutes, and it fires up to 16 requests that each return 4xx, which counts toward GGG's invalid-request threshold.

**[R]** Run network calls on a `QThreadPool` worker, send no automatic retries, and add a shared rate limiter.

### 3.6 Spoofed browser User-Agent [V]

`trade/builder.py:201-210`, and on the branch `pricer/search.py:56-62`, send a hard-coded Chrome UA because *"Cloudflare rejects generic User-Agents"*. GGG's docs require an identifiable `OAuth {clientId}/{version} (contact: …)` UA [V] <https://www.pathofexile.com/developer/docs>. See COMPLIANCE_REVIEW §2.

### 3.7 F12 is unbound during calibration [V by reading]

`ui/slot_selector.py:297` calls `scheduler.hotkeys.unbind_all()` for the whole time the calibration dialog is open. That removes **emergency_stop** too. If the life-flask loop is running, it keeps pressing `1` with no global kill switch. Only the Qt shortcut works, and only while our window has focus.

**[R]** Give `HotkeyService.suspend(except_={"emergency_stop"})` an explicit exception list.

### 3.8 Inconsistent persistence [V by reading]

Slot selections, calibration and Map Search state are written to `config/user.yaml`. **Macro enable checkboxes, hotkey edits and the flask interval are not**: `ui/main_window.py:88-90,101-102,158-160` only call `cfg.set`. They silently reset on restart.

### 3.9 Two sources of truth for "global enabled" [V by reading]

Both `cfg["app.global_enabled"]` and `state["global_enabled"]` exist. `Macro.guard()` reads cfg, while listeners subscribe to state, and `Scheduler`/`MainWindow` must remember to set both.

**[R]** Make `AppState` authoritative for runtime flags and keep config for persisted preferences only.

### 3.10 Config robustness [V]

- **Encoding.** `read_text()`/`write_text()` run with no `encoding=` (`core/config.py:42,47,50,74,82,95`). On this machine the locale encoding is **cp1252** (verified with `locale.getpreferredencoding()`), while `default.yaml` contains 20 non-ASCII UTF-8 bytes. Comments decode as mojibake today. Any future non-ASCII value (a league or profile name) will corrupt or fail. **[R]** Always pass `encoding="utf-8"`.
- **Corrupt or missing YAML** raises during `ConfigStore.__init__`, so the app won't start and shows no message.
- **Non-atomic writes** of `user.yaml` (`core/config.py:95`). A crash mid-write truncates the file. **[R]** Write to a temp file, then `os.replace`.
- **No schema or version**, so user overrides of removed keys linger forever.
- **`save_profile()`** (`core/config.py:70-74`) dumps the *entire merged* config (including user overrides) into a profile. It is unused, but a footgun.

### 3.11 Unsanitised file names [V by reading]

The slot-profile name from `QInputDialog` becomes `profile_dir / f"{name}.yaml"` (`ui/slot_selector.py:267-271`). Names like `..\..\x` or `con` escape the directory or fail on Windows. **[R]** Slugify the name and reject reserved names.

### 3.12 Daemon worker threads [V by reading]

Macro threads are `daemon=True` (`engine/macro.py:69-72`), and `Scheduler.shutdown()` signals stop but never joins. Closing the window mid-sweep can kill the thread before its `finally: key_up(ctrl)`, leaving Ctrl logically held. **[R]** Join with a timeout on shutdown, then send `key_up` for modifiers unconditionally (the emergency stop already does this).

### 3.13 Dead or unused code and config [V]

| Item | Evidence | Action taken |
|---|---|---|
| `ui/trade_widget.py` | Not imported anywhere except its own module (`grep TradeWidget`). `map_search_widget.py:3` says it "Replaces the old regex-style TradeWidget". | **Removed** |
| `trade/parser.py`, `ModMap`, `build_query` (`trade/builder.py`) | Only used by `TradeWidget` and the failing tests. The v1 data they need no longer exists in `map_mods.yaml`. | **Removed** (`build_url` kept, as it's live) |
| `hotkeys.toggle_ui` | Never read. | Documented, left in place |
| `input.backend`, `vision.capture_backend` | Never read (backend hard-coded). | Documented, left in place |
| `vision/detect.py: find_all, pixel_is` | Unused, but they're small, tested-by-inspection primitives. | Kept |

### 3.14 Repository hygiene [V]

- Root has no `.gitignore` (only `poe_qol/.gitignore`). **Added.**
- `git stash list` contains `stash@{1}` ("On main: GitHub Desktop"), which holds **6,289 files of `.venv/`**, about 1.6 M lines. **[R]** Drop it after confirming nothing else is in it: `git stash show --stat stash@{1}`. I did **not** touch any stash.
- Commit `b6fbfe8` "my settings" committed personal slot profiles (`config/slot_profiles/Inventory.yaml`, `config/slot_profiles_map_stash/123.yaml`). User data is mixed with shipped defaults. Kept, to avoid discarding your data, but see §5.4.
- Bytecode in `src/poe_qol/{economy,pricer}/__pycache__` and `ui/__pycache__/{branding,styles,flipper_widget,pricer_widget}*.pyc` is left over from checking out the design branch. It's ignored by git and harmless, but confusing.

### 3.15 The unmerged design branch [V]

`origin/claude/design-review-icon-nS8OE` holds the design system, Flipper and Pricer. Its last commit is from 2026-04-15, and today's GitHub Desktop stash shows it was checked out recently. Findings:

- `economy/ninja.py` calls `https://poe.ninja/api/data/currencyoverview`, the **old, undocumented** route. poe.ninja now documents `/poe1/api/economy/exchange/current/overview` [V] <https://poe.ninja/docs/api>.
- `pricer_widget.py` auto-queries on *every* `QClipboard.dataChanged` (`pricer.auto_price_on_copy: true`). Copying a password in another app would trigger a parse attempt. Non-item text should never leave the machine.
- `logs/poe_qol.log` shows a real failure: `trade API 400 … "Unknown item name"` from `pricer/search.py:178`. That's an unhandled parser or base-type mismatch.
- `styles.py` is a solid start on a token-based design system (see UI_UX_PROPOSAL).

**[R]** Rebase the branch onto this cleanup branch, apply the compliance fixes (honest UA, explicit hotkey, documented ninja endpoints), then merge. Don't develop the UI further on `main` until that's done, or the two will diverge.

---

## 4. Performance

| Area | Observation | Recommendation |
|---|---|---|
| Startup | `opencv`/`numpy` are lazy-imported (good). PySide6 import dominates. | Nothing needed. |
| Overlay | `EnumWindows` across all windows every 250 ms. | Cache the HWND and call `GetWindowRect(hwnd)` only, re-enumerating when the HWND becomes invalid. |
| Status bar | `QTimer` every 400 ms polls macro state. | Fine. Could become `AppState` signals later. |
| Network | Synchronous, with retries. | Use a worker pool with a shared rate limiter and ETag cache (§5.3). |
| Logging | Every hotkey fire logs at INFO. | Move to DEBUG once stable. |

---

## 5. Recommended refactoring (incremental, no rewrite) [R]

Keep **Python + PySide6**. Nothing in the research justifies a framework change. APT (Electron/Vue), Sidekick (Blazor in an Avalonia WebView) and Exile-UI (AHK) are each successful on very different stacks. What they share is architecture, not technology.

### 5.1 Target layout (adapted to what exists; avoids deep nesting)

```
poe_qol/src/poe_qol/
  app.py                 composition root (unchanged role)
  core/                  config, state, logger, paths (NEW), events
  engine/                Macro, registry, scheduler   (macros stay "plugins")
  input/                 hotkeys (→ HotkeyService), sender
  vision/                capture, detect, window
  services/      (NEW)   http (UA + rate limit + ETag cache + worker), storage (sqlite)
  integrations/  (NEW)   trade/, poe_ninja/, ggg_public/ (currency-exchange), wealthy_exile/ (CSV import)
  pages/         (NEW)   one module per sidebar page; registered like macros
  ui/                    shell (sidebar, header), theme (styles.py from branch), shared widgets
```

`trade/` moves under `integrations/` only when it's next touched. **Do not mass-move files**: it would conflict with the unmerged branch.

### 5.2 Page registry (the generalisation macros already prove)

```python
@register_page
class MapSearchPage(Page):
    ID, TITLE, GROUP, ICON = "map_search", "Map Search", "Trade", "search"
    def create(self, ctx: AppContext) -> QWidget: ...
```

`MainWindow` builds the sidebar from the registry. `AppContext` is a frozen dataclass of `cfg`, `state`, `hotkeys`, `http`, `storage` and `scheduler` (public API only). It replaces reaching into `scheduler._bind_hotkeys`.

### 5.3 Services

- **`HttpClient`** (one instance):
  - Honest UA: `poe_qol/<version> (contact: <configurable>)`.
  - Per-host token-bucket limiter seeded conservatively (APT seeds 1 request per 5 s for trade [V]) and updated from `X-Rate-Limit-*` headers.
  - Honour `Retry-After`.
  - ETag/`If-None-Match` disk cache.
  - All calls on `QThreadPool`, with results delivered via Qt signals.
  - No automatic retry on 4xx.
- **`Storage`**: stdlib `sqlite3` for time series (wealth snapshots, sessions, price history). YAML stays for human-edited settings only. That adds no dependency.

### 5.4 Configuration and user data

| Kind | Location |
|---|---|
| Shipped defaults (read-only) | package data: `poe_qol/defaults/default.yaml`, `map_mods.yaml` |
| User settings | `%APPDATA%\poe_qol\settings.yaml` (via `QStandardPaths`) |
| User slot profiles | `%APPDATA%\poe_qol\slot_profiles\…` |
| Logs, caches, DB | `%LOCALAPPDATA%\poe_qol\{logs,cache,data.sqlite}` |

- Migration on first run: if `poe_qol/config/user.yaml` or non-default slot profiles exist in the checkout, **copy** them (never move or delete) and log it.
- Validate with a small hand-written schema (dataclasses plus defaults). Pydantic isn't needed.
- On parse error: back up the bad file as `.corrupt-<ts>`, start from defaults, and show a banner.
- Add `config_version: 1` with ordered migration functions.

### 5.5 Hotkey management

`HotkeyService` replaces `HotkeyRouter`:

- A registry of **actions** (id, label, default combo, owner, "game-affecting" flag).
- Conflict detection *before* binding, shown inline in a Hotkeys page.
- `suspend(except_={"emergency_stop"})` and `resume()`.
- Optional per-page *scopes* (only active while the PoE window is foreground) to avoid hijacking F-keys in other apps.
- **Compliance guard:** an action flagged game-affecting may send at most one input event group per invocation. Enforce it in `InputSender` with a debug assertion and a unit test.

### 5.6 Error recovery and logging

- A global `sys.excepthook` plus Qt message handler writes to the log and shows a non-blocking toast.
- A "Copy diagnostics" button collects version, OS, last 200 log lines and redacted config.
- Log location goes to `%LOCALAPPDATA%`.

### 5.7 Testing

- Keep `unittest` (no new dependency). Add `QT_QPA_PLATFORM=offscreen` smoke tests that construct each page.
- Add a `tests/` fixture for `map_mods.yaml` v2 and characterisation tests for `build_map_query` (added in this cleanup).
- **CI:** a GitHub Actions `windows-latest` job that installs `requirements.txt` and runs unittest.

### 5.8 Packaging and updates

- PyInstaller **one-folder** build (`scripts/build.ps1`). One-file builds unpack to `%TEMP%` on every launch and trip antivirus heuristics more often. **[A]** That's common community experience and wasn't measured here.
- Updates: a user-initiated "Check for updates" that queries the GitHub Releases API and opens the release page. No silent self-update (it's simpler and avoids supply-chain risk).
- Code signing is optional. PoE Lurker uses SignPath's free OSS signing [V] <https://github.com/C1rdec/Poe-Lurker>.

---

## 6. Changes actually made in this cleanup (reviewable commits)

See `REPOSITORY_AUDIT.md` and `VERIFICATION_REPORT.md`. In short: root `.gitignore`, dependency manifests, removal of the dead v1 trade pipeline and `TradeWidget`, legacy scripts archived to `legacy/`, tests replaced with characterisation tests of live code, and docs. **No behaviour of any running feature was changed.** In particular the non-compliant macros are *untouched* until you approve the plan in COMPLIANCE_REVIEW §2.1.
