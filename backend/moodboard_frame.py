"""Compose moodboard renders into a Material Board slide (title, swatches, sidebar)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

# Reference palette (MyClosets-style material board).
_CANVAS_SIZE = (1800, 1200)
_BG = (255, 255, 255)
_SIDEBAR_BG = (235, 225, 210)
_TEXT_TAN = (181, 154, 123)
_BRAND_BLUE = (45, 62, 92)

_LEFT_COL = 220
_RIGHT_COL = 130
_TOP_PAD = 36
_BOTTOM_PAD = 36
_SWATCH_SIZE = 78
_SWATCH_GAP = 22


def _load_serif_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "fonts" / "LiberationSerif-Regular.ttf",
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/timesbd.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _load_sans_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "fonts" / "LiberationSans-Regular.ttf",
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _avg_color(region: Image.Image) -> Tuple[int, int, int]:
    thumb = region.convert("RGB").resize((24, 24))
    pixels = list(thumb.getdata())
    if not pixels:
        return (200, 190, 175)
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return (r, g, b)


def _swatch_samples(render: Image.Image, count: int = 4) -> List[Image.Image]:
    w, h = render.size
    boxes = [
        (int(w * 0.08), int(h * 0.12), int(w * 0.28), int(h * 0.32)),
        (int(w * 0.55), int(h * 0.10), int(w * 0.78), int(h * 0.30)),
        (int(w * 0.10), int(h * 0.55), int(w * 0.32), int(h * 0.78)),
        (int(w * 0.58), int(h * 0.58), int(w * 0.82), int(h * 0.82)),
    ]
    out: List[Image.Image] = []
    for box in boxes[:count]:
        crop = render.crop(box)
        sw = Image.new("RGB", (_SWATCH_SIZE, _SWATCH_SIZE), _avg_color(crop))
        sw.paste(crop.resize((_SWATCH_SIZE, _SWATCH_SIZE), Image.Resampling.LANCZOS), (0, 0))
        mask = Image.new("L", (_SWATCH_SIZE, _SWATCH_SIZE), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, _SWATCH_SIZE - 1, _SWATCH_SIZE - 1), fill=255)
        circ = Image.new("RGB", (_SWATCH_SIZE, _SWATCH_SIZE), _BG)
        circ.paste(sw, (0, 0), mask)
        out.append(circ)
    return out


def _fit_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    ratio = min(max_w / img.width, max_h / img.height)
    if ratio >= 1:
        return img.copy()
    size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
    return img.resize(size, Image.Resampling.LANCZOS)


def _render_vertical_label(
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: Tuple[int, int, int],
) -> Image.Image:
    """Horizontal text rotated clockwise so it reads bottom-to-top in the sidebar."""
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    bbox = measure.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    txt = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(txt).text((-bbox[0], -bbox[1]), text, font=font, fill=fill + (255,))
    return txt.rotate(-90, expand=True)


def _draw_sidebar_room_label(
    canvas: Image.Image,
    text: str,
    *,
    sidebar_left: int,
    sidebar_w: int,
    canvas_h: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    top_reserved: int = 130,
    bottom_pad: int = 36,
) -> None:
    """Place vertical room name centered in the sidebar without clipping."""
    label = (text or "Room").strip()
    if not label:
        return

    rotated = _render_vertical_label(label, font=font, fill=fill)
    rw, rh = rotated.size
    avail_h = max(1, canvas_h - top_reserved - bottom_pad)
    avail_w = max(1, sidebar_w - 20)

    if rw > avail_w or rh > avail_h:
        scale = min(avail_w / rw, avail_h / rh)
        rw = max(1, int(rw * scale))
        rh = max(1, int(rh * scale))
        rotated = rotated.resize((rw, rh), Image.Resampling.LANCZOS)

    paste_x = sidebar_left + (sidebar_w - rw) // 2
    paste_y = top_reserved + (avail_h - rh) // 2
    paste_x = max(sidebar_left + 8, min(paste_x, sidebar_left + sidebar_w - rw - 8))
    paste_y = max(top_reserved, min(paste_y, canvas_h - rh - bottom_pad))
    canvas.paste(rotated, (paste_x, paste_y), rotated)


def _draw_brand_logo(draw: ImageDraw.ImageDraw, cx: int, top: int, brand: str, sans: ImageFont.ImageFont) -> None:
    size = 44
    left = cx - size // 2
    draw.rectangle((left, top, left + size, top + size), fill=_BRAND_BLUE)
    bar_w = 7
    gap = 10
    mid = left + size // 2
    draw.rectangle((mid - gap - bar_w, top + 8, mid - gap, top + size - 8), fill=(255, 255, 255))
    draw.rectangle((mid + gap, top + 8, mid + gap + bar_w, top + size - 8), fill=(255, 255, 255))
    bb = draw.textbbox((0, 0), brand, font=sans)
    tw = bb[2] - bb[0]
    draw.text((cx - tw // 2, top + size + 6), brand, font=sans, fill=_TEXT_TAN)


def apply_material_board_frame(
    png_bytes: bytes,
    *,
    room_label: str,
    board_title: str = "Material Board",
    brand_name: str | None = None,
) -> bytes:
    """
    Wrap a plain interior render in a Material Board layout:
    top-left title, left material swatches, right beige sidebar with logo + vertical room name.
    """
    brand = (brand_name or os.environ.get("MOODBOARD_BRAND_NAME") or "Interior Copilot").strip()
    room = (room_label or "Room").strip()
    if len(room) > 42:
        room = room[:39] + "..."

    render = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    canvas = Image.new("RGB", _CANVAS_SIZE, _BG)
    draw = ImageDraw.Draw(canvas)

    cw, ch = _CANVAS_SIZE
    sidebar_left = cw - _RIGHT_COL
    draw.rectangle((sidebar_left, 0, cw, ch), fill=_SIDEBAR_BG)

    content_left = _LEFT_COL
    content_right = sidebar_left
    content_w = content_right - content_left
    content_h = ch - _TOP_PAD - _BOTTOM_PAD
    fitted = _fit_image(render, content_w, content_h)
    paste_x = content_left + (content_w - fitted.width) // 2
    paste_y = _TOP_PAD + (content_h - fitted.height) // 2
    canvas.paste(fitted, (paste_x, paste_y))

    title_font = _load_serif_font(40)
    room_font_size = 52 if len(room) <= 14 else 40 if len(room) <= 22 else 32
    room_font = _load_serif_font(room_font_size)
    brand_font = _load_sans_font(14)
    draw.text((34, 34), board_title, font=title_font, fill=_TEXT_TAN)

    y = 110
    for sw in _swatch_samples(render):
        canvas.paste(sw, (56, y))
        y += _SWATCH_SIZE + _SWATCH_GAP

    sidebar_cx = sidebar_left + _RIGHT_COL // 2
    _draw_brand_logo(draw, sidebar_cx, 42, brand, brand_font)
    _draw_sidebar_room_label(
        canvas,
        room,
        sidebar_left=sidebar_left,
        sidebar_w=_RIGHT_COL,
        canvas_h=ch,
        font=room_font,
        fill=_TEXT_TAN,
        top_reserved=130,
    )

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
