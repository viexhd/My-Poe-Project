"""Build a polished app icon from a raw mascot PNG.

Option-A treatment from the design review:

    * Flatten source onto a 1024×1024 rounded square (18% corner radius).
    * 10% internal padding so the character doesn't kiss the edge.
    * Vertical dark gradient (#0E1116 → #1C222C) so the icon reads on
      both light and dark OS themes.
    * Thin gold (``#E8B057``) 1.5% ring inset from the edge as a subtle
      brand tie.
    * Export:
        assets/app_icon.png   – 512×512 (Qt uses this at runtime).
        assets/app_icon.ico   – multi-res bundle for Windows taskbar.
        assets/app_icon_1024.png – master for stores / installers.

Usage
-----

    # 1. Put your raw square PNG (ideally >=1024, transparent bg) at:
    #    poe_qol/assets/piplup_source.png
    # 2. Run:
    python -m poe_qol.tools.build_icon
    # 3. Commit the generated files.

The script is deliberately dependency-light (Pillow only) so it can
live in the main repo without bloating the runtime install. Pillow is
listed under ``[project.optional-dependencies].tools`` in pyproject —
install via ``pip install -e .[tools]`` or just ``pip install Pillow``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover - helpful message
    print("This script requires Pillow. Install with: pip install Pillow",
          file=sys.stderr)
    raise


# ---- design tokens (mirror ui/styles.py) --------------------------------
BG_TOP = (14, 17, 22, 255)      # #0E1116
BG_BOT = (28, 34, 44, 255)      # #1C222C
RING = (232, 176, 87, 255)      # #E8B057
MASTER_SIZE = 1024
CORNER_RADIUS_PCT = 0.18
PADDING_PCT = 0.10
RING_WIDTH_PCT = 0.014          # ~14px at 1024
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
RUNTIME_PNG_SIZE = 512


def _vertical_gradient(size: int, top: tuple[int, int, int, int],
                       bot: tuple[int, int, int, int]) -> Image.Image:
    """Single-column gradient stretched to a square.

    Using a 1-pixel-wide column and resizing is 10× faster than
    per-pixel iteration and antialiases cleanly."""
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        r = round(top[0] + (bot[0] - top[0]) * t)
        g = round(top[1] + (bot[1] - top[1]) * t)
        b = round(top[2] + (bot[2] - top[2]) * t)
        grad.putpixel((0, y), (r, g, b, 255))
    return grad.resize((size, size))


def _rounded_square_mask(size: int, radius: int) -> Image.Image:
    """L-mode mask with anti-aliased rounded corners."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1),
                           radius=radius, fill=255)
    return mask


def _drop_shadow(size: int, radius: int) -> Image.Image:
    """Soft shadow behind the mascot so Piplup doesn't look pasted on
    the gradient. Keeps the icon readable at 48px while adding depth
    at 256px+. Free at runtime (baked into the PNG)."""
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    inset = size // 18
    d.ellipse((inset, inset * 2, size - inset, size - inset),
              fill=(0, 0, 0, 120))
    return shadow.filter(ImageFilter.GaussianBlur(size // 40))


def build_icon(src: Path, out_dir: Path) -> None:
    """Render the full icon suite from ``src`` into ``out_dir``.

    ``src`` should be a transparent-background PNG of the mascot; any
    square-ish aspect works — we fit into a padded safe area.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    size = MASTER_SIZE
    radius = int(size * CORNER_RADIUS_PCT)
    pad = int(size * PADDING_PCT)
    ring_w = max(2, int(size * RING_WIDTH_PCT))

    # --- background: gradient clipped to a rounded square ---
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = _vertical_gradient(size, BG_TOP, BG_BOT)
    mask = _rounded_square_mask(size, radius)
    canvas.paste(grad, (0, 0), mask)

    # --- mascot: fit into (size - 2*pad), preserve aspect, center ---
    mascot = Image.open(src).convert("RGBA")
    target = size - 2 * pad
    mw, mh = mascot.size
    scale = target / max(mw, mh)
    new_size = (max(1, round(mw * scale)), max(1, round(mh * scale)))
    mascot = mascot.resize(new_size, Image.LANCZOS)

    # Subtle drop-shadow (baked) so the mascot lifts off the gradient.
    shadow = _drop_shadow(size, radius)
    # Only apply shadow inside the rounded square so the corners stay
    # crisp — otherwise the blur halos outside the icon silhouette.
    shadow_clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_clipped.paste(shadow, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, shadow_clipped)

    mx = (size - new_size[0]) // 2
    my = (size - new_size[1]) // 2
    canvas.alpha_composite(mascot, dest=(mx, my))

    # --- gold ring inset from the corner-radius edge ---
    ring_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring_layer)
    inset = ring_w  # ring sits ~1 stroke inside the rounded edge
    rd.rounded_rectangle(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        radius=max(0, radius - inset),
        outline=RING,
        width=ring_w,
    )
    canvas = Image.alpha_composite(canvas, ring_layer)

    # Ensure the final corners are clean (compositing can leak ~1px).
    final = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    final.paste(canvas, (0, 0), mask)

    # --- exports ---
    master_path = out_dir / "app_icon_1024.png"
    final.save(master_path, format="PNG")

    runtime = final.resize((RUNTIME_PNG_SIZE, RUNTIME_PNG_SIZE), Image.LANCZOS)
    runtime_path = out_dir / "app_icon.png"
    runtime.save(runtime_path, format="PNG")

    # ICO: let Pillow resample each size from the 1024 master so small
    # sizes get their own sharp render rather than a bilinear squash.
    ico_path = out_dir / "app_icon.ico"
    final.save(ico_path, format="ICO",
               sizes=[(s, s) for s in ICO_SIZES])

    print(f"wrote {master_path}")
    print(f"wrote {runtime_path}")
    print(f"wrote {ico_path}")


def _default_src(assets_dir: Path) -> Path:
    # Prefer a file named piplup_source.* so the generated app_icon.png
    # can coexist with the raw art in the same folder.
    for name in ("piplup_source.png", "piplup.png",
                 "icon_source.png", "source.png"):
        p = assets_dir / name
        if p.exists():
            return p
    return assets_dir / "piplup_source.png"


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[3]
    assets = repo / "poe_qol" / "assets"

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=_default_src(assets),
                    help="source mascot PNG (default: assets/piplup_source.png)")
    ap.add_argument("--out", type=Path, default=assets,
                    help="output directory (default: poe_qol/assets)")
    args = ap.parse_args(argv)

    if not args.src.exists():
        print(f"source image not found: {args.src}", file=sys.stderr)
        print(f"drop your mascot PNG at {args.src} and re-run.",
              file=sys.stderr)
        return 2
    build_icon(args.src, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
