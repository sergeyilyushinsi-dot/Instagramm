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
        if not slide.get("visual"):
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
        visual = slide.get("visual") or {}
        if visual:
            if number:  # номер шага — маленький светящийся бейдж над схемой
                _glow_layer(img, lambda o: o.ellipse([W / 2 - 34, hero_top - 34, W / 2 + 34, hero_top + 34],
                                                     fill=(200, 235, 255, 255)), 14)
                _center_text(ImageDraw.Draw(img), number, W / 2, hero_top, _mont(36, 900), c["mid"])
                hero_top += 60
            _visual(img, (90, hero_top, W - 90, hero_bottom - 10), visual, c)
        elif image and (config.ROOT / image).exists():
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


# --- инфографика ---------------------------------------------------------------
# В слайде: visual: {type: hub|persona|funnel|journey|matrix|chart|donut, ...}
#   hub:     center, items[]                  — понятие и его составляющие
#   persona: items[{label, sub}]              — роли / аудитории
#   funnel:  items[]                          — воронка сверху вниз
#   journey: items[], span                    — этапы пути; span — подпись над всей линией
#   matrix:  x, y, points[{label, x, y}]      — позиционирование (x, y от 0 до 1)
#   chart:   values[], forecast_from          — факт и пунктирный прогноз
#   donut:   center, items[{label, value}]    — доли целого
# Слова с *звёздочками* в подписях выделяются акцентом. Числа на схемах — иллюстрация,
# подпись `note` выводится мелко под схемой (например «схема условная»).

def _plain(text: str) -> tuple[str, bool]:
    return text.replace("*", ""), "*" in text


def _center_text(d, text, cx, cy, font, fill):
    box = d.textbbox((0, 0), text, font=font)
    d.text((cx - (box[2] - box[0]) / 2 - box[0], cy - (box[3] - box[1]) / 2 - box[1]), text, font=font, fill=fill)


def _wrap_center(d, text, cx, cy, font, fill, max_w, line_h):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if cur and d.textlength(test, font=font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = test
    lines.append(cur)
    y = cy - (len(lines) - 1) * line_h / 2
    for line in lines:
        _center_text(d, line, cx, y, font, fill)
        y += line_h


def _glow_layer(img, draw_fn, blur=18):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))
    img.alpha_composite(layer)


def _panel(o, box, hl=False, radius=26, solid=False):
    if solid:
        fill = (55, 125, 240, 250) if hl else (16, 52, 160, 245)
    else:
        fill = (110, 190, 255, 95) if hl else (160, 200, 255, 40)
    o.rounded_rectangle(box, radius=radius, fill=fill, outline=(190, 225, 255, 210 if hl else 130), width=3 if hl else 2)


def _person(o, cx, cy, s, color):
    o.ellipse([cx - s * .22, cy - s * .5, cx + s * .22, cy - s * .06], fill=color)
    o.rounded_rectangle([cx - s * .38, cy, cx + s * .38, cy + s * .5], radius=int(s * .22), fill=color)


def _v_hub(img, box, v, c):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    items = v.get("items", [])
    R = min(x1 - x0 - 260, y1 - y0 - 120) / 2
    import math
    pts = []
    for i, _ in enumerate(items):
        a = -math.pi / 2 + 2 * math.pi * i / max(1, len(items))
        pts.append((cx + R * 1.25 * math.cos(a), cy + R * math.sin(a)))
    _glow_layer(img, lambda o: [o.line([(cx, cy), p], fill=(140, 200, 255, 170), width=4) for p in pts], 10)
    lf = _mont(28, 700)
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(o)
    for (px, py), item in zip(pts, items):
        text, hl = _plain(item)
        tw = od.textlength(text, font=lf)
        _panel(od, [px - tw / 2 - 26, py - 32, px + tw / 2 + 26, py + 32], hl, radius=32, solid=True)
    _panel(od, [cx - 120, cy - 70, cx + 120, cy + 70], True, radius=40, solid=True)
    img.alpha_composite(o)
    d = ImageDraw.Draw(img)
    for (px, py), item in zip(pts, items):
        text, hl = _plain(item)
        _center_text(d, text, px, py, lf, "white" if not hl else c["text"])
    _wrap_center(d, v.get("center", ""), cx, cy, _mont(32, 800), "white", 210, 38)


def _v_persona(img, box, v, c):
    x0, y0, x1, y1 = box
    items = v.get("items", [])
    n = max(1, len(items))
    gap = 26
    cw = (x1 - x0 - gap * (n - 1)) / n
    ch = min(y1 - y0, 360)
    top = (y0 + y1 - ch) / 2
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(o)
    for i, item in enumerate(items):
        label, hl = _plain(item.get("label", ""))
        bx = x0 + i * (cw + gap)
        _panel(od, [bx, top, bx + cw, top + ch], hl)
        _person(od, bx + cw / 2, top + ch * .36, ch * .38, (220, 240, 255, 235) if hl else (170, 205, 255, 200))
    if any(_plain(it.get("label", ""))[1] for it in items):
        img.alpha_composite(o.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(o)
    d = ImageDraw.Draw(img)
    for i, item in enumerate(items):
        label, hl = _plain(item.get("label", ""))
        bx = x0 + i * (cw + gap)
        _wrap_center(d, label, bx + cw / 2, top + ch * .74, _mont(30 if hl else 28, 800), "white", cw - 30, 34)
        _wrap_center(d, item.get("sub", ""), bx + cw / 2, top + ch * .89, _mont(22, 600 if hl else 500),
                     "white" if hl else c["muted"], cw - 30, 28)


def _v_funnel(img, box, v, c):
    x0, y0, x1, y1 = box
    items = v.get("items", [])
    n = max(1, len(items))
    gap = 12
    h = min(110, (y1 - y0 - gap * (n - 1)) / n)
    total_h = n * h + gap * (n - 1)
    top = (y0 + y1 - total_h) / 2
    cx = (x0 + x1) / 2
    wmax, wmin = (x1 - x0) * .92, (x1 - x0) * .38
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(o)
    for i in range(n):
        wt = wmax - (wmax - wmin) * i / n
        wb = wmax - (wmax - wmin) * (i + 1) / n
        yt = top + i * (h + gap)
        alpha = 70 + int(120 * i / max(1, n - 1))
        od.polygon([(cx - wt / 2, yt), (cx + wt / 2, yt), (cx + wb / 2, yt + h), (cx - wb / 2, yt + h)],
                   fill=(110, 190, 255, alpha), outline=(200, 230, 255, 200))
    img.alpha_composite(o.filter(ImageFilter.GaussianBlur(10)))
    img.alpha_composite(o)
    d = ImageDraw.Draw(img)
    for i, item in enumerate(items):
        text, hl = _plain(item)
        _center_text(d, text, cx, top + i * (h + gap) + h / 2, _mont(32 if hl else 30, 800 if hl else 700),
                     "white")


def _v_journey(img, box, v, c):
    x0, y0, x1, y1 = box
    items = v.get("items", [])
    n = max(2, len(items))
    cy = (y0 + y1) / 2 + 20
    xs = [x0 + 40 + (x1 - x0 - 80) * i / (n - 1) for i in range(len(items))]
    _glow_layer(img, lambda o: o.line([(xs[0], cy), (xs[-1], cy)], fill=(140, 200, 255, 220), width=6), 10)
    if v.get("span"):
        def bracket(o):
            by = cy - 120
            o.line([(xs[0], by + 22), (xs[0], by), (xs[-1], by), (xs[-1], by + 22)], fill=(180, 220, 255, 200), width=3)
        _glow_layer(img, bracket, 6)
        d = ImageDraw.Draw(img)
        nt = _plain(v["span"])[0]
        f = _mont(28, 700)
        tw = d.textlength(nt, font=f)
        mx = (xs[0] + xs[-1]) / 2
        _overlay(img, lambda o: o.rounded_rectangle([mx - tw / 2 - 24, cy - 148, mx + tw / 2 + 24, cy - 92],
                                                     radius=28, fill=(10, 40, 130, 255), outline=(150, 210, 255, 220), width=2))
        _center_text(ImageDraw.Draw(img), nt, mx, cy - 120, f, c["accent"])
    for i, (x, item) in enumerate(zip(xs, items)):
        text, hl = _plain(item)
        r = 30 if hl else 24
        _glow_layer(img, lambda o: o.ellipse([x - r, cy - r, x + r, cy + r], fill=(200, 235, 255, 255) if hl else (120, 190, 255, 255),
                                             outline=(230, 245, 255, 255), width=3), 12)
        d = ImageDraw.Draw(img)
        _wrap_center(d, text, x, cy + 78 + (34 if i % 2 else 0), _mont(26, 700), c["accent"] if hl else "white", 180, 30)


def _v_matrix(img, box, v, c):
    x0, y0, x1, y1 = box
    side = min(x1 - x0 - 120, y1 - y0 - 70)
    ox, oy = (x0 + x1) / 2 - side / 2 + 20, (y0 + y1) / 2 + side / 2 - 10
    def axes(o):
        o.line([(ox, oy), (ox + side, oy)], fill=(180, 220, 255, 220), width=4)
        o.line([(ox, oy), (ox, oy - side)], fill=(180, 220, 255, 220), width=4)
        o.polygon([(ox + side + 14, oy), (ox + side, oy - 9), (ox + side, oy + 9)], fill=(180, 220, 255, 220))
        o.polygon([(ox, oy - side - 14), (ox - 9, oy - side), (ox + 9, oy - side)], fill=(180, 220, 255, 220))
        for k in (1, 2, 3):
            o.line([(ox + side * k / 4, oy), (ox + side * k / 4, oy - side)], fill=(150, 200, 255, 45), width=2)
            o.line([(ox, oy - side * k / 4), (ox + side, oy - side * k / 4)], fill=(150, 200, 255, 45), width=2)
    _glow_layer(img, axes, 6)
    d = ImageDraw.Draw(img)
    f = _mont(24, 600)
    d.text((ox + side - d.textlength(v.get("x", ""), font=f), oy + 14), v.get("x", ""), font=f, fill=c["muted"])
    lbl = Image.new("RGBA", (400, 40), (0, 0, 0, 0))
    ImageDraw.Draw(lbl).text((0, 0), v.get("y", ""), font=f, fill=c["muted"])
    lbl = lbl.rotate(90, expand=True)
    img.alpha_composite(lbl, (int(ox - 48), int(oy - side + 0)))
    for p in v.get("points", []):
        text, hl = _plain(p.get("label", ""))
        px, py = ox + side * p.get("x", .5), oy - side * p.get("y", .5)
        r = 26 if hl else 16
        _glow_layer(img, lambda o: o.ellipse([px - r, py - r, px + r, py + r],
                                             fill=(210, 240, 255, 255) if hl else (120, 180, 255, 230)), 16 if hl else 6)
        d = ImageDraw.Draw(img)
        d.text((px + r + 12, py - 18), text, font=_mont(30 if hl else 26, 800 if hl else 600),
               fill=c["accent"] if hl else c["muted"])


def _v_chart(img, box, v, c):
    x0, y0, x1, y1 = box
    vals = v.get("values", [])
    split = v.get("forecast_from", len(vals))
    if len(vals) < 2:
        return
    lo, hi = min(vals), max(vals)
    gx0, gx1, gy0, gy1 = x0 + 30, x1 - 30, y0 + 40, y1 - 50
    pts = [(gx0 + (gx1 - gx0) * i / (len(vals) - 1), gy1 - (gy1 - gy0) * (vv - lo) / max(1e-9, hi - lo)) for i, vv in enumerate(vals)]
    def area(o):
        poly = pts[:split] + [(pts[split - 1][0], gy1), (pts[0][0], gy1)]
        o.polygon(poly, fill=(90, 170, 255, 70))
        for k in range(4):
            yy = gy0 + (gy1 - gy0) * k / 3
            o.line([(gx0, yy), (gx1, yy)], fill=(150, 200, 255, 40), width=2)
    _overlay(img, area)
    _glow_layer(img, lambda o: o.line(pts[:split], fill=(200, 235, 255, 255), width=7, joint="curve"), 12)
    def dashed(o):
        seg = pts[split - 1:]
        for a, b in zip(seg, seg[1:]):
            n = 8
            for k in range(0, n, 2):
                p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
                o.line([p, q], fill=_rgb(c["accent"]) + (255,), width=6)
        bx = pts[split - 1][0]
        for yy in range(int(gy0), int(gy1), 18):
            o.line([(bx, yy), (bx, yy + 9)], fill=(180, 220, 255, 120), width=2)
    _glow_layer(img, dashed, 8)
    d = ImageDraw.Draw(img)
    f = _mont(26, 700)
    d.text((pts[0][0], gy1 + 14), v.get("fact_label", "факт"), font=f, fill="white")
    fl = v.get("forecast_label", "прогноз")
    d.text((gx1 - d.textlength(fl, font=f), gy1 + 14), fl, font=f, fill=c["accent"])
    lx, ly = pts[split - 1]
    _glow_layer(img, lambda o: o.ellipse([lx - 14, ly - 14, lx + 14, ly + 14], fill=(255, 255, 255, 255)), 10)


def _v_donut(img, box, v, c):
    x0, y0, x1, y1 = box
    items = v.get("items", [])
    total = sum(i.get("value", 1) for i in items) or 1
    r = min((y1 - y0) / 2 - 10, (x1 - x0) * .25)
    cx, cy = x0 + r + 30, (y0 + y1) / 2
    shades = [(40, 110, 230), (70, 140, 245), (100, 165, 255), (135, 190, 255), (170, 210, 255)]
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(o)
    start = -90
    for i, item in enumerate(items):
        ext = 360 * item.get("value", 1) / total
        hl = _plain(item.get("label", ""))[1]
        col = _rgb(c["accent"]) if hl else shades[i % len(shades)]
        rr = r + (14 if hl else 0)
        od.pieslice([cx - rr, cy - rr, cx + rr, cy + rr], start + 1, start + ext - 1, fill=col + (255,))
        start += ext
    hole = r * .58
    od.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=(0, 0, 0, 0))
    mask = Image.new("L", (W, H), 255)
    ImageDraw.Draw(mask).ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=0)
    o.putalpha(Image.composite(o.getchannel("A"), Image.new("L", (W, H), 0), mask))
    img.alpha_composite(o.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(o)
    d = ImageDraw.Draw(img)
    _wrap_center(d, v.get("center", ""), cx, cy, _mont(28, 800), "white", hole * 1.7, 32)
    lx = cx + r + 60
    ly = cy - (len(items) - 1) * 56 / 2
    for i, item in enumerate(items):
        text, hl = _plain(item.get("label", ""))
        col = _rgb(c["accent"]) if hl else shades[i % len(shades)]
        d.rounded_rectangle([lx, ly - 13, lx + 26, ly + 13], radius=7, fill=col)
        d.text((lx + 42, ly - 18), text, font=_mont(30 if hl else 28, 800 if hl else 600),
               fill=c["accent"] if hl else "white")
        ly += 56


VISUALS = {"hub": _v_hub, "persona": _v_persona, "funnel": _v_funnel, "journey": _v_journey,
           "matrix": _v_matrix, "chart": _v_chart, "donut": _v_donut}


def _visual(img, box, v, c) -> None:
    fn = VISUALS.get(v.get("type", ""))
    if not fn:
        return
    x0, y0, x1, y1 = box
    note = v.get("note")
    if note:
        y1 -= 40
    fn(img, (x0, y0, x1, y1), v, c)
    if note:
        d = ImageDraw.Draw(img)
        _center_text(d, note, W / 2, y1 + 22, _mont(22, 500), c["muted"])
