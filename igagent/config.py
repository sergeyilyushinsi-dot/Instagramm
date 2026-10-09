from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
CONTENT_DIR = ROOT / "content"
INBOX_DIR = CONTENT_DIR / "inbox"
READY_DIR = CONTENT_DIR / "ready"
QUEUE_DIR = CONTENT_DIR / "queue"
PUBLISHED_DIR = CONTENT_DIR / "published"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@lru_cache
def profile() -> dict:
    return yaml.safe_load((CONFIG_DIR / "profile.yaml").read_text(encoding="utf-8"))


@lru_cache
def settings() -> dict:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))


def tz() -> ZoneInfo:
    return ZoneInfo(settings().get("timezone", "UTC"))


def env(name: str, required: bool = True) -> str:
    # Убираем пробелы, переносы строк и кавычки, которые часто попадают при копировании
    value = os.environ.get(name, "").strip().strip("'\"").strip()
    if required and not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


def profile_text() -> str:
    """Профиль в виде YAML-текста для системного промпта."""
    return yaml.safe_dump(profile(), allow_unicode=True, sort_keys=False)
