"""Работа с контентом: разбор фото/видео из inbox, тексты постов, карусели."""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import analytics, config, llm, media, planner, slides
from .queue import QueueItem, Slide, new_id


# --- схемы ответов Claude -------------------------------------------------------
class MediaAnalysis(BaseModel):
    description: str = Field(description="Что на фото/видео, 1-2 предложения")
    quality_score: int = Field(description="Пригодность для публикации, 1-10")
    quality_issues: list[str] = Field(description="Проблемы: смаз, пересвет, мусор в кадре и т.п.")
    privacy_risks: list[str] = Field(description="Что может нарушать приватность: адреса, номера машин, документы, дети")
    best_format: Literal["image", "carousel", "reels", "story"]
    rubric: str = Field(description="id рубрики из профиля")
    topic: str = Field(description="О чём пост, коротко")
    cover_second: float = Field(description="Для видео — секунда с лучшим кадром для обложки, иначе 0")


class PostText(BaseModel):
    hook: str = Field(description="Первая строка, которая останавливает скролл")
    caption: str = Field(description="Полный текст подписи без хэштегов, с абзацами и CTA")
    hashtags: list[str] = Field(description="Хэштеги без #, смесь крупных и нишевых")
    alt_text: str = Field(description="Альтернативный текст для незрячих, 1 предложение")
    reels_script: str = Field(description="Для Reels: сценарий по секундам с текстом на экране; иначе пусто")
    cover_text: str = Field(description="Короткий текст на обложку (до 6 слов)")
    media_brief: str = Field(description="Если медиа нет — что снять или подобрать; иначе пусто")


class CarouselText(BaseModel):
    slides: list[Slide] = Field(description="5-9 слайдов: обложка-крючок, суть по шагам, вывод/CTA")


# --- разбор входящих медиа -----------------------------------------------------
def analyze_media(path: Path) -> MediaAnalysis:
    if media.is_video(path):
        frames = media.keyframes(path)
        info = media.probe(path)
        intro = (f"Это {len(frames)} равномерно взятых кадров из видео длиной {info['duration']:.0f} с. "
                 f"Кадр i снят примерно на секунде {info['duration']:.0f}*(i+0.5)/{len(frames)}.")
        blocks = [llm.image_block(f) for f in frames]
    else:
        intro = "Это фото, которое автор загрузил для публикации."
        blocks = [llm.image_block(media.preview(path))]
    prompt = (f"{intro}\nОцени материал для Instagram автора и предложи, как его использовать. "
              "Рубрику выбери из профиля.")
    return llm.parse(blocks + [{"type": "text", "text": prompt}], MediaAnalysis)


def process_inbox() -> list[QueueItem]:
    """Обрабатывает новые файлы из content/inbox: формат, кадрирование, анализ, черновик поста.

    Файлы в одной подпапке inbox/<имя>/ объединяются в одну карусель.
    """
    items = []
    groups: list[list[Path]] = []
    for entry in sorted(config.INBOX_DIR.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            files = [f for f in sorted(entry.iterdir()) if media.is_image(f) or media.is_video(f)]
            if files:
                groups.append(files)
        elif media.is_image(entry) or media.is_video(entry):
            groups.append([entry])

    for files in groups:
        existing = _queue_item_for(files[0])
        if existing:
            items.append(_attach_media(existing, files))
            continue
        if not os.environ.get("ANTHROPIC_API_KEY"):
            # Без ключа Claude новые файлы ждут разбора в сессии с Claude
            print(f"ждёт разбора: {files[0].relative_to(config.ROOT)}")
            continue
        analysis = analyze_media(files[0])
        fmt = "carousel" if len(files) > 1 else analysis.best_format
        if media.is_video(files[0]) and fmt not in ("reels", "story"):
            fmt = "reels"
        item_id = new_id(analysis.topic)
        out_dir = config.READY_DIR / item_id
        processed: list[Path] = []
        for f in files:
            if media.is_video(f):
                processed.append(media.process_video(f, out_dir))
            else:
                aspect = "9:16" if fmt == "story" else None
                processed.append(media.process_image(f, out_dir, aspect=aspect))
        if fmt == "reels" and analysis.cover_second:
            processed.append(media.extract_cover(files[0], out_dir, analysis.cover_second))

        notes = [f"Анализ: {analysis.description} (качество {analysis.quality_score}/10)"]
        if analysis.quality_issues:
            notes.append("Проблемы: " + "; ".join(analysis.quality_issues))
        if analysis.privacy_risks:
            notes.append("⚠️ ПРИВАТНОСТЬ: " + "; ".join(analysis.privacy_risks))

        item = QueueItem(
            id=item_id, status="draft", format=fmt, rubric=analysis.rubric, topic=analysis.topic,
            media=[str(p.relative_to(config.ROOT)) for p in processed], notes="\n".join(notes),
            scheduled_at=planner.next_free_slot(fmt),
        )
        write_post(item, media_paths=processed)
        item.save()
        items.append(item)

        _archive(item_id, files)
    return items


def _archive(item_id: str, files: list[Path]) -> None:
    archive = config.CONTENT_DIR / "originals" / item_id
    archive.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.move(str(f), archive / f.name)
    if files[0].parent != config.INBOX_DIR and not any(files[0].parent.iterdir()):
        files[0].parent.rmdir()


def _queue_item_for(file: Path) -> QueueItem | None:
    """Папка inbox/<id-поста>/ — это медиа для уже запланированной идеи."""
    if file.parent == config.INBOX_DIR:
        return None
    path = config.QUEUE_DIR / f"{file.parent.name}.yaml"
    if not path.exists():
        return None
    import yaml
    return QueueItem.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _attach_media(item: QueueItem, files: list[Path]) -> QueueItem:
    out_dir = config.READY_DIR / item.id
    processed = []
    for f in files:
        if media.is_video(f):
            processed.append(media.process_video(f, out_dir))
        else:
            processed.append(media.process_image(f, out_dir, aspect="9:16" if item.format == "story" else None))
    item.media = [str(p.relative_to(config.ROOT)) for p in processed]
    item.slides = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        write_post(item, media_paths=processed)  # переписываем текст с учётом реальных кадров
    item.media_brief = ""
    item.status = "draft"
    item.save()
    _archive(item.id, files)
    return item


# --- тексты ------------------------------------------------------------------
def write_post(item: QueueItem, media_paths: list[Path] | None = None) -> QueueItem:
    """Пишет подпись, хэштеги, сценарий Reels; для экспертных каруселей без фото — слайды."""
    media_paths = media_paths or [config.ROOT / m for m in item.media]
    blocks: list[dict] = []
    for p in media_paths[:5]:
        if media.is_image(p):
            blocks.append(llm.image_block(media.preview(p)))
        elif media.is_video(p):
            blocks.extend(llm.image_block(f) for f in media.keyframes(p, count=4))

    insights = analytics.latest_insights_text()
    prompt = f"""Напиши текст для публикации в Instagram.
Формат: {item.format}
Рубрика: {item.rubric}
Тема: {item.topic}
Идея/крючок из плана: {item.hook or '—'}
Заметки: {item.notes or '—'}
Медиа: {'прикреплены выше' if blocks else 'пока нет'}

Что известно о том, что заходит аудитории:
{insights}

Требования: первая строка — сильный крючок; абзацы короткие; в конце один CTA из профиля
(или лучше подходящий по смыслу); хэштегов не больше лимита из профиля, без запрещённых.
Для story подпись короткая (это текст на экране)."""
    text = llm.parse(blocks + [{"type": "text", "text": prompt}], PostText)
    item.hook, item.caption, item.alt_text = text.hook, text.caption, text.alt_text
    hashtag_cfg = config.profile().get("hashtags", {})
    banned = {t.lower().lstrip("#") for t in hashtag_cfg.get("banned", [])}
    tags = [t.lstrip("#") for t in hashtag_cfg.get("always", [])] + text.hashtags
    tags = [t for t in dict.fromkeys(tags) if t.lower() not in banned]
    item.hashtags = tags[: hashtag_cfg.get("max_per_post", 8)]
    item.reels_script, item.cover_text = text.reels_script, text.cover_text
    if not media_paths:
        item.media_brief = text.media_brief or item.media_brief

    # Экспертная карусель без фото — генерируем слайды сами
    if item.format == "carousel" and not media_paths:
        carousel = llm.parse(
            f"Сделай текст слайдов карусели по теме «{item.topic}». Крючок: {item.hook}. "
            "На слайде: заголовок до 8 слов и пояснение до 35 слов. Без воды.",
            CarouselText,
        )
        item.slides = carousel.slides
        out_dir = config.READY_DIR / item.id
        paths = slides.render([s.model_dump() for s in item.slides], out_dir, config.profile().get("handle", ""))
        item.media = [str(p.relative_to(config.ROOT)) for p in paths]
        item.media_brief = ""
    if item.media and item.status == "idea":
        item.status = "draft"
    return item


def write_pending_ideas() -> list[QueueItem]:
    """Дописывает тексты для идей из контент-плана."""
    from .queue import by_status

    done = []
    for item in by_status("idea"):
        if item.caption:
            continue
        write_post(item)
        item.save()
        done.append(item)
    return done


def ready_to_publish(now: datetime) -> list[QueueItem]:
    from .queue import by_status

    statuses = ("approved",) if config.settings()["approval"]["require_for_posts"] else ("approved", "draft")
    return [i for i in by_status(*statuses)
            if i.media and i.scheduled_at and i.scheduled_at <= now]
