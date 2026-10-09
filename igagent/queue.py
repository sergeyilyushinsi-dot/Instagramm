"""Очередь контента: каждый пост — отдельный YAML-файл в content/queue/.

Жизненный цикл: idea → draft → approved → published (или failed).
Ты одобряешь пост, поменяв в файле `status: draft` на `status: approved`
(можно прямо в веб-интерфейсе или приложении GitHub).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from . import config

Status = Literal["idea", "draft", "approved", "published", "failed", "skipped"]
Format = Literal["image", "carousel", "reels", "story"]


class Slide(BaseModel):
    title: str
    body: str = ""


class QueueItem(BaseModel):
    id: str
    status: Status = "idea"
    format: Format
    rubric: str
    topic: str
    hook: str = ""
    scheduled_at: datetime | None = None
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    alt_text: str = ""
    reels_script: str = ""
    cover_text: str = ""
    slides: list[Slide] = Field(default_factory=list)   # для экспертных каруселей
    media: list[str] = Field(default_factory=list)      # пути к файлам в content/ready
    media_brief: str = ""                               # что снять/найти, если медиа ещё нет
    notes: str = ""
    published_id: str | None = None
    permalink: str | None = None
    error: str | None = None

    @property
    def path(self) -> Path:
        return config.QUEUE_DIR / f"{self.id}.yaml"

    def full_caption(self) -> str:
        tags = " ".join(f"#{t.lstrip('#')}" for t in self.hashtags)
        return f"{self.caption}\n\n{tags}".strip()

    def save(self) -> None:
        data = self.model_dump(mode="json")
        self.path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )


def slugify(text: str, limit: int = 40) -> str:
    translit = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhccss_y_eua",
    )
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(translit)).strip("-")
    return slug[:limit].strip("-") or "post"


def new_id(topic: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(config.tz())).strftime("%Y%m%d-%H%M")
    base = f"{stamp}-{slugify(topic)}"
    candidate, n = base, 2
    while (config.QUEUE_DIR / f"{candidate}.yaml").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def load_all() -> list[QueueItem]:
    items = []
    for path in sorted(config.QUEUE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data:
            items.append(QueueItem.model_validate(data))
    return items


def by_status(*statuses: Status) -> list[QueueItem]:
    return [i for i in load_all() if i.status in statuses]
