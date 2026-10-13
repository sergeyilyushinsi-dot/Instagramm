"""Автоочистка текста перед публикацией скиллом ig-human (с русской адаптацией ru_fix).

Убирает невидимые символы, штампы и канцелярит так, чтобы грамматика не ломалась.
Если что-то пошло не так — возвращает исходный текст: очистка никогда не блокирует публикацию.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache

from . import config

HUMANIZE = config.ROOT / ".claude" / "skills" / "ig-human" / "humanize.py"


@lru_cache
def _module():
    spec = importlib.util.spec_from_file_location("ig_humanize", HUMANIZE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.load_lexicon()


def clean(text: str) -> str:
    if not text.strip():
        return text
    try:
        mod, lex = _module()
        return mod.humanize(text, lex)[0].strip()
    except Exception as exc:  # noqa: BLE001
        print(f"-- textfix: очистка пропущена ({exc})")
        return text
