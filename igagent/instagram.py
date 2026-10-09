"""Клиент Instagram API (Instagram Login, graph.instagram.com).

Нужен профессиональный аккаунт (Creator или Business) и долгоживущий токен
с правами instagram_business_basic, instagram_business_content_publish,
instagram_business_manage_comments, instagram_business_manage_insights.
"""
from __future__ import annotations

import time

import requests

from . import config


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self) -> None:
        ig = config.settings().get("instagram", {})
        self.base = f"{ig.get('base_url', 'https://graph.instagram.com')}/{ig.get('api_version', 'v23.0')}"
        self.user_id = config.env("IG_USER_ID")
        self.token = config.env("IG_ACCESS_TOKEN")

    # --- низкоуровневые запросы ---------------------------------------------
    def _request(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        resp = requests.request(method, url, params=params if method == "GET" else None,
                                data=params if method != "GET" else None, timeout=60)
        payload = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in payload:
            raise InstagramError(f"{method} {path}: {payload.get('error', resp.text)}")
        return payload

    def get(self, path: str, **params) -> dict:
        return self._request("GET", path, **params)

    def post(self, path: str, **params) -> dict:
        return self._request("POST", path, **params)

    def paginate(self, path: str, limit: int = 200, **params) -> list[dict]:
        out: list[dict] = []
        data = self.get(path, **params)
        while True:
            out.extend(data.get("data", []))
            nxt = data.get("paging", {}).get("next")
            if not nxt or len(out) >= limit:
                return out[:limit]
            data = requests.get(nxt, timeout=60).json()

    # --- публикация ----------------------------------------------------------
    def _wait_ready(self, container_id: str, timeout_s: int = 600) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.get(container_id, fields="status_code,status").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                info = self.get(container_id, fields="status")
                raise InstagramError(f"Контейнер {container_id}: {status} {info}")
            time.sleep(10)
        raise InstagramError(f"Контейнер {container_id} не обработался за {timeout_s} с")

    def _container(self, **params) -> str:
        return self.post(f"{self.user_id}/media", **params)["id"]

    def _publish(self, container_id: str) -> str:
        self._wait_ready(container_id)
        return self.post(f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def publish_image(self, url: str, caption: str, alt_text: str = "") -> str:
        params = {"image_url": url, "caption": caption}
        if alt_text:
            params["alt_text"] = alt_text
        return self._publish(self._container(**params))

    def publish_carousel(self, urls: list[str], caption: str) -> str:
        children = []
        for url in urls[:10]:
            is_video = url.lower().endswith((".mp4", ".mov"))
            params = {"is_carousel_item": "true"}
            if is_video:
                params.update(media_type="VIDEO", video_url=url)
            else:
                params["image_url"] = url
            child = self._container(**params)
            self._wait_ready(child)
            children.append(child)
        return self._publish(self._container(media_type="CAROUSEL", children=",".join(children), caption=caption))

    def publish_reel(self, video_url: str, caption: str, cover_url: str | None = None,
                     share_to_feed: bool = True) -> str:
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption,
                  "share_to_feed": str(share_to_feed).lower()}
        if cover_url:
            params["cover_url"] = cover_url
        return self._publish(self._container(**params))

    def publish_story(self, url: str) -> str:
        is_video = url.lower().endswith((".mp4", ".mov"))
        params = {"media_type": "STORIES"}
        params["video_url" if is_video else "image_url"] = url
        return self._publish(self._container(**params))

    def permalink(self, media_id: str) -> str | None:
        return self.get(media_id, fields="permalink").get("permalink")

    # --- аналитика -----------------------------------------------------------
    def account(self) -> dict:
        return self.get(self.user_id, fields="username,followers_count,follows_count,media_count")

    def recent_media(self, limit: int = 100) -> list[dict]:
        fields = "id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink"
        return self.paginate(f"{self.user_id}/media", limit=limit, fields=fields)

    def media_insights(self, media_id: str, product_type: str) -> dict:
        metrics = ["reach", "saved", "shares", "total_interactions", "views"]
        if product_type == "REELS":
            metrics += ["ig_reels_avg_watch_time"]
        try:
            data = self.get(f"{media_id}/insights", metric=",".join(metrics))
        except InstagramError:
            # Часть метрик недоступна для старых постов/сторис — пробуем базовый набор
            data = self.get(f"{media_id}/insights", metric="reach,saved,total_interactions")
        return {m["name"]: (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value"))
                for m in data.get("data", [])}

    def audience_demographics(self) -> dict:
        out = {}
        for breakdown in ("age", "gender", "city"):
            try:
                data = self.get(f"{self.user_id}/insights", metric="follower_demographics",
                                period="lifetime", metric_type="total_value", breakdown=breakdown)
                results = data["data"][0]["total_value"]["breakdowns"][0]["results"]
                out[breakdown] = {r["dimension_values"][0]: r["value"] for r in results}
            except (InstagramError, KeyError, IndexError):
                continue
        return out

    # --- комментарии ---------------------------------------------------------
    def comments(self, media_id: str) -> list[dict]:
        return self.paginate(f"{media_id}/comments", limit=200,
                             fields="id,text,username,timestamp,replies{id,username,text}")

    def reply(self, comment_id: str, message: str) -> str:
        return self.post(f"{comment_id}/replies", message=message)["id"]

    # --- токен ---------------------------------------------------------------
    def refresh_token(self) -> dict:
        """Продлевает долгоживущий токен ещё на 60 дней (токен должен быть старше 24 часов)."""
        resp = requests.get("https://graph.instagram.com/refresh_access_token",
                            params={"grant_type": "ig_refresh_token", "access_token": self.token}, timeout=60)
        payload = resp.json()
        if "access_token" not in payload:
            raise InstagramError(f"Не удалось обновить токен: {payload}")
        return payload
