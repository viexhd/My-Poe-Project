# poe_qol: developer notes

This is the developer guide. For the user guide, install steps and the compliance notice, see the [root README](../README.md).

> This product isn't affiliated with or endorsed by Grinding Gear Games in any way.

## Stack

* **PySide6** for the UI.
* **pydirectinput-rgx** for input: `SendInput` with scancodes, which PoE accepts.
* **keyboard** for global hotkeys (a `WH_KEYBOARD_LL` hook).
* Optional **OpenCV + mss + numpy** (`pip install -e .[vision]`) for the template-match anchor. These are imported lazily, so the app runs without them.

## Layout

```
config/                 YAML config: default + profiles + slot profiles + map_mods
logs/                   log file + captured coords (runtime, git-ignored)
src/poe_qol/
    app.py              composition root: config → state → input → engine → UI
    core/               ConfigStore (layered YAML), AppState (pub-sub + kill switch), logger
    input/              HotkeyRouter, InputSender
    vision/             mss capture, OpenCV detectors, Win32 window lookup
    engine/             Macro ABC, @register registry, Scheduler
    macros/             one file per macro (plugin-style, auto-discovered)
    trade/              map_query (MapDataset, build_map_query), builder (build_url)
    ui/                 MainWindow, SlotSelector + overlay, CalibrateDialog, MapSearchWidget
tests/                  unittest suite
```

## Config layering

`default.yaml`, then `profiles/<app.profile>.yaml`, then `user.yaml`, deep-merged in that order. All code reads config through `ConfigStore.get("dot.path")`. The UI persists selected keys with `ConfigStore.save_user_overrides([...])`.

## Adding a macro

1. Add a file under `src/poe_qol/macros/`.
2. Subclass `Macro`, set `NAME` and `HOTKEYS`, and decorate the class with `@register`.
3. Add a `macros.<name>` section in `config/default.yaml`.

`Scheduler.load()` discovers it on the next launch.

**Compliance rule for new macros:** one manual key press may produce **at most one** action that interacts with the game, and nothing may be triggered by a timer, file change or screen read. See [`docs/COMPLIANCE_REVIEW.md`](../docs/COMPLIANCE_REVIEW.md).

## Safety

* `F12` emergency stop is always bound, with a Qt in-window fallback for when the global hook is blocked by UIPI.
* `Pause` toggles the master switch.
* Sweeps use interruptible waits (`Event.wait`), so F12 aborts mid-delay. Modifiers are released in `finally`.
* Re-entry is guarded in the `Macro` base class.

## Map Search

`config/map_mods.yaml` (schema **version 2**) defines:

* `item_types`: dropdown entries, mapping to `type_filters.category` and `map_filters.map_tier`
* `categories`: section order and colour
* `mods`: `id`, `name`, `category`, trade `stat_id`, search `tags`
* `presets`: named sets of excluded mod ids
* `defaults`: rarity and corrupted filters

`build_map_query` emits a single `count` stat group with `value.max = 0` (*none of these mods*), the same shape the trade site produces. `build_url(mode="post")` POSTs to the trade search API and returns the hash URL. `mode="copy"` builds an offline `?q=` URL for inspection.

When GGG changes a stat id between leagues, edit `map_mods.yaml`. No Python changes are needed. The POST path also strips any stat id the API reports as unknown and retries.

## Visual slot selector

The **Inventory** and **Map Stash** tabs render a config-driven grid of toggle buttons. Selection is written to `macros.<name>.selected_slots`. They provide:

* **All / None / Invert** bulk actions.
* Named profiles under `slot_profile_dir`, applied with `active_slot_profile`.
* **Show overlay**: a frameless, always-on-top, click-through window highlighting the selected slots at their real screen coordinates.
* **Calibrate…**: hover the top-left, top-right and bottom-left slots and press F8 at each. The app computes origin and cell size across the full grid and can store a window-relative offset.

## Tests

```
python -m unittest discover -s poe_qol/tests -v
```

* `test_map_query.py`: `MapDataset` loading of the shipped catalogue, `build_map_query` payload shape, `build_url` copy mode, stale-stat stripping.
* `test_inventory_grid.py`: serpentine and row-major grid generation, slot filtering.
