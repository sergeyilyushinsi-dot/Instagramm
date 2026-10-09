"""Сбор статистики и анализ спроса аудитории."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import yaml
from pydantic import BaseModel, Field

from . import config, llm

POSTS_FILE = config.DATA_DIR / "posts.json"
ACCOUNT_FILE = config.DATA_DIR / "account_history.json"
INSIGHTS_FILE = config.DATA_DIR / "insights.json"


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _rubrics_by_media_id() -> dict[str, dict]:
    out = {}
    for path in config.PUBLISHED_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("published_id"):
            out[data["published_id"]] = {"rubric": data.get("rubric"), "topic": data.get("topic")}
    return out


def sync(ig) -> dict:
    """Скачивает метрики аккаунта и последних публикаций в data/."""
    account = ig.account()
    history = _read(ACCOUNT_FILE, [])
    history.append({"date": datetime.now(config.tz()).isoformat(timespec="minutes"), **account})
    _write(ACCOUNT_FILE, history[-400:])

    lookback = config.settings().get("analytics", {}).get("lookback_days", 60)
    since = datetime.now(config.tz()) - timedelta(days=lookback)
    known = _rubrics_by_media_id()
    posts = []
    for m in ig.recent_media(limit=100):
        ts = datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
        if ts < since:
            continue
        m["insights"] = ig.media_insights(m["id"], m.get("media_product_type", ""))
        m.update(known.get(m["id"], {}))
        reach = m["insights"].get("reach") or 0
        interactions = m["insights"].get("total_interactions") or (m.get("like_count", 0) + m.get("comments_count", 0))
        m["engagement_rate"] = round(interactions / reach, 4) if reach else None
        m["save_rate"] = round((m["insights"].get("saved") or 0) / reach, 4) if reach else None
        posts.append(m)
    _write(POSTS_FILE, posts)
    return {"account": account, "posts": len(posts)}


def _group_stats(posts: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for p in posts:
        if p.get("engagement_rate") is not None:
            groups[p.get(key) or "unknown"].append(p)
    return {
        k: {
            "posts": len(v),
            "avg_reach": round(statistics.mean(p["insights"].get("reach") or 0 for p in v)),
            "avg_engagement_rate": round(statistics.mean(p["engagement_rate"] for p in v), 4),
            "avg_save_rate": round(statistics.mean(p["save_rate"] or 0 for p in v), 4),
        }
        for k, v in groups.items()
    }


class DemandReport(BaseModel):
    summary: str = Field(description="Главное за период в 3-5 предложениях")
    what_works: list[str] = Field(description="Форматы/темы/подачи, которые заходят, с цифрами")
    what_fails: list[str] = Field(description="Что не заходит и почему, с цифрами")
    audience_questions: list[str] = Field(description="Вопросы и боли из комментариев, сгруппированные")
    content_gaps: list[str] = Field(description="Темы, на которые есть спрос, но нет контента")
    trend_ideas: list[str] = Field(description="Идеи по трендам ниши (если был веб-поиск)")
    recommendations: list[str] = Field(description="5-8 конкретных действий на следующие 2 недели")
    best_posting_times: list[str] = Field(description="Лучшие дни/часы по данным, если видно")


def analyze_demand(ig) -> DemandReport:
    posts = _read(POSTS_FILE, [])
    history = _read(ACCOUNT_FILE, [])
    comments = []
    for p in sorted(posts, key=lambda x: x.get("comments_count", 0), reverse=True)[:15]:
        for c in ig.comments(p["id"])[:40]:
            comments.append({"post": (p.get("caption") or "")[:80], "text": c.get("text", "")})
    demographics = ig.audience_demographics()

    compact_posts = [
        {k: p.get(k) for k in ("timestamp", "media_product_type", "media_type", "rubric", "like_count",
                               "comments_count", "engagement_rate", "save_rate")}
        | {"reach": p["insights"].get("reach"), "caption": (p.get("caption") or "")[:200]}
        for p in posts
    ]
    trends = ""
    if config.settings().get("analytics", {}).get("use_web_search", True):
        niche = config.profile().get("expertise", {}).get("niche", "")
        trends = llm.text(
            f"Найди актуальные (последние 1-2 месяца) темы, вопросы и форматы Instagram/Reels в нише: «{niche}», "
            "для русскоязычной аудитории. Дай короткий список с пояснениями.",
            effort="low", tools=[llm.WEB_SEARCH_TOOL],
        )

    data = {
        "account_history": history[-30:],
        "by_format": _group_stats(posts, "media_product_type"),
        "by_rubric": _group_stats(posts, "rubric"),
        "posts": compact_posts,
        "comments": comments[:300],
        "demographics": demographics,
    }
    prompt = ("Проанализируй статистику аккаунта и комментарии и определи, какой контент нужен аудитории.\n"
              "Опирайся на цифры; если данных мало — так и скажи.\n\n"
              f"Данные:\n{json.dumps(data, ensure_ascii=False)}\n\nТренды ниши из веб-поиска:\n{trends or 'нет'}")
    report = llm.parse(prompt, DemandReport, effort="high")

    _write(INSIGHTS_FILE, {"date": datetime.now(config.tz()).isoformat(timespec="minutes"),
                           **report.model_dump(), "stats": {"by_format": data["by_format"],
                                                            "by_rubric": data["by_rubric"]}})
    _write_report(report, data)
    return report


def _write_report(report: DemandReport, data: dict) -> None:
    today = datetime.now(config.tz()).date().isoformat()
    followers = data["account_history"][-1].get("followers_count") if data["account_history"] else "—"

    def section(title, items):
        return f"## {title}\n" + ("\n".join(f"- {i}" for i in items) or "- нет данных") + "\n"

    def table(stats):
        rows = ["| | постов | ср. охват | ER | сохранения |", "|---|---|---|---|---|"]
        rows += [f"| {k} | {v['posts']} | {v['avg_reach']} | {v['avg_engagement_rate']:.1%} | {v['avg_save_rate']:.1%} |"
                 for k, v in sorted(stats.items(), key=lambda kv: -kv[1]["avg_engagement_rate"])]
        return "\n".join(rows) + "\n"

    md = [f"# Аналитика {today}\n", f"Подписчиков: **{followers}**\n", report.summary + "\n",
          "## По форматам\n" + table(data["by_format"]), "## По рубрикам\n" + table(data["by_rubric"]),
          section("Что работает", report.what_works), section("Что не работает", report.what_fails),
          section("Вопросы аудитории", report.audience_questions), section("Пробелы в контенте", report.content_gaps),
          section("Тренды", report.trend_ideas), section("Лучшее время", report.best_posting_times),
          section("Рекомендации", report.recommendations)]
    (config.REPORTS_DIR / f"{today}-analytics.md").write_text("\n".join(md), encoding="utf-8")


def latest_insights_text() -> str:
    data = _read(INSIGHTS_FILE, None)
    if not data:
        return "Аналитики пока нет — опирайся на профиль."
    parts = [data["summary"], "Работает: " + "; ".join(data["what_works"]),
             "Вопросы аудитории: " + "; ".join(data["audience_questions"]),
             "Рекомендации: " + "; ".join(data["recommendations"])]
    return "\n".join(parts)
