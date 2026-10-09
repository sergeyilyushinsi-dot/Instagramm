"""Обработка фото и видео под требования Instagram + загрузка в публичное хранилище."""
from __future__ import annotations

import json
import mimetypes
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from . import config

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

ASPECTS = {"4:5": (1080, 1350), "1:1": (1080, 1080), "1.91:1": (1080, 566), "9:16": (1080, 1920)}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXT


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


# --- фото ---------------------------------------------------------------------
def process_image(src: Path, dst_dir: Path, aspect: str | None = None, enhance: bool | None = None) -> Path:
    """Поворот по EXIF, кадрирование по центру под формат, лёгкая автокоррекция, JPEG 1080px."""
    media_cfg = config.settings().get("media", {})
    aspect = aspect or media_cfg.get("image_aspect", "4:5")
    enhance = media_cfg.get("enhance_photos", True) if enhance is None else enhance

    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    img = ImageOps.fit(img, ASPECTS[aspect], method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    if enhance:
        img = ImageOps.autocontrast(img, cutoff=0.5)
        img = ImageEnhance.Sharpness(img).enhance(1.15)
        img = ImageEnhance.Color(img).enhance(1.05)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.stem}_{aspect.replace(':', 'x')}.jpg"
    img.save(dst, "JPEG", quality=92, optimize=True, progressive=True)
    return dst


def preview(src: Path, max_side: int = 1280) -> Path:
    """Уменьшенная копия для анализа через Claude (экономит токены)."""
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = Path(tempfile.mkdtemp()) / f"{src.stem}_preview.jpg"
    img.save(out, "JPEG", quality=85)
    return out


# --- видео --------------------------------------------------------------------
def probe(src: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(src)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(out.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    return {
        "duration": float(info["format"].get("duration", 0)),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
    }


def process_video(src: Path, dst_dir: Path, max_seconds: int | None = None) -> Path:
    """Перекодирование в формат Reels: 1080x1920 (9:16), H.264 + AAC, 30 fps, faststart."""
    max_seconds = max_seconds or config.settings().get("media", {}).get("max_reel_seconds", 90)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.stem}_reel.mp4"
    info = probe(src)
    # Вертикальное видео — кадрируем по центру; горизонтальное — вписываем с размытым фоном
    if info["height"] >= info["width"]:
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    else:
        vf = ("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if not info["has_audio"]:
        # У Reels должна быть аудиодорожка — добавляем тишину
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-shortest"]
    cmd += ["-t", str(max_seconds), "-filter_complex" if "split" in vf else "-vf", vf,
            "-r", "30", "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst


def keyframes(src: Path, count: int = 6) -> list[Path]:
    """Равномерно вынимает кадры из видео, чтобы Claude мог «посмотреть» ролик."""
    duration = probe(src)["duration"] or 1
    out_dir = Path(tempfile.mkdtemp())
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        frame = out_dir / f"frame_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=720:-2", "-q:v", "3", str(frame)], check=True, capture_output=True)
        frames.append(frame)
    return frames


def extract_cover(src: Path, dst_dir: Path, at_second: float) -> Path:
    dst = dst_dir / f"{src.stem}_cover.jpg"
    subprocess.run(["ffmpeg", "-y", "-ss", f"{at_second:.2f}", "-i", str(src), "-frames:v", "1",
                    "-q:v", "2", str(dst)], check=True, capture_output=True)
    return dst


# --- хранилище ----------------------------------------------------------------
def upload(path: Path) -> str:
    """Загружает файл в S3-совместимое хранилище и возвращает публичный URL."""
    import boto3

    storage = config.settings().get("storage", {})
    prefix = storage.get("prefix", "instagram/")
    key = f"{prefix}{path.parent.name}/{path.name}"
    s3 = boto3.client(
        "s3",
        endpoint_url=config.env("S3_ENDPOINT_URL", required=False) or None,
        aws_access_key_id=config.env("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=config.env("S3_SECRET_ACCESS_KEY"),
        region_name=config.env("S3_REGION", required=False) or "auto",
    )
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    s3.upload_file(str(path), config.env("S3_BUCKET"), key, ExtraArgs={"ContentType": content_type})
    return f"{config.env('PUBLIC_MEDIA_BASE_URL').rstrip('/')}/{key}"
