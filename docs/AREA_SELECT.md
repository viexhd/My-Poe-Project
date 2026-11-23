# Alt+Drag Area Selection

Hold **Alt**, press the left mouse button over the inventory and drag. A rectangle follows the cursor, and the slots whose centres are inside it light up with a running count. Release the button to finish, or press **Esc** to cancel. What happens next depends on the transfer mode:

| Mode | What happens after you release | GGG's macro rules |
|---|---|---|
| **Manual** (default) | The selected slots stay highlighted and numbered in a suggested click order. You Ctrl-click each one yourself. Each slot is ticked off as you click it, and the highlight clears when you're done, after 30 s, on Esc, or when you start a new selection. | ✅ Sends no input. One click from you is one game action. |
| **Experimental** | The app Ctrl-clicks every selected slot for you. | ❌ **Not compliant.** One gesture becomes many game actions. Off by default, and runs only after you accept a warning. See [`COMPLIANCE_REVIEW.md` §7](COMPLIANCE_REVIEW.md#7-update-2026-11-23-altdrag-area-selection). |

This replaces the retired F1/F2 "inventory dump" sweep (`legacy/poe_qol_macros/inventory_dump.py`). The slot grid on the Inventory tab, its profiles and its overlay are unchanged and still work.

## Setup

1. **Calibrate the inventory grid.** Open the **Inventory** tab and click **Calibrate…**. Hover the centre of the top-left, top-right and bottom-left slots in PoE and press F8 on each. Keep "Save as window-relative" on `top_right`. Calibration now also records the game window size, so the grid scales when you change resolution. Recalibrate once after updating, so this is recorded.
2. Open the **Area Select** tab. It's enabled by default. Choose the modifier (Alt, Ctrl+Alt or Alt+Shift) and which grids it works on (inventory, and optionally the map stash tab).
3. Run PoE in **windowed** or **windowed fullscreen** mode, so the overlay can draw over it.
4. If PoE runs as administrator, start the app with `run-admin.bat`. Otherwise Windows hides PoE's mouse input from the app.

## Using it

- **Start** the drag inside the calibrated grid, or up to `start_margin_px` (12 px) outside it. Alt+clicks anywhere else go to the game as usual, so you can still pick up ground loot with item labels shown.
- **Drag** in any direction. You can drag past the edge of the grid: only slot centres inside the rectangle count. If you don't move, or move less than 6 px, the click selects the one slot under the cursor.
- **Cancel** with **Esc**. The drag is also cancelled if PoE loses focus (Alt+Tab, a click on another window).
- **Empty slots.** With "Detect empty / occupied slots" on, the app takes one screenshot of the grid when you press, and marks slots as item (solid gold) or empty (dashed). With "Leave empty slots out" on, empty slots don't end up in the plan. Slots that can't be classified count as unknown and stay in.
- **Stopping an experimental run:** press **F12** or **Esc**, move the mouse more than 25 px yourself, or switch windows. Ctrl is always released afterwards.

## Settings

Everything is in the **Area Select** tab and stored under `area_select:` in `config/user.yaml`. Defaults with comments are in `config/default.yaml`.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Feature switch. When off, the mouse hook isn't installed. |
| `modifier` | `alt` | Key(s) to hold: `alt`, `ctrl+alt` or `alt+shift`. The match is exact (Ctrl+Alt is not Alt). `ctrl` alone isn't allowed, because manual mode relies on your Ctrl-clicks. |
| `grids` | `[macros.inventory_dump]` | Calibrated grids the gesture works on. A drag picks the grid with the most selected slots. |
| `macros.inventory_dump.grid.cols / rows` | 12 / 5 | Grid dimensions (also editable in the tab) |
| `macros.inventory_dump.grid.bounds` | `null` | Optional `[left, top, right, bottom]` outer edges in screen px. Overrides `origin` + `cell_size` when there is no window-relative calibration. |
| `start_margin_px` | 12 | How far outside a grid a drag may start |
| `click_threshold_px` | 6 | Drags smaller than this select the slot under the cursor |
| `order` | `column_serpentine` | Click order: down column 1, up column 2, … or `row_major` |
| `detect_items` / `skip_empty` | `true` / `true` | Empty-slot detection, and whether to drop empty slots |
| `occupancy.std_min` / `mean_min` | 14 / 70 | Detection thresholds (luminance std-dev / mean). Tune them with debug mode on. |
| `manual_clear_after_s` | 30 | Manual highlights clear after this many seconds (0 = never) |
| `overlay.visible` / `fill_opacity` / `border_px` | `true` / 0.18 / 2 | Overlay look |
| `debug` | `false` | Draws grid bounds and logs the selection and each slot's detection statistics |
| `transfer_mode` | `manual` | `manual` or `experimental` |
| `experimental.acknowledged` | `false` | Set when you accept the warning in the tab. Experimental mode runs as manual until then. |
| `experimental.click_delay_ms` | 60 | Pause between clicks (minimum 20) |
| `experimental.max_slots` | 60 | Cap per gesture |
| `experimental.modifier_release_timeout_ms` | 1500 | How long to wait for you to release Alt before clicking (otherwise PoE would get Ctrl+Alt+click) |
| `experimental.abort_move_px` | 25 | A real mouse move this far from the cursor aborts the run |

## Architecture

```
 OS hook thread                                   Qt main thread
 ─────────────────────────────────────            ─────────────────────────────────────────
 input/mouse_hook.py                              area_select/controller.py
   LowLevelInputHook (WH_MOUSE_LL,                  AreaSelectController
   WH_KEYBOARD_LL) ──► area_select/gesture.py        ├─ selection.resolve_selection ◄─ grid.py
                        GestureGate                  ├─ occupancy.classify_slots (optional)
                        (returns "swallow?")         ├─ overlay_model ──► ui/area_select_overlay.py
                          │  queued Qt signals       └─ TransferStrategy (transfer.py)
                          └────────────────────────►       ├─ ManualTransfer         (no input)
                                                           └─ experimental/bulk_ctrl_click.py
                                                              (lazy import, NOT compliant)
 settings: area_select/settings.py ◄── config/default.yaml + user.yaml ◄── ui/area_select_widget.py
```

| Concern | Module | Notes |
|---|---|---|
| Input handling | `input/mouse_hook.py` | ctypes Win32 low-level hooks on their own thread. Swallows only the gesture's own button down/up and Esc during a drag. Never sends input. |
| Selection state | `area_select/gesture.py`, `selection.py` | Pure Python, unit-tested. The gate ignores injected events, so the experimental clicks can't start a drag. |
| Coordinate mapping | `area_select/grid.py` | `GridGeometry` (slot centre/rect, `slot_at`, `slots_in_rect`) and `resolve_geometry` (window-relative + resolution scaling, bounds, absolute). The Inventory tab overlay now uses it too. |
| Item detection | `area_select/occupancy.py` | numpy + mss (`vision` extra, already in the venv). Missing deps mean "unknown", not an error. |
| Overlay | `area_select/overlay_model.py`, `ui/area_select_overlay.py` | The model is plain data. The window is click-through, never takes focus, hides when idle, is excluded from screen capture, and is DPI-aware. |
| Transfer | `area_select/transfer.py`, `experimental/bulk_ctrl_click.py` | `TransferStrategy.start(TransferPlan, listener)` takes the grid plus ordered `(row, col)` slots. Each run is tagged with an id, so a stopping run can't clear a newer selection. |
| Configuration | `area_select/settings.py`, `ui/area_select_widget.py` | Validated and clamped on load, saved to `user.yaml` on every change, and pushed to the controller live. |

To add another strategy (for example a "next slot" hotkey that only moves the highlight), subclass `TransferStrategy` and return it from the controller's `strategy_factory`.

## Limitations

- **Windows only.** The hook, focus check and capture exclusion use Win32.
- **Calibration-based.** The app doesn't know where PoE draws the inventory. It relies on your calibration. Window-relative calibration plus the recorded window size handles moving the window and changing resolution (UI scaled by window height, as PoE does). If PoE's UI scale option or aspect ratio changes, recalibrate.
- **Closed inventory.** The app can't tell whether the inventory panel is open. An Alt+drag that starts where the inventory would be is swallowed even when the panel is closed. A plain Alt+click there without dragging still selects one slot rather than reaching the game.
- **Item detection is a heuristic.** Very dark items can read as empty, and busy backgrounds can read as occupied. Tune the thresholds with debug mode, or turn "Leave empty slots out" off.
- **Python hook latency.** The hook callback runs Python on every mouse event. If the app's UI thread is busy for a long time, mouse input can stutter, and Windows drops a hook that times out repeatedly. Restarting the app reinstalls it.
- **Exclusive fullscreen.** The overlay can't draw over exclusive fullscreen.
- **Experimental mode** depends on PoE accepting SendInput clicks (`run-admin.bat` if PoE is elevated) and on the inventory staying open. It stops when focus is lost, but it can't detect a closed panel.

## Testing

Automated (`poe_qol\.venv\Scripts\python -m unittest discover -s poe_qol/tests`):

| Scenario | Test |
|---|---|
| One slot, adjacent block, whole row, whole column, whole inventory | `test_area_grid.SlotsInRectTests` |
| Reverse drag directions | `RectTests.test_from_points_normalises_any_drag_direction`, `SlotsInRectTests.test_reverse_drag_matches_forward_drag` |
| Partly / fully outside the grid | `test_partially_outside_the_grid_is_clipped`, `test_fully_outside_selects_nothing`, `GestureGateTests.test_drag_may_end_outside_the_grid` |
| Empty slots | `OccupancyTests`, `ControllerTests.test_empty_slots_skipped_when_detection_available` |
| Cancel (Esc, external) | `GestureGateTests.test_escape_cancels_and_is_swallowed`, `ControllerTests.test_escape_cancel_clears_overlay` |
| Resolution change | `ResolveGeometryTests.test_resolution_change_scales_offset_and_cell_by_height` |
| Grid configuration change | `ResolveGeometryTests.test_grid_dimensions_come_from_config`, `test_bounds_override_origin` |
| Focus loss during selection / transfer | `GestureGateTests.test_losing_focus_mid_drag_cancels`, `ExperimentalTransferTests.test_focus_loss_aborts` |
| Modifier gating, loot Alt+click untouched | `GestureGateTests` |
| Experimental safety rails (acknowledgement, F12, Ctrl released, mouse takeover, Alt release) | `test_area_transfer.ExperimentalTransferTests` |
| Defaults and isolation of experimental code | `test_compliance.AreaSelectDefaultsTests` |
| Hook installs and removes on Windows | `test_area_settings.HookSmokeTests` |

Not automatable here, and still needing an in-game check: the drag over a real PoE window, overlay alignment at your resolution and DPI scaling, detection thresholds on real item art, and whether PoE accepts the experimental clicks.
