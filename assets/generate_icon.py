"""Generate the OneTimeSecret application icon.

Produces a multi-resolution ``onetime.ico`` plus a 512px preview PNG.
The motif mirrors the sidebar brand mark: a cyan diamond on a dark
rounded-square surface. Re-run after tweaking constants below.

Usage:
    python assets/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


BG_DARK = (15, 18, 25, 255)
BG_DARK_TOP = (24, 30, 42, 255)
ACCENT = (34, 211, 238, 255)
ACCENT_HI = (103, 232, 249, 255)
ACCENT_LO = (6, 182, 212, 255)

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
PREVIEW_SIZE = 512
SUPERSAMPLE = 4


def _rounded_rect_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _vertical_gradient(size: int, top: tuple[int, int, int, int],
                       bottom: tuple[int, int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (size, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        a = round(top[3] + (bottom[3] - top[3]) * t)
        for x in range(size):
            img.putpixel((x, y), (r, g, b, a))
    return img


def _diamond_polygon(size: int, inset_ratio: float = 0.22) -> list[tuple[float, float]]:
    inset = size * inset_ratio
    cx = size / 2
    return [
        (cx, inset),
        (size - inset, size / 2),
        (cx, size - inset),
        (inset, size / 2),
    ]


def render(size: int) -> Image.Image:
    """Render a single square icon at ``size`` px using supersampling."""
    s = size * SUPERSAMPLE
    mask = _rounded_rect_mask(s)

    bg = _vertical_gradient(s, BG_DARK_TOP, BG_DARK)

    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.polygon(_diamond_polygon(s, inset_ratio=0.18), fill=(34, 211, 238, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=s * 0.05))
    canvas = Image.alpha_composite(canvas, glow)

    diamond = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d_draw = ImageDraw.Draw(diamond)
    d_draw.polygon(_diamond_polygon(s, inset_ratio=0.24), fill=ACCENT)
    canvas = Image.alpha_composite(canvas, diamond)

    highlight = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight)
    cx, cy = s / 2, s / 2
    inset = s * 0.24
    h_draw.polygon(
        [(cx, inset), (s - inset, cy), (cx, cy)],
        fill=ACCENT_HI,
    )
    h_draw.polygon(
        [(cx, cy), (s - inset, cy), (cx, s - inset)],
        fill=ACCENT_LO,
    )
    highlight.putalpha(highlight.split()[-1].point(lambda v: int(v * 0.35)))
    canvas = Image.alpha_composite(canvas, highlight)

    inner = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    i_draw = ImageDraw.Draw(inner)
    i_draw.polygon(_diamond_polygon(s, inset_ratio=0.40), outline=(255, 255, 255, 90),
                   width=max(1, s // 96))
    canvas = Image.alpha_composite(canvas, inner)

    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    ico_path = out_dir / "onetime.ico"
    png_path = out_dir / "onetime_preview.png"

    layers = [render(s) for s in ICO_SIZES]
    layers[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=layers[:-1],
    )

    preview = render(PREVIEW_SIZE)
    preview.save(png_path, format="PNG", optimize=True)

    print(f"wrote {ico_path}")
    print(f"wrote {png_path}")


if __name__ == "__main__":
    main()
