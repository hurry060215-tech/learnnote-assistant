from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "assets" / "brand"
EXTENSION_ICON_DIR = ROOT / "extension" / "icons"
SITE_ASSET_DIR = ROOT / "site" / "assets"
SIZES = (16, 32, 48, 128, 256, 512)

COLORS = {
    "ink": "#173E3A",
    "teal": "#173E3A",
    "teal_dark": "#173E3A",
    "mint": "#B6D6C8",
    "paper": "#F5F7EF",
}
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def _scaled_points(points: list[tuple[float, float]], scale: int) -> list[tuple[int, int]]:
    return [(round(x * scale), round(y * scale)) for x, y in points]


def _rounded_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float, float, float],
    scale: int,
    fill: str,
    width: float,
) -> None:
    x1, y1, x2, y2 = (round(value * scale) for value in xy)
    stroke = max(1, round(width * scale))
    draw.line((x1, y1, x2, y2), fill=fill, width=stroke)
    radius = stroke // 2
    for x, y in ((x1, y1), (x2, y2)):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def render_mark(size: int) -> Image.Image:
    work_size = max(512, size * 4)
    image = Image.new("RGBA", (work_size, work_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = round(work_size * 0.055)
    radius = round(work_size * 0.225)
    draw.rounded_rectangle(
        (margin, margin, work_size - margin, work_size - margin),
        radius=radius,
        fill=COLORS["teal"],
    )

    # Quiet ink-and-sage open book. A generous spine gap and solid play glyph
    # remain distinct at toolbar sizes; note strokes are omitted at 16 px.
    left_page = [
        (0.205, 0.250),
        (0.375, 0.250),
        (0.475, 0.310),
        (0.475, 0.750),
        (0.375, 0.695),
        (0.205, 0.695),
    ]
    right_page = [
        (0.525, 0.310),
        (0.625, 0.250),
        (0.795, 0.250),
        (0.795, 0.695),
        (0.625, 0.695),
        (0.525, 0.750),
    ]
    draw.polygon(_scaled_points(left_page, work_size), fill=COLORS["paper"])
    draw.polygon(_scaled_points(right_page, work_size), fill=COLORS["mint"])
    if size >= 32:
        _rounded_line(draw, (0.275, 0.405, 0.400, 0.405), work_size, COLORS["teal_dark"], 0.026)
        _rounded_line(draw, (0.275, 0.485, 0.365, 0.485), work_size, COLORS["teal_dark"], 0.026)
    draw.polygon(
        _scaled_points([(0.605, 0.380), (0.605, 0.595), (0.745, 0.4875)], work_size),
        fill=COLORS["teal_dark"],
    )

    if size != work_size:
        image = image.resize((size, size), LANCZOS)
    return image


def validate_png(path: Path, expected_size: int) -> None:
    with Image.open(path) as image:
        if image.format != "PNG":
            raise RuntimeError(f"{path} is not a PNG")
        if image.size != (expected_size, expected_size):
            raise RuntimeError(f"{path} has unexpected dimensions: {image.size}")
        if image.mode != "RGBA":
            raise RuntimeError(f"{path} must preserve transparent corners")


def synchronize_web_assets() -> None:
    # Current UI references files instead of the old embedded data URLs.
    for directory in (ROOT / "web", SITE_ASSET_DIR):
        for size in (32, 128):
            target = directory / f"learnnote-mark-{size}.png"
            target.write_bytes((BRAND_DIR / target.name).read_bytes())
            validate_png(target, size)


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    EXTENSION_ICON_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ASSET_DIR.mkdir(parents=True, exist_ok=True)

    rendered: dict[int, Image.Image] = {}
    for size in SIZES:
        image = render_mark(size)
        rendered[size] = image

        brand_path = BRAND_DIR / f"learnnote-mark-{size}.png"
        extension_path = EXTENSION_ICON_DIR / f"icon{size}.png"
        image.save(brand_path, format="PNG", optimize=True)
        image.save(extension_path, format="PNG", optimize=True)
        validate_png(brand_path, size)
        validate_png(extension_path, size)

    ico_path = BRAND_DIR / "learnnote.ico"
    ico_sizes = tuple(size for size in SIZES if size <= 256)
    rendered[512].save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in ico_sizes],
    )
    with Image.open(ico_path) as icon:
        available_sizes = set(icon.info.get("sizes", set()))
    expected_sizes = {(size, size) for size in ico_sizes}
    if not expected_sizes.issubset(available_sizes):
        raise RuntimeError(f"ICO is missing sizes: {sorted(expected_sizes - available_sizes)}")

    (BRAND_DIR / "palette.json").write_text(
        json.dumps(
            {
                "name": "LearnNote",
                "style": "flat",
                "gradient": False,
                "colors": COLORS,
                "concept": ["open book", "play", "notes"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    site_icon = SITE_ASSET_DIR / "learnnote-mark-32.png"
    site_icon.write_bytes((BRAND_DIR / "learnnote-mark-32.png").read_bytes())
    validate_png(site_icon, 32)
    synchronize_web_assets()

    print(f"Generated {len(SIZES) * 2 + 3} LearnNote brand files.")
    print(f"Brand assets: {BRAND_DIR}")
    print(f"Extension icons: {EXTENSION_ICON_DIR}")


if __name__ == "__main__":
    main()
