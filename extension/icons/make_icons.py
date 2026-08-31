"""Regenerate the extension's icon set.

The mark is deliberately the app's own, not a new one: app.py's `.sb-logo`
(the "AR" square at the top of the sidebar) is a rounded square filled with
var(--brand-dark) carrying white 800-weight "AR". An extension whose toolbar
icon does not match the product it opens is just one more anonymous puzzle
piece in the Chrome toolbar.

Values below are copied from that CSS rather than eyeballed:
  background  var(--brand-dark)  #1d4ed8   (theme.py TOKENS["brand-dark"])
  foreground  var(--surface)     #ffffff   (theme.py TOKENS["surface"])
  radius      var(--radius)      8px on a 38px box, i.e. 21% of the side

Run from this directory:  python3 make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_DARK = "#1d4ed8"
SURFACE = "#ffffff"
RADIUS_RATIO = 8 / 38  # var(--radius) against .sb-logo's 38px box
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Chrome uses 16 in the toolbar/context menus, 32 on Windows, 48 on the
# extensions management page, and 128 in the Web Store and during install.
SIZES = (16, 32, 48, 128)

# Rendered at 8x and downsampled: PIL has no antialiasing for rounded_rectangle
# or text, so drawing straight to 16px gives a jagged mark. Supersampling is the
# whole reason the small sizes are legible at all.
SCALE = 8


def render(size):
    box = size * SCALE
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, box - 1, box - 1),
        radius=round(box * RADIUS_RATIO),
        fill=BRAND_DARK,
    )

    # "AR" set to ~52% of the tile width. The CSS uses 0.95rem on a 38px box
    # (~40%), but that leaves generous side bearing that reads as an empty blue
    # square once the tile is 16px wide, so the mark is set tighter here.
    font = ImageFont.truetype(FONT_PATH, round(box * 0.52))
    left, top, right, bottom = draw.textbbox((0, 0), "AR", font=font)
    draw.text(
        ((box - (right - left)) / 2 - left, (box - (bottom - top)) / 2 - top),
        "AR",
        font=font,
        fill=SURFACE,
    )
    return image.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for size in SIZES:
        path = here / f"icon{size}.png"
        render(size).save(path)
        print(f"wrote {path.name}")
