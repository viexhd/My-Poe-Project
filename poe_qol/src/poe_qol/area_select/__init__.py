"""Alt+drag area selection over the PoE inventory grid.

Layers (each module only depends on the ones above it):

    grid.py          screen <-> grid-slot mapping, calibration resolution
    selection.py     drag rectangle state + rectangle -> slot selection
    gesture.py       per-event gate: decides what is swallowed from the game
    occupancy.py     optional empty / occupied detection from a screenshot
    settings.py      typed view of the `area_select:` config section
    transfer.py      transfer interface + ManualTransfer (highlight-only)
    overlay_model.py what the overlay should draw (pure data)
    controller.py    Qt glue: hook -> gate -> selection -> overlay -> transfer

The OS hook lives in ``input/mouse_hook.py``, the painting in
``ui/area_select_overlay.py`` and the settings tab in
``ui/area_select_widget.py``. The experimental bulk Ctrl-click transfer
is isolated in ``poe_qol/experimental/`` and is only imported when the
user picks (and acknowledges) that mode. See docs/AREA_SELECT.md.
"""
