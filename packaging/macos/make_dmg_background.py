"""Generate the DMG background image for pytodo-qt.

Writes packaging/macos/dmg_background.png at 600x400. create-dmg lays
the app icon and the Applications alias on top of this background at
the positions configured in release.yml, so this script only paints
the static chrome: title, drag hint, and the first-launch
instructions users need because the app ships with an ad-hoc
signature.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path(__file__).with_name("dmg_background.png")

WIDTH = 600
HEIGHT = 400

BG_COLOR = (245, 245, 247)
FG_COLOR = (28, 28, 30)
DIM_COLOR = (110, 110, 115)
ACCENT_COLOR = (0, 122, 255)

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    title_font = _font(34)
    hint_font = _font(15)
    heading_font = _font(15)
    body_font = _font(13)

    draw.text(
        (WIDTH // 2, 44),
        "PyTodo-Qt",
        fill=FG_COLOR,
        font=title_font,
        anchor="mm",
    )
    draw.text(
        (WIDTH // 2, 76),
        "Drag the app into Applications to install",
        fill=DIM_COLOR,
        font=hint_font,
        anchor="mm",
    )

    box_top = 260
    box_bottom = 380
    draw.rounded_rectangle(
        [(40, box_top), (WIDTH - 40, box_bottom)],
        radius=10,
        fill=(255, 255, 255),
        outline=(220, 220, 224),
        width=1,
    )

    heading_y = box_top + 20
    draw.text(
        (WIDTH // 2, heading_y),
        "First time only",
        fill=ACCENT_COLOR,
        font=heading_font,
        anchor="mm",
    )

    # Instructions target macOS Sequoia (15.x) and later, which
    # removed the right-click > Open bypass for unnotarized ad-hoc-
    # signed apps. Users must now approve the app explicitly via
    # System Settings. Older macOS (Ventura 13 / Sonoma 14) users
    # will see the same Settings panel and the flow also works
    # there, just with the alternate "right-click Open" path still
    # available in parallel.
    lines = (
        "If macOS blocks the first launch, open",
        "System Settings  >  Privacy & Security",
        "and click 'Open Anyway'. See README for details.",
    )
    y = heading_y + 22
    for line in lines:
        draw.text((WIDTH // 2, y), line, fill=FG_COLOR, font=body_font, anchor="mm")
        y += 20

    img.save(OUT_PATH, "PNG")
    print(f"Wrote {OUT_PATH} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
