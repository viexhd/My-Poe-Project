# assets

`ui/branding.py` picks up `app_icon.png` (or `app_icon.ico`) from this
folder automatically at startup and applies it to both
`QApplication.setWindowIcon` and the main window.

## Quick path (recommended) — scripted build from a raw PNG

1. Save the mascot PNG (transparent background, ≥1024px) as
   `poe_qol/assets/piplup_source.png`.
2. Install the optional build dep once:
   ```
   pip install -e .[tools]       # or: pip install Pillow
   ```
3. Run the builder:
   ```
   python -m poe_qol.tools.build_icon
   ```

You get three files next to the source:

    app_icon_1024.png   # master, for store listings / README banners
    app_icon.png        # 512×512, loaded by the runtime UI
    app_icon.ico        # multi-res (16/24/32/48/64/128/256) for Windows

The script applies the "Option A" treatment from the design review:
10% internal padding, rounded square (18% corner radius), dark vertical
gradient, thin `#E8B057` gold ring, baked-in soft shadow.

## Recommended export for the Piplup mascot

1. Start from a 1024×1024 source PNG with transparent background.
2. Add 10–12% internal padding so the character doesn't touch the
   canvas edge — prevents clipping in Windows taskbar / macOS dock
   rounded masks.
3. Flatten onto a rounded square (18% corner radius) with a subtle
   vertical gradient `#0E1116 → #1C222C` so the icon reads on both
   dark and light OS themes.
4. Export:
   * `app_icon.png` – 512×512 (Qt uses this for X11/Wayland).
   * `app_icon.ico` – multi-resolution bundle (16, 24, 32, 48, 64,
     128, 256) for Windows taskbar + alt-tab clarity.
5. For an installer / store listing, additionally export 1024×1024
   PNG and `.icns` for macOS.

## Why this matters

Mascot icons are charming but Windows renders the icon at 16×16 in
the alt-tab list. Without padding and a solid contrast backing,
Piplup's light-blue head disappears against light wallpapers. The
gradient + corner-radius treatment is a 30-second Figma export and
makes the app feel like a finished product at every size.
