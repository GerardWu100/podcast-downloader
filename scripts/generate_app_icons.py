"""Generate the home-screen icons used when the web UI is installed on a phone.

The artwork matches the inline SVG favicon in ``src/web/templates.py``: a blue
rounded square holding a white download arrow above a baseline.

Run this only when the artwork changes:

    uv run --group dev python scripts/generate_app_icons.py

The PNG files it writes are committed to the repository, so neither the Docker
image nor the running app needs Pillow. ``.dockerignore`` excludes ``scripts/``
for that reason.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# The artwork is described on a 32x32 grid, the same viewBox the SVG favicon
# uses, then scaled to whatever pixel size each output file needs.
DESIGN_GRID = 32.0
CORNER_RADIUS = 7.0
STROKE_WIDTH = 2.4

# Matches --accent in BASE_STYLES and FAVICON_ACCENT_COLOR in templates.py.
ACCENT_COLOR = (37, 99, 235, 255)  # #2563eb
GLYPH_COLOR = (255, 255, 255, 255)

# Pillow has no anti-aliasing, so each icon is drawn this many times larger and
# then shrunk with a smooth filter to get clean diagonal edges.
SUPERSAMPLE = 4

# Three strokes make the download glyph: a vertical stem, the arrowhead below
# it, and the baseline underneath. Coordinates are points on the 32x32 grid.
ARROW_STEM = ((16.0, 7.0), (16.0, 17.0))
ARROW_HEAD = ((12.0, 13.0), (16.0, 17.0), (20.0, 13.0))
BASELINE = ((9.0, 22.0), (23.0, 22.0))

# Android may crop a "maskable" icon to a circle, a squircle, or a rounded
# square depending on the phone. Shrinking the glyph to this fraction of the
# canvas keeps it inside the area every crop shape is guaranteed to show.
MASKABLE_GLYPH_SCALE = 0.60

# iOS applies its own rounded-corner mask, so the icon is drawn edge to edge
# with the glyph pulled in far enough that the mask cannot clip it.
APPLE_GLYPH_SCALE = 0.78

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"


def _stroke_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    width: float,
    color: tuple[int, int, int, int],
) -> None:
    """Draw connected line segments with rounded ends and corners.

    Pillow's ``line`` has no cap or join style, so a filled circle as wide as
    the stroke is stamped at every vertex. That rounds both ends of the run and
    fills the notch that would otherwise show at each corner.

    Parameters
    ----------
    draw:
        Drawing surface for the supersampled canvas.
    points:
        Vertices in pixel coordinates, in drawing order.
    width:
        Stroke thickness in pixels.
    color:
        Stroke color as red, green, blue, alpha.
    """
    draw.line(points, fill=color, width=round(width))
    radius = width / 2.0
    for x, y in points:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def render_icon(size: int, *, glyph_scale: float, rounded_corners: bool) -> Image.Image:
    """Return one square icon drawn at the requested pixel size.

    Parameters
    ----------
    size:
        Width and height of the returned image in pixels.
    glyph_scale:
        Fraction of the canvas the 32x32 design grid should occupy. ``1.0``
        fills the icon; smaller values inset the glyph and leave a blue border.
    rounded_corners:
        ``True`` draws a rounded square on a transparent background, for icons
        the operating system shows as-is. ``False`` fills the whole canvas, for
        icons the operating system masks to its own shape.

    Returns
    -------
    PIL.Image.Image
        Icon in RGBA mode at ``size`` by ``size`` pixels.
    """
    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if rounded_corners:
        radius = CORNER_RADIUS / DESIGN_GRID * canvas
        draw.rounded_rectangle(
            (0, 0, canvas - 1, canvas - 1), radius=radius, fill=ACCENT_COLOR
        )
    else:
        draw.rectangle((0, 0, canvas - 1, canvas - 1), fill=ACCENT_COLOR)

    # One design-grid unit in pixels, plus the offset that centers the grid
    # when the glyph is inset. At glyph_scale 1.0 the margin is zero.
    unit = canvas * glyph_scale / DESIGN_GRID
    margin = canvas * (1.0 - glyph_scale) / 2.0

    def to_pixels(point: tuple[float, float]) -> tuple[float, float]:
        grid_x, grid_y = point
        return (margin + grid_x * unit, margin + grid_y * unit)

    stroke_pixels = STROKE_WIDTH * unit
    for polyline in (ARROW_STEM, ARROW_HEAD, BASELINE):
        _stroke_polyline(
            draw, [to_pixels(point) for point in polyline], stroke_pixels, GLYPH_COLOR
        )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write every icon file the web manifest and iOS reference."""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    for size in (192, 512):
        icon = render_icon(size, glyph_scale=1.0, rounded_corners=True)
        icon.save(STATIC_DIR / f"icon-{size}.png")

    maskable = render_icon(
        512, glyph_scale=MASKABLE_GLYPH_SCALE, rounded_corners=False
    )
    maskable.save(STATIC_DIR / "icon-maskable-512.png")

    # iOS renders the home-screen icon on an opaque background and ignores
    # transparency, so this one is flattened to RGB.
    apple = render_icon(180, glyph_scale=APPLE_GLYPH_SCALE, rounded_corners=False)
    apple.convert("RGB").save(STATIC_DIR / "apple-touch-icon.png")

    for path in sorted(STATIC_DIR.glob("*.png")):
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
