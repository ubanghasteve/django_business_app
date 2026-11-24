"""
Regenerate PWA / favicon / taskbar icons from the real City Prints logo.

logo-ct.png uses transparent cutouts for the skyline inside the orange sun.
On a white tile those holes would show white and the skyline would vanish, so
we first fill cutouts that sit inside the sun with solid black, then place the
mark on white. Result: orange sun + black skyline, both high-contrast.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parents[1] / "static" / "img"
LOGO = BASE / "logo-ct.png"
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


def sun_skyline_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the orange sun (skyline cutouts live inside it)."""
    im = im.convert("RGBA")
    w, h = im.size
    pixels = im.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < 20:
                continue
            if r > 200 and 40 < g < 180 and b < 100:
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
    if maxx < 0:
        raise SystemExit("Could not find orange sun in logo-ct.png")
    return minx, miny, maxx + 1, maxy + 1


def bake_skyline_black(mark: Image.Image) -> Image.Image:
    """
    Fill transparent skyline cutouts with black so they stay visible on white.

    Uses an ellipse covering the sun bbox as the interior mask: any mostly
    transparent pixel inside that ellipse becomes solid black.
    """
    mark = mark.convert("RGBA")
    w, h = mark.size
    mask = Image.new("L", (w, h), 0)
    # Sun is a semicircle / wide ellipse filling the crop
    ImageDraw.Draw(mask).ellipse([0, 0, w - 1, h * 2 - 1], fill=255)

    pixels = mark.load()
    m = mask.load()
    for y in range(h):
        for x in range(w):
            if m[x, y] < 128:
                continue
            r, g, b, a = pixels[x, y]
            if a < 40:
                pixels[x, y] = BLACK
            elif a < 200 and r + g + b < 80:
                # Semi-transparent dark antialias → solid black
                pixels[x, y] = BLACK
    return mark


def extract_mark(im: Image.Image) -> Image.Image:
    """Crop sun + skyline and bake cutouts to black for white-tile icons."""
    im = im.convert("RGBA")
    x0, y0, x1, y1 = sun_skyline_bbox(im)
    pad = 4
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    mark = im.crop((x0, y0, x1, y1))
    return bake_skyline_black(mark)


def make_icon(mark: Image.Image, size: int, *, safe_ratio: float = 0.0) -> Image.Image:
    """
    White square with the logo mark scaled to fill the usable area.
    safe_ratio insets content for Android maskable icons (~20% safe zone).
    """
    canvas = Image.new("RGBA", (size, size), WHITE)
    inset = int(size * safe_ratio)
    usable = size - 2 * inset
    if usable < 8:
        usable = size
        inset = 0

    margin = max(2, int(usable * 0.04))
    target = usable - 2 * margin
    mw, mh = mark.size
    scale = min(target / mw, target / mh)
    nw = max(1, int(mw * scale))
    nh = max(1, int(mh * scale))
    resized = mark.resize((nw, nh), Image.Resampling.LANCZOS)

    x = inset + (usable - nw) // 2
    y = inset + (usable - nh) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def save_ico(master: Image.Image, ico_path: Path) -> None:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = [master.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    images[0].save(ico_path, format="ICO", sizes=sizes, append_images=images[1:])


def main() -> None:
    mark = extract_mark(Image.open(LOGO))
    print(f"Mark size: {mark.size}")

    specs = [
        ("icon-192.png", 192, 0.0),
        ("icon-512.png", 512, 0.0),
        ("apple-icon.png", 180, 0.0),
        ("favicon.png", 64, 0.0),
        ("icon-maskable-192.png", 192, 0.14),
        ("icon-maskable-512.png", 512, 0.14),
    ]
    master = None
    for name, size, safe in specs:
        out = make_icon(mark, size, safe_ratio=safe)
        out.save(BASE / name, optimize=True)
        print(f"Wrote {name}")
        if name == "icon-512.png":
            master = out

    if master is not None:
        save_ico(master, BASE / "favicon.ico")
        print("Wrote favicon.ico")

    for tmp in (
        "_icon_mark_source.png",
        "_icon_mark_cleaned.png",
        "_preview_logo_on_black.png",
        "_preview_logo_on_orange.png",
        "_preview_logo_on_white.png",
    ):
        p = BASE / tmp
        if p.exists():
            p.unlink()
            print(f"Removed {tmp}")


if __name__ == "__main__":
    main()
