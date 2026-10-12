"""Публикация одобренных постов, у которых наступило время: Instagram (Reels, сторис) и Telegram."""
from __future__ import annotations

import os
import shutil
from datetime import datetime

from . import config, content, media
from .queue import QueueItem

REQUIRED = {
    "instagram": ["IG_USER_ID", "IG_ACCESS_TOKEN", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY",
                  "PUBLIC_MEDIA_BASE_URL"],
    "telegram": ["TG_BOT_TOKEN", "TG_CHANNEL"],
}


def missing_secrets(channel: str) -> list[str]:
    return [n for n in REQUIRED[channel] if not os.environ.get(n)]


def _publish_instagram(item: QueueItem, paths) -> None:
    from .instagram import Instagram

    ig = Instagram()
    if item.format == "story":
        media_id = None
        for p in paths:  # каждая сторис — отдельная публикация
            media_id = ig.publish_story(media.upload(p))
    elif item.format == "reels":
        video = next(p for p in paths if media.is_video(p))
        cover = next((p for p in paths if p.name.endswith("_cover.jpg")), None)
        media_id = ig.publish_reel(media.upload(video), item.full_caption(),
                                   cover_url=media.upload(cover) if cover else None)
    elif item.format == "carousel" and len(paths) > 1:
        media_id = ig.publish_carousel([media.upload(p) for p in paths], item.full_caption())
    else:
        media_id = ig.publish_image(media.upload(paths[0]), item.full_caption(), item.alt_text)
    item.published_id = media_id
    item.permalink = ig.permalink(media_id) if media_id and item.format != "story" else None


def _publish_telegram(item: QueueItem, paths) -> None:
    from .telegram import Telegram

    tg = Telegram()
    ids = tg.publish(item.full_caption(), paths)
    item.published_id = ",".join(map(str, ids))
    item.permalink = tg.link(ids[0]) if ids else None


def publish_item(item: QueueItem) -> QueueItem:
    paths = [config.ROOT / m for m in item.media]
    try:
        if item.channel == "telegram":
            _publish_telegram(item, paths)
        else:
            _publish_instagram(item, paths)
        item.status, item.error = "published", None
    except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку в карточке поста
        item.status, item.error = "failed", str(exc)[:2000]
    item.save()
    if item.status == "published":
        shutil.move(str(item.path), config.PUBLISHED_DIR / item.path.name)
    return item


def publish_due(now: datetime | None = None) -> list[QueueItem]:
    now = now or datetime.now(config.tz())
    done = []
    for item in content.ready_to_publish(now):
        missing = missing_secrets(item.channel)
        if missing:
            print(f"-- {item.id}: {item.channel} ждёт секретов {', '.join(missing)}")
            continue
        done.append(publish_item(item))
    return done
