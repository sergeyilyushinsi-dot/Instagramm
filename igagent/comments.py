"""Комментарии: черновики ответов и отправка одобренных.

Черновики лежат в content/replies.yaml. Чтобы отправить ответ, поставь у него
`approved: true` (можно поправить текст). Простые комментарии (спасибо, эмодзи)
агент может отправлять сам, если в settings.yaml approval.require_for_replies: false.
"""
from __future__ import annotations

import json
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from . import config, llm

REPLIES_FILE = config.CONTENT_DIR / "replies.yaml"
SEEN_FILE = config.DATA_DIR / "seen_comments.json"


class ReplyDraft(BaseModel):
    comment_id: str
    category: Literal["thanks", "question", "feedback", "negative", "spam", "lead"]
    reply: str = Field(description="Ответ от лица автора; для spam — пусто")


class ReplyBatch(BaseModel):
    replies: list[ReplyDraft]


def _load_replies() -> list[dict]:
    if not REPLIES_FILE.exists():
        return []
    return yaml.safe_load(REPLIES_FILE.read_text(encoding="utf-8")) or []


def _save_replies(rows: list[dict]) -> None:
    REPLIES_FILE.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")


def draft_replies(ig, posts_limit: int = 10) -> int:
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    me = ig.account().get("username")
    fresh = []
    for post in ig.recent_media(limit=posts_limit):
        for c in ig.comments(post["id"]):
            if c["id"] in seen or c.get("username") == me:
                continue
            replies = c.get("replies", {}).get("data", [])
            if any(r.get("username") == me for r in replies):
                seen.add(c["id"])
                continue
            fresh.append({"comment_id": c["id"], "username": c.get("username"), "text": c.get("text", ""),
                          "post_caption": (post.get("caption") or "")[:300], "permalink": post.get("permalink")})
    if not fresh:
        return 0

    batch = llm.parse(
        "Подготовь ответы на комментарии в Instagram от лица автора. Коротко, тепло, по существу; "
        "на вопрос — полезный ответ или приглашение в директ, если нужен личный разбор; "
        "на негатив — спокойно и без оправданий; на спам — пустой ответ. "
        "Категория lead — если человек явно интересуется услугой/консультацией.\n\n"
        + json.dumps(fresh, ensure_ascii=False),
        ReplyBatch, effort="low",
    )
    by_id = {c["comment_id"]: c for c in fresh}
    auto = not config.settings()["approval"]["require_for_replies"]
    rows = _load_replies()
    for d in batch.replies:
        src = by_id.get(d.comment_id)
        if not src:
            continue
        seen.add(d.comment_id)
        if d.category == "spam" or not d.reply:
            continue
        rows.append({**src, "category": d.category, "reply": d.reply,
                     "approved": auto and d.category == "thanks", "sent": False})
    _save_replies(rows)
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    return len(batch.replies)


def send_approved(ig) -> int:
    rows = _load_replies()
    sent = 0
    for row in rows:
        if row.get("approved") and not row.get("sent"):
            row["reply_id"] = ig.reply(row["comment_id"], row["reply"])
            row["sent"] = True
            sent += 1
    # Отправленные старше последних 200 убираем, чтобы файл не рос бесконечно
    pending = [r for r in rows if not r.get("sent")]
    done = [r for r in rows if r.get("sent")][-200:]
    _save_replies(pending + done)
    return sent
