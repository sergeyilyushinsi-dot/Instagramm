"""Генерация слайдов для экспертных каруселей (1080x1350) из текста."""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

W, H = 1080, 1350
PAD = 96

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    brand = config.CONFIG_DIR / "brand"
    custom = brand / ("font-bold.ttf" if bold else "font-regular.ttf")
    candidates = [custom] + [Path(p) for p in FONT_CANDIDATES if bold or "Bold" not in p]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def _theme() -> dict:
    theme = config.settings().get("slides", {})
    return {
        "bg": theme.get("background", "#F5F1EA"),
        "fg": theme.get("text", "#1C1C1C"),
        "accent": theme.get("accent", "#E2552D"),
    }


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        width = 40
        while width > 8:
            wrapped = textwrap.wrap(paragraph, width) or [""]
            if all(draw.textlength(line, font=font) <= max_width for line in wrapped):
                break
            width -= 2
        lines.extend(wrapped)
    return lines


def render(slides: list[dict], out_dir: Path, handle: str) -> list[Path]:
    theme = _theme()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    total = len(slides)
    for idx, slide in enumerate(slides, start=1):
        img = Image.new("RGB", (W, H), theme["bg"])
        d = ImageDraw.Draw(img)
        is_cover = idx == 1
        title_font = _font(92 if is_cover else 64)
        body_font = _font(40, bold=False)

        y = PAD + (180 if is_cover else 40)
        d.rectangle([PAD, y - 40, PAD + 120, y - 28], fill=theme["accent"])
        for line in _wrap(d, slide.get("title", ""), title_font, W - 2 * PAD):
            d.text((PAD, y), line, font=title_font, fill=theme["fg"])
            y += title_font.size + 14
        y += 40
        for line in _wrap(d, slide.get("body", ""), body_font, W - 2 * PAD):
            d.text((PAD, y), line, font=body_font, fill=theme["fg"])
            y += body_font.size + 16

        footer = _font(30, bold=False)
        d.text((PAD, H - PAD), handle, font=footer, fill=theme["fg"])
        counter = f"{idx}/{total}" + ("  →" if idx < total else "")
        d.text((W - PAD - d.textlength(counter, font=footer), H - PAD), counter, font=footer, fill=theme["accent"])

        path = out_dir / f"slide_{idx:02d}.jpg"
        img.save(path, "JPEG", quality=93)
        paths.append(path)
    return paths
