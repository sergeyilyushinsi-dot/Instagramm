"""Командная строка агента: python -m igagent <команда>."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from . import analytics, comments, config, content, planner, publisher
from .instagram import Instagram
from .queue import load_all


def cmd_inbox(_):
    for item in content.process_inbox():
        print(f"draft: {item.id} [{item.format}] {item.topic}")


def cmd_plan(_):
    for item in planner.plan_week():
        print(f"idea: {item.scheduled_at:%a %d.%m %H:%M} [{item.format}] {item.topic}")


def cmd_write(_):
    for item in content.write_pending_ideas():
        print(f"{item.status}: {item.id} — {item.hook}")


def cmd_publish(_):
    for item in publisher.publish_due(Instagram()):
        print(f"{item.status}: {item.id} {item.permalink or item.error or ''}")


def cmd_sync(_):
    print(analytics.sync(Instagram()))


def cmd_analyze(_):
    ig = Instagram()
    analytics.sync(ig)
    report = analytics.analyze_demand(ig)
    print(report.summary)


def cmd_comments(_):
    ig = Instagram()
    print(f"новых комментариев разобрано: {comments.draft_replies(ig)}")
    print(f"ответов отправлено: {comments.send_approved(ig)}")


def cmd_status(_):
    rows = ["# Очередь контента\n", f"Обновлено: {datetime.now(config.tz()):%d.%m.%Y %H:%M}\n",
            "| Когда | Статус | Формат | Тема | Медиа | Файл |", "|---|---|---|---|---|---|"]
    items = sorted(load_all(), key=lambda i: i.scheduled_at or datetime.max.replace(tzinfo=config.tz()))
    for i in items:
        when = f"{i.scheduled_at:%a %d.%m %H:%M}" if i.scheduled_at else "—"
        media = f"{len(i.media)} шт." if i.media else f"нужно: {i.media_brief or '—'}"
        rows.append(f"| {when} | {i.status} | {i.format} | {i.topic} | {media} | [yaml](../content/queue/{i.id}.yaml) |")
    (config.REPORTS_DIR / "queue.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))


def cmd_refresh_token(_):
    token = Instagram().refresh_token()["access_token"]
    out = os.environ.get("NEW_TOKEN_FILE")
    if out:
        with open(out, "w") as f:
            f.write(token)
        print("Новый токен записан во временный файл")
    else:
        print(token)


def cmd_tick(_):
    """Один «такт» по расписанию (запускается раз в час из GitHub Actions)."""
    now = datetime.now(config.tz())
    steps = [("inbox", cmd_inbox), ("publish", cmd_publish), ("comments", cmd_comments)]
    if now.hour == 7:
        steps.append(("analyze", cmd_analyze))
    if now.weekday() == 6 and now.hour == 10:
        steps.append(("plan", cmd_plan))
    if now.hour in (10, 18):
        steps.append(("write", cmd_write))
    steps.append(("status", cmd_status))
    failed = False
    for name, fn in steps:
        print(f"== {name}")
        try:
            fn(None)
        except Exception as exc:  # noqa: BLE001 — один упавший шаг не должен ронять остальные
            failed = True
            print(f"!! {name} упал: {exc}", file=sys.stderr)
    if failed:
        sys.exit(1)


COMMANDS = {
    "inbox": (cmd_inbox, "обработать новые фото/видео из content/inbox"),
    "plan": (cmd_plan, "составить контент-план на неделю"),
    "write": (cmd_write, "написать тексты для идей из плана"),
    "publish": (cmd_publish, "опубликовать одобренные посты, время которых пришло"),
    "sync": (cmd_sync, "скачать статистику"),
    "analyze": (cmd_analyze, "статистика + анализ спроса аудитории"),
    "comments": (cmd_comments, "черновики ответов и отправка одобренных"),
    "status": (cmd_status, "сводка очереди в reports/queue.md"),
    "refresh-token": (cmd_refresh_token, "продлить токен Instagram"),
    "tick": (cmd_tick, "всё по расписанию (для cron)"),
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="igagent", description="Агент для Instagram")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        sub.add_parser(name, help=help_text)
    args = parser.parse_args()
    COMMANDS[args.command][0](args)


if __name__ == "__main__":
    main()
