"""Settings and auto-refresh API routes."""

from __future__ import annotations

import time
from typing import Callable

from flask import Blueprint, jsonify, request

from price_mixer.settings import (
    AUTO_REFRESH_ALLOWED_HOURS,
    _deep_merge_dict,
    load_app_settings,
    load_auto_refresh_settings,
    save_auto_refresh_settings,
)


def _redact_app_settings(data: dict) -> dict:
    b2b = data.get("onliner_b2b")
    if isinstance(b2b, dict) and str(b2b.get("client_secret") or "").strip():
        b2b["client_secret"] = "••••••••"

    sources = data.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "tradex"):
            src = sources.get(key)
            if isinstance(src, dict) and str(src.get("file_url") or "").strip():
                src["file_url"] = "••••••••"
        ntech = sources.get("ntech")
        if isinstance(ntech, dict) and str(ntech.get("password") or "").strip():
            ntech["password"] = "••••••••"
    return data


def _preserve_redacted_secrets(payload: dict, current: dict) -> dict:
    b2b = payload.get("onliner_b2b")
    if isinstance(b2b, dict):
        if not str(b2b.get("client_secret") or "").strip() or b2b.get("client_secret") == "••••••••":
            b2b["client_secret"] = current.get("onliner_b2b", {}).get("client_secret", "")

    sources = payload.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "tradex"):
            src = sources.get(key)
            if isinstance(src, dict):
                if not str(src.get("file_url") or "").strip() or src.get("file_url") == "••••••••":
                    src["file_url"] = current.get("api_sources", {}).get(key, {}).get("file_url", "")
        ntech = sources.get("ntech")
        if isinstance(ntech, dict):
            if not str(ntech.get("password") or "").strip() or ntech.get("password") == "••••••••":
                ntech["password"] = current.get("api_sources", {}).get("ntech", {}).get("password", "")
    return payload


def create_settings_bp(
    *,
    get_active_session_dir: Callable[[], str | None],
    get_last_active_session_dir: Callable[[], str | None],
    start_market_refresh: Callable[[str | None, list], dict],
    save_app_settings: Callable[[dict], dict],
) -> Blueprint:
    bp = Blueprint("settings_api", __name__)

    @bp.route("/api/auto-refresh-settings")
    def api_auto_refresh_settings():
        settings = load_auto_refresh_settings()
        now = int(time.time())
        interval_hours = int(settings.get("interval_hours", 12) or 12)
        if interval_hours not in AUTO_REFRESH_ALLOWED_HOURS:
            interval_hours = 12
        last_run_ts = int(settings.get("last_run_ts", 0) or 0)
        next_run_ts = 0
        if settings.get("enabled"):
            next_run_ts = (last_run_ts + interval_hours * 3600) if last_run_ts > 0 else now
        next_in_sec = max(0, next_run_ts - now) if next_run_ts else 0
        return jsonify({
            "enabled": bool(settings.get("enabled")),
            "interval_hours": interval_hours,
            "last_run_ts": last_run_ts,
            "last_started_ts": int(settings.get("last_started_ts", 0) or 0),
            "last_status": str(settings.get("last_status", "idle")),
            "last_count": int(settings.get("last_count", 0) or 0),
            "last_message": str(settings.get("last_message", "")),
            "next_run_ts": int(next_run_ts or 0),
            "next_in_sec": int(next_in_sec or 0),
        })

    @bp.route("/api/auto-refresh-settings", methods=["POST"])
    def api_auto_refresh_settings_update():
        payload = request.get_json(silent=True) or {}
        current = load_auto_refresh_settings()
        was_enabled = bool(current.get("enabled"))
        if "enabled" in payload:
            current["enabled"] = bool(payload.get("enabled"))
        if "interval_hours" in payload:
            try:
                interval = int(payload.get("interval_hours"))
            except Exception:
                interval = current.get("interval_hours", 12)
            if interval in AUTO_REFRESH_ALLOWED_HOURS:
                current["interval_hours"] = interval
        if current.get("enabled") and int(current.get("last_run_ts", 0) or 0) <= 0:
            current["last_run_ts"] = 0
            current["last_message"] = "Автообновление включено. Ближайший запуск — в ближайшие секунды."
        elif not current.get("enabled"):
            current["last_message"] = "Автообновление выключено."
        save_auto_refresh_settings(current)

        if current.get("enabled") and not was_enabled:
            sdir = get_active_session_dir() or get_last_active_session_dir()
            started = start_market_refresh(sdir, [])
            latest = load_auto_refresh_settings()
            if started.get("status") == "started":
                latest["last_status"] = "running"
                latest["last_started_ts"] = int(time.time())
                latest["last_message"] = "Автообновление включено. Мгновенный запуск по всем категориям."
            elif started.get("status") == "already_running":
                latest["last_status"] = "running"
                latest["last_message"] = "Автообновление включено. Уже идет текущее обновление."
            else:
                latest["last_status"] = "error"
                latest["last_message"] = "Автообновление включено, но старт не выполнен: " + str(started.get("message", "нет активной сессии"))
            save_auto_refresh_settings(latest)

        return jsonify({"status": "ok"})

    @bp.route("/api/app-settings")
    def api_app_settings():
        return jsonify({"status": "ok", "settings": _redact_app_settings(load_app_settings())})

    @bp.route("/api/app-settings", methods=["POST"])
    def api_app_settings_update():
        payload = request.get_json(silent=True) or {}
        current = load_app_settings()
        payload = _preserve_redacted_secrets(payload if isinstance(payload, dict) else {}, current)
        merged = _deep_merge_dict(current, payload)
        saved = save_app_settings(merged)
        return jsonify({"status": "ok", "settings": saved})

    return bp
