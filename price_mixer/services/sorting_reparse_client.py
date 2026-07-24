"""Client helpers for the auxiliary Onliner sorting reparse service."""

from __future__ import annotations

from collections.abc import Mapping

import requests


def parser_error_message(exc, *, label="Парсер на :5055") -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout | requests.exceptions.ReadTimeout | requests.exceptions.Timeout):
        return f"{label} не ответил за отведённое время. Попробуй повторить позже."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"{label} не запущен. Запусти локальный onliner-parser и повтори допарсинг."
    return f"{label} недоступен: {exc}"


def response_json_payload(response, *, label="Парсер на :5055") -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        text = str(getattr(response, "text", "") or "").strip()
        snippet = text[:240] if text else "пустой ответ"
        status_code = int(getattr(response, "status_code", 0) or 0)
        content_type = ""
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping):
            content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").strip()
        detail = f"HTTP {status_code}"
        if content_type:
            detail += f", {content_type}"
        raise ValueError(f"{label} вернул не JSON ({detail}): {snippet}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{label} вернул неожиданный формат ответа.")
    return payload
