"""Обёртка над Claude API: текст, структурированный вывод, картинки."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_TEMPLATE = """Ты — SMM-агент, который ведёт Instagram-аккаунт автора: экспертный блог с личной частью.
Пиши на языке профиля, от лица автора, строго в его голосе. Не выдумывай факты биографии,
цифры, кейсы и клиентов, которых нет в профиле или во входных данных — если чего-то не хватает,
оставь пометку [УТОЧНИТЬ: ...]. Соблюдай список тем, которыми автор не делится.

Профиль автора:
{profile}"""


class RefusalError(RuntimeError):
    pass


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _system() -> list[dict]:
    # Профиль стабилен между вызовами — кэшируем его.
    return [
        {
            "type": "text",
            "text": SYSTEM_TEMPLATE.format(profile=config.profile_text()),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _params(effort: str | None) -> dict:
    claude_cfg = config.settings().get("claude", {})
    return {
        "model": claude_cfg.get("model", "claude-opus-5-5"),
        "max_tokens": 16000,
        "system": _system(),
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort or claude_cfg.get("effort", "medium")},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def image_block(path: Path) -> dict:
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _check(response) -> None:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise RefusalError(f"Claude отказался выполнить запрос: {details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Ответ Claude обрезан по max_tokens")


def parse(prompt: str | list[dict], schema: type[T], effort: str | None = None,
          tools: list[dict] | None = None) -> T:
    """Запрос со структурированным ответом в виде pydantic-модели."""
    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    params = _params(effort)
    if tools:
        params["tools"] = tools
    response = client().beta.messages.parse(
        messages=[{"role": "user", "content": content}],
        output_format=schema,
        **params,
    )
    _check(response)
    if response.parsed_output is None:
        raise RuntimeError("Claude вернул ответ, который не прошёл валидацию схемы")
    return response.parsed_output


def text(prompt: str | list[dict], effort: str | None = None, tools: list[dict] | None = None) -> str:
    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    params = _params(effort)
    if tools:
        params["tools"] = tools
    params["max_tokens"] = 64000
    with client().beta.messages.stream(messages=[{"role": "user", "content": content}], **params) as stream:
        response = stream.get_final_message()
    _check(response)
    return "".join(b.text for b in response.content if b.type == "text")


WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
