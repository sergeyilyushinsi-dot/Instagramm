"""Публикация в Telegram-канал через Bot API.

Бот создаётся в @BotFather и добавляется в канал администратором с правом публикации.
Файлы загружаются напрямую — публичное хранилище не нужно.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import requests

from . import config

CAPTION_LIMIT = 1024   # подпись к фото/альбому
TEXT_LIMIT = 4096      # обычное сообщение


class TelegramError(RuntimeError):
    pass


def _format(text: str) -> str:
    """Экранирует HTML и превращает *слово* в жирный — так же, как выделение на слайдах."""
    import re

    escaped = html.escape(text, quote=False)
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", escaped)


def _split(text: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for para in text.split("\n\n"):
        candidate = f"{cur}\n\n{para}" if cur else para
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
        while len(para) > limit:
            parts.append(para[:limit])
            para = para[limit:]
        cur = para
    if cur:
        parts.append(cur)
    return parts


class Telegram:
    def __init__(self) -> None:
        self.token = config.env("TG_BOT_TOKEN")
        self.chat = config.env("TG_CHANNEL")  # @username канала или числовой id -100…

    def _call(self, method: str, files: dict | None = None, **params) -> dict:
        resp = requests.post(f"https://api.telegram.org/bot{self.token}/{method}",
                             data=params, files=files, timeout=120)
        payload = resp.json()
        if not payload.get("ok"):
            raise TelegramError(f"{method}: {payload.get('description', resp.text)}")
        return payload["result"]

    # --- проверка ------------------------------------------------------------
    def check(self) -> str:
        me = self._call("getMe")
        chat = self._call("getChat", chat_id=self.chat)
        member = self._call("getChatMember", chat_id=self.chat, user_id=me["id"])
        if member.get("status") != "administrator" or not member.get("can_post_messages", True):
            raise TelegramError(f"бот @{me['username']} не админ канала или не может публиковать")
        return f"бот @{me['username']} публикует в «{chat.get('title')}»"

    # --- публикация ----------------------------------------------------------
    def send_text(self, text: str) -> list[int]:
        return [self._call("sendMessage", chat_id=self.chat, text=part, parse_mode="HTML",
                           link_preview_options=json.dumps({"is_disabled": True}))["message_id"]
                for part in _split(_format(text), TEXT_LIMIT)]

    def send_photo(self, path: Path, caption: str = "") -> int:
        with open(path, "rb") as f:
            return self._call("sendPhoto", files={"photo": f}, chat_id=self.chat,
                              caption=_format(caption), parse_mode="HTML")["message_id"]

    def send_album(self, paths: list[Path], caption: str = "") -> list[int]:
        ids = []
        for start in range(0, len(paths), 10):  # в альбоме максимум 10 файлов
            chunk = paths[start:start + 10]
            files, media = {}, []
            for i, p in enumerate(chunk):
                key = f"file{i}"
                files[key] = open(p, "rb")
                kind = "video" if p.suffix.lower() in (".mp4", ".mov") else "photo"
                entry = {"type": kind, "media": f"attach://{key}"}
                if i == 0 and start == 0 and caption:
                    entry.update(caption=_format(caption), parse_mode="HTML")
                media.append(entry)
            try:
                result = self._call("sendMediaGroup", files=files, chat_id=self.chat, media=json.dumps(media))
            finally:
                for f in files.values():
                    f.close()
            ids += [m["message_id"] for m in result]
        return ids

    def publish(self, text: str, paths: list[Path]) -> list[int]:
        """Пост с картинками: короткий текст — подписью, длинный — отдельным сообщением после альбома."""
        if not paths:
            return self.send_text(text)
        short = len(_format(text)) <= CAPTION_LIMIT
        if len(paths) == 1:
            ids = [self.send_photo(paths[0], text if short else "")]
        else:
            ids = self.send_album(paths, text if short else "")
        if not short:
            ids += self.send_text(text)
        return ids

    def link(self, message_id: int) -> str | None:
        return f"https://t.me/{self.chat.lstrip('@')}/{message_id}" if self.chat.startswith("@") else None
