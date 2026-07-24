from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "assets" / "brand"
EXTENSION_ICON_DIR = ROOT / "extension" / "icons"
SITE_ASSET_DIR = ROOT / "site" / "assets"
SIZES = (16, 32, 48, 128, 256, 512)

COLORS = {
    "ink": "#123B43",
    "teal": "#0B8583",
    "teal_dark": "#075F62",
    "mint": "#BDEDE4",
    "paper": "#FFFFFF",
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
    radius = round(work_size * 0.205)
    draw.rounded_rectangle(
        (margin, margin, work_size - margin, work_size - margin),
        radius=radius,
        fill=COLORS["teal"],
    )

    # The open book is also a note surface. The play symbol sits on the right
    # page, while the two short strokes on the left page read as note lines.
    left_page = [
        (0.185, 0.265),
        (0.315, 0.225),
        (0.425, 0.245),
        (0.500, 0.310),
        (0.500, 0.750),
        (0.425, 0.700),
        (0.315, 0.680),
        (0.185, 0.720),
    ]
    right_page = [
        (0.500, 0.310),
        (0.575, 0.245),
        (0.685, 0.225),
        (0.815, 0.265),
        (0.815, 0.720),
        (0.685, 0.680),
        (0.575, 0.700),
        (0.500, 0.750),
    ]
    draw.polygon(_scaled_points(left_page, work_size), fill=COLORS["mint"])
    draw.polygon(_scaled_points(right_page, work_size), fill=COLORS["paper"])

    spine_width = max(2, round(work_size * 0.018))
    draw.line(
        (round(work_size * 0.5), round(work_size * 0.31), round(work_size * 0.5), round(work_size * 0.75)),
        fill=COLORS["teal_dark"],
        width=spine_width,
    )

    _rounded_line(draw, (0.270, 0.420, 0.410, 0.400), work_size, COLORS["teal_dark"], 0.022)
    _rounded_line(draw, (0.270, 0.505, 0.390, 0.490), work_size, COLORS["teal_dark"], 0.022)
    draw.polygon(
        _scaled_points([(0.590, 0.385), (0.590, 0.575), (0.745, 0.480)], work_size),
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


def synchronize_embedded_html_assets(png_bytes: bytes) -> None:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    pattern = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]+")
    replacement = f"data:image/png;base64,{encoded}"

    expected_counts = {
        ROOT / "site" / "index.html": 3,
        ROOT / "web" / "index.html": 2,
    }
    for path, expected_count in expected_counts.items():
        source = path.read_text(encoding="utf-8")
        updated, count = pattern.subn(replacement, source)
        if count != expected_count:
            raise RuntimeError(
                f"Expected {expected_count} embedded LearnNote marks in {path}, found {count}"
            )
        path.write_text(updated, encoding="utf-8")


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
    synchronize_embedded_html_assets((BRAND_DIR / "learnnote-mark-32.png").read_bytes())

    print(f"Generated {len(SIZES) * 2 + 3} LearnNote brand files.")
    print(f"Brand assets: {BRAND_DIR}")
    print(f"Extension icons: {EXTENSION_ICON_DIR}")


if __name__ == "__main__":
    main()
