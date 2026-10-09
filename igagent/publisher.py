"""Публикация одобренных постов, у которых наступило время."""
from __future__ import annotations

import shutil
from datetime import datetime

from . import config, content, media
from .instagram import Instagram
from .queue import QueueItem


def publish_item(ig: Instagram, item: QueueItem) -> QueueItem:
    paths = [config.ROOT / m for m in item.media]
    try:
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
        item.status, item.error = "published", None
    except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку в карточке поста
        item.status, item.error = "failed", str(exc)[:2000]
    item.save()
    if item.status == "published":
        shutil.move(str(item.path), config.PUBLISHED_DIR / item.path.name)
    return item


def publish_due(ig: Instagram, now: datetime | None = None) -> list[QueueItem]:
    now = now or datetime.now(config.tz())
    return [publish_item(ig, item) for item in content.ready_to_publish(now)]
