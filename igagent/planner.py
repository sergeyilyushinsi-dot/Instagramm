"""Контент-план: идеи на неделю по рубрикам, слотам и данным аналитики."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from . import analytics, config, llm
from .queue import QueueItem, load_all, new_id


class PlannedPost(BaseModel):
    slot_index: int = Field(description="Индекс слота из списка, для story — -1")
    day_offset: int = Field(description="Для story: день недели плана 0-6, для постов — 0")
    format: Literal["image", "carousel", "reels", "story"]
    rubric: str
    topic: str
    hook: str = Field(description="Крючок / первая фраза")
    why: str = Field(description="Почему эта тема сейчас: связь с аналитикой или целью")
    media_needed: str = Field(description="Что нужно снять/подобрать автору; для текстовой карусели — 'не нужно'")


class WeekPlan(BaseModel):
    theme_of_week: str
    posts: list[PlannedPost]
    stories_idea: str = Field(description="Общая идея сторис на неделю (опросы, закулисье)")


def upcoming_slots(start: datetime, days: int = 7) -> list[datetime]:
    slots = config.settings()["schedule"]["slots"]
    out = []
    for d in range(days):
        day = (start + timedelta(days=d)).date()
        for s in slots:
            if day.weekday() == s["weekday"]:
                h, m = map(int, s["time"].split(":"))
                dt = datetime.combine(day, time(h, m), tzinfo=config.tz())
                if dt > start:
                    out.append(dt)
    return sorted(out)


def next_free_slot(fmt: str = "image") -> datetime:
    now = datetime.now(config.tz())
    if fmt == "story":
        return now + timedelta(hours=1)
    taken = {i.scheduled_at for i in load_all() if i.scheduled_at and i.status not in ("failed", "skipped")}
    for slot in upcoming_slots(now, days=60):
        if slot not in taken:
            return slot
    return now + timedelta(days=1)


def plan_week(start: datetime | None = None) -> list[QueueItem]:
    start = start or datetime.now(config.tz())
    taken = {i.scheduled_at for i in load_all() if i.scheduled_at}
    slots = [s for s in upcoming_slots(start) if s not in taken]
    recent = [f"{i.scheduled_at:%d.%m} {i.rubric}: {i.topic}" for i in load_all()[-30:] if i.scheduled_at]
    stories = config.settings()["schedule"].get("stories_per_day", 0)

    prompt = f"""Составь контент-план на неделю с {start:%d.%m.%Y}.
Свободные слоты для постов (индекс: время): {[f"{n}: {s:%a %d.%m %H:%M}" for n, s in enumerate(slots)]}
Сторис: по {stories} в день — запланируй {min(stories * 7, 7)} самых важных (остальные автор снимет сам).

Соблюдай доли рубрик из профиля, чередуй экспертное и личное, не повторяй недавние темы:
{recent or 'истории нет'}

Аналитика и спрос аудитории:
{analytics.latest_insights_text()}

Предпочитай форматы, которые лучше заходят. Экспертные карусели можно делать без фото —
слайды сгенерируются автоматически."""
    plan = llm.parse(prompt, WeekPlan, effort="high")

    items = []
    for p in plan.posts:
        if p.format == "story":
            day = (start + timedelta(days=max(0, min(6, p.day_offset)))).date()
            when = datetime.combine(day, time(13, 0), tzinfo=config.tz())
        elif 0 <= p.slot_index < len(slots):
            when = slots[p.slot_index]
        else:
            continue
        item = QueueItem(
            id=new_id(p.topic, when), status="idea", format=p.format, rubric=p.rubric, topic=p.topic,
            hook=p.hook, scheduled_at=when,
            media_brief="" if p.media_needed.strip().lower() == "не нужно" else p.media_needed,
            notes=f"Неделя: {plan.theme_of_week}\nПочему: {p.why}",
        )
        item.save()
        items.append(item)

    report = [f"# Контент-план с {start:%d.%m.%Y}\n", f"**Тема недели:** {plan.theme_of_week}\n",
              f"**Сторис:** {plan.stories_idea}\n", "| Когда | Формат | Рубрика | Тема | Нужно медиа |",
              "|---|---|---|---|---|"]
    report += [f"| {i.scheduled_at:%a %d.%m %H:%M} | {i.format} | {i.rubric} | {i.topic} | {i.media_brief or '—'} |"
               for i in sorted(items, key=lambda x: x.scheduled_at)]
    (config.REPORTS_DIR / f"{start:%Y-%m-%d}-plan.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return items
