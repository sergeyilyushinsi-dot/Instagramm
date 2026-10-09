"""Генерация слайдов для экспертных каруселей (1080x1350) из текста.

Темы (settings.yaml → slides.theme):
  neon    — синий градиент со свечением, выделение слов *звёздочками*, кнопка внизу
  minimal — светлый фон и тёмный текст
"""
from __future__ import annotations

import random
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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


def _render_minimal(slides: list[dict], out_dir: Path, handle: str) -> list[Path]:
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


def render(slides: list[dict], out_dir: Path, handle: str) -> list[Path]:
    theme = config.settings().get("slides", {}).get("theme", "neon")
    if theme == "minimal":
        return _render_minimal(slides, out_dir, handle)
    return _render_neon(slides, out_dir, handle)


# --- тема neon ---------------------------------------------------------------
def _neon_cfg() -> dict:
    cfg = config.settings().get("slides", {}).get("neon", {})
    return {
        "top": cfg.get("top", "#050E33"),
        "mid": cfg.get("mid", "#0C3BC2"),
        "bottom": cfg.get("bottom", "#08247F"),
        "glow": cfg.get("glow", "#3D8BFF"),
        "accent": cfg.get("accent", "#6CC8FF"),
        "text": cfg.get("text", "#FFFFFF"),
        "muted": cfg.get("muted", "#C3D3FF"),
        "logo_text": cfg.get("logo_text", ""),
    }


def _mont(size: int, weight: int = 800, italic: bool = False) -> ImageFont.FreeTypeFont:
    path = config.CONFIG_DIR / "brand" / ("Montserrat-Italic.ttf" if italic else "Montserrat.ttf")
    if not path.exists():
        return _font(size, bold=weight >= 600)
    font = ImageFont.truetype(str(path), size)
    try:
        font.set_variation_by_axes([weight])
    except (OSError, AttributeError):
        pass
    return font


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _background(c: dict, seed: int) -> Image.Image:
    top, mid, bottom = _rgb(c["top"]), _rgb(c["mid"]), _rgb(c["bottom"])
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / H
        grad.putpixel((0, y), _lerp(top, mid, t / 0.6) if t < 0.6 else _lerp(mid, bottom, (t - 0.6) / 0.4))
    img = grad.resize((W, H))

    # Свечение и размытые «огни» на фоне
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    gr = _rgb(c["glow"])
    g.ellipse([W * 0.1, H * 0.42, W * 0.9, H * 0.98], fill=gr + (120,))
    rnd = random.Random(seed)
    for _ in range(9):
        r = rnd.randint(14, 46)
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        g.rounded_rectangle([x - r, y - r, x + r, y + r], radius=r // 2, fill=gr + (rnd.randint(50, 110),))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    sharp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sharp)
    for _ in range(5):
        r = rnd.randint(6, 16)
        x, y = rnd.randint(40, W - 40), rnd.randint(40, H - 40)
        sd.ellipse([x - r, y - r, x + r, y + r], fill=(150, 200, 255, rnd.randint(40, 90)))
    sharp = sharp.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    return Image.alpha_composite(img, sharp)


def _tokens(text: str) -> list[tuple[str, bool]]:
    """«Обычный *выделенный* текст» → [(слово, выделено?)]."""
    out = []
    for i, part in enumerate(re.split(r"\*", text)):
        out += [(w, i % 2 == 1) for w in part.split()]
    return out


def _rich_lines(text: str, fonts: tuple, max_w: int, d: ImageDraw.ImageDraw) -> list[list[tuple[str, bool]]]:
    lines, cur, cur_w = [], [], 0
    space = d.textlength(" ", font=fonts[0])
    for word, hl in _tokens(text):
        w = d.textlength(word, font=fonts[hl])
        if cur and cur_w + space + w > max_w:
            lines.append(cur)
            cur, cur_w = [], 0
        cur_w += (space if cur else 0) + w
        cur.append((word, hl))
    if cur:
        lines.append(cur)
    return lines


def _draw_rich(d, text: str, y: int, fonts: tuple, colors: tuple, max_w: int, line_h: int) -> int:
    for para in text.split("\n"):
        if not para.strip():
            y += line_h // 2
            continue
        for line in _rich_lines(para, fonts, max_w, d):
            space = d.textlength(" ", font=fonts[0])
            width = sum(d.textlength(w, font=fonts[h]) for w, h in line) + space * (len(line) - 1)
            x = (W - width) / 2
            for w, h in line:
                d.text((x, y), w, font=fonts[h], fill=colors[h])
                x += d.textlength(w, font=fonts[h]) + space
            y += line_h
    return y


def _glow_text(img: Image.Image, text: str, font, center: tuple[int, int], c: dict) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    box = ld.textbbox((0, 0), text, font=font)
    pos = (center[0] - (box[2] - box[0]) / 2 - box[0], center[1] - (box[3] - box[1]) / 2 - box[1])
    ld.text(pos, text, font=font, fill=_rgb(c["glow"]) + (255,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(35)))
    # Сам текст — с вертикальным градиентом от белого к акценту
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text(pos, text, font=font, fill=255)
    fill = Image.new("RGBA", (W, H))
    top, bottom = (255, 255, 255), _rgb(c["accent"])
    y0, y1 = int(pos[1] + box[1]), int(pos[1] + box[3])
    fd = ImageDraw.Draw(fill)
    for y in range(max(0, y0), min(H, y1 + 1)):
        fd.line([(0, y), (W, y)], fill=_lerp(top, bottom, (y - y0) / max(1, y1 - y0)) + (255,))
    img.paste(fill, (0, 0), mask)


def _glass_tiles(img: Image.Image, seed: int) -> None:
    """Плавающие «стеклянные» плашки по краям — замена 3D-объектам из референса."""
    rnd = random.Random(seed * 31 + 5)
    spots = [(115, 640), (965, 610), (120, 1010), (955, 1000), (900, 1170), (950, 800)]
    rnd.shuffle(spots)
    for i, (x, y) in enumerate(spots[:4]):
        size = rnd.randint(70, 130)
        x += rnd.randint(-30, 30)
        y += rnd.randint(-30, 30)
        tile = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        box = [x - size // 2, y - size // 2, x + size // 2, y + size // 2]
        td.rounded_rectangle(box, radius=size // 4, fill=(150, 200, 255, 55), outline=(200, 230, 255, 150), width=3)
        inner = size // 4
        td.rounded_rectangle([x - inner, y - inner, x + inner, y + inner], radius=inner // 2, fill=(220, 240, 255, 90))
        tile = tile.rotate(rnd.randint(-25, 25), center=(x, y), resample=Image.Resampling.BICUBIC)
        blur = 6 if i % 2 else 1.5   # часть плашек «не в фокусе» — даёт глубину
        img.alpha_composite(tile.filter(ImageFilter.GaussianBlur(blur)))


def _glass_rings(img: Image.Image, center: tuple[int, int], c: dict) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    cx, cy = center
    for r, a, w in ((270, 60, 3), (200, 100, 4), (130, 160, 6)):
        ld.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(150, 205, 255, a), width=w)
    glow = layer.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(glow)
    img.alpha_composite(layer)
    core = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(core).ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=(190, 230, 255, 230))
    img.alpha_composite(core.filter(ImageFilter.GaussianBlur(28)))


def _photo(img: Image.Image, path: Path, box: tuple[int, int, int, int], c: dict) -> None:
    x0, y0, x1, y1 = box
    photo = ImageOps.fit(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), (x1 - x0, y1 - y0))
    mask = Image.new("L", photo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *photo.size], radius=36, fill=255)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0 - 10, y0 - 10, x1 + 10, y1 + 10], radius=46,
                                             fill=_rgb(c["glow"]) + (200,))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(40)))
    img.paste(photo, (x0, y0), mask)
    ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1, y1], radius=36, outline=(160, 210, 255, 160), width=3)


def _overlay(img: Image.Image, draw_fn) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    img.alpha_composite(layer)


def _logo(img: Image.Image, handle: str, c: dict) -> None:
    initials = c["logo_text"] or "".join(p[0] for p in config.profile().get("name", "S").split()[:2]).upper()
    _overlay(img, lambda o: o.rounded_rectangle([72, 70, 132, 130], radius=16, fill=(255, 255, 255, 45),
                                                 outline=(200, 225, 255, 200), width=2))
    d = ImageDraw.Draw(img)
    f = _mont(26, 800)
    box = d.textbbox((0, 0), initials, font=f)
    d.text((102 - (box[2] - box[0]) / 2 - box[0], 100 - (box[3] - box[1]) / 2 - box[1]), initials, font=f, fill="white")
    d.text((148, 83), handle.lstrip("@"), font=_mont(30, 600), fill="white")


def _cta(img: Image.Image, text: str, c: dict) -> None:
    d = ImageDraw.Draw(img)
    f = _mont(28, 600)
    tw = d.textlength(text, font=f)
    x0, y0, h = 72, H - 150, 76
    x1 = int(x0 + 40 + tw + 24 + 56 + 12)
    _overlay(img, lambda o: o.rounded_rectangle([x0, y0, x1, y0 + h], radius=h // 2, fill=(6, 20, 70, 190),
                                                 outline=(120, 180, 255, 220), width=2))
    box = d.textbbox((0, 0), text, font=f)
    d.text((x0 + 40, y0 + h / 2 - (box[3] + box[1]) / 2), text, font=f, fill="white")
    cx0 = x1 - 12 - 56
    d.rounded_rectangle([cx0, y0 + 10, cx0 + 56, y0 + h - 10], radius=28, fill="white")
    ay = y0 + h / 2
    d.line([(cx0 + 16, ay), (cx0 + 40, ay)], fill=_rgb(c["mid"]), width=4)
    d.polygon([(cx0 + 42, ay), (cx0 + 32, ay - 9), (cx0 + 32, ay + 9)], fill=_rgb(c["mid"]))


def _render_neon(slides: list[dict], out_dir: Path, handle: str) -> list[Path]:
    c = _neon_cfg()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    total = len(slides)
    for idx, slide in enumerate(slides, start=1):
        img = _background(c, seed=idx * 7919 + len(slide.get("title", "")))
        _glass_tiles(img, seed=idx)
        d = ImageDraw.Draw(img)
        _logo(img, handle, c)
        counter = f"{idx}/{total}"
        cf = _mont(26, 600)
        d.text((W - 72 - d.textlength(counter, font=cf), 88), counter, font=cf, fill=c["muted"])

        title = slide.get("title", "")
        number = None
        m = re.match(r"^\s*(\d+)[.)]\s*(.+)$", title)
        if m:
            number, title = m.group(1), m.group(2)

        is_cover = idx == 1
        size = 84 if is_cover else 68
        tfonts = (_mont(size, 800), _mont(size, 800, italic=True))
        y = 210 if is_cover else 190
        y = _draw_rich(d, title, y, tfonts, (c["text"], c["accent"]), W - 160, int(size * 1.16))
        body = slide.get("body", "")
        if body:
            bfonts = (_mont(34, 500), _mont(34, 700))
            y = _draw_rich(d, body, y + 34, bfonts, (c["muted"], c["accent"]), W - 220, 48)

        hero_top, hero_bottom = max(y + 50, 640), H - 190
        hero_center = (W // 2, (hero_top + hero_bottom) // 2)
        image = slide.get("image")
        if image and (config.ROOT / image).exists():
            hw = min(820, int((hero_bottom - hero_top) * 1.25))
            hh = hero_bottom - hero_top
            _photo(img, config.ROOT / image, (W // 2 - hw // 2, hero_top, W // 2 + hw // 2, hero_top + hh), c)
        elif number:
            _glow_text(img, number, _mont(min(420, hero_bottom - hero_top), 900), hero_center, c)
        elif hero_bottom - hero_top > 220:
            _glass_rings(img, hero_center, c)

        default_cta = "Листай" if idx < total else "Сохрани себе"
        _cta(img, slide.get("cta") or default_cta, c)

        path = out_dir / f"slide_{idx:02d}.jpg"
        img.convert("RGB").save(path, "JPEG", quality=93)
        paths.append(path)
    return paths
