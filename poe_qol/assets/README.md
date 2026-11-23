# assets

Brand assets for **Twice Corrupted**. See [`docs/BRAND.md`](../../docs/BRAND.md) for the design direction.

| File | What | Used by |
|---|---|---|
| `brand/icon.svg` | **Source** artwork for the app icon (vector, self-contained) | `tools/build_brand.py` |
| `app_icon.png` | 512×512 render | Loaded at runtime by `ui/branding.py` (window and taskbar icon) |
| `app_icon.ico` | 16–256 px multi-size icon | Windows shortcuts and a future installer |
| `app_icon_1024.png` | 1024×1024 master render | Store and installer artwork |
| `banner.png` | 1600×400 README header | Root `README.md` |
| `social_preview.png` | 1280×640 | GitHub → repo **Settings → Social preview** (upload by hand) |

## Rebuilding

The PNG and ICO files are generated. Edit `brand/icon.svg` (or the banner code in `src/poe_qol/tools/build_brand.py`), then run:

```powershell
cd poe_qol
.venv\Scripts\python -m poe_qol.tools.build_brand
```

Only Qt is needed: QtSvg ships with PySide6, so there's no Pillow. Banner text uses Cinzel if it's installed, otherwise Constantia or Georgia. Commit the regenerated files together with the source change.
