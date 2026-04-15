# assets

Drop the app icon here as `app_icon.png` (or `app_icon.ico`). It is
picked up automatically at startup by `ui/branding.py` and applied to
both `QApplication.setWindowIcon` and the main window.

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
