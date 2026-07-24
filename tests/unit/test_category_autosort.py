"""Unit tests for category autosort helpers."""

import json
import threading

import pandas as pd

from price_mixer.services import category_autosort as svc


class FakeResponse:
    def __init__(self, ok=True, status_code=200, payload=None):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def response_payload(category, confidence=0.8, reason="ai"):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "category": category,
                        "confidence": confidence,
                        "reason": reason,
                    })
                }
            }
        ]
    }


def test_predict_openai_category_requires_api_key_and_input():
    assert svc.predict_openai_category("Mouse", ["Мышь"], api_key="") == ("", 0.0, "no_api_key")
    assert svc.predict_openai_category("", ["Мышь"], api_key="key") == ("", 0.0, "bad_input")
    assert svc.predict_openai_category("Mouse", [], api_key="key") == ("", 0.0, "bad_input")


def test_predict_openai_category_returns_cached_value_without_http_call():
    key = svc.build_category_cache_key("Mouse", ["Мышь"])
    cache = {key: {"category": "Мышь", "confidence": 0.91, "reason": "cached"}}

    result = svc.predict_openai_category(
        "Mouse",
        ["Мышь"],
        api_key="key",
        cache=cache,
        cache_lock=threading.Lock(),
        requests_post=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call http")),
    )

    assert result == ("Мышь", 0.91, "cached")


def test_predict_openai_category_posts_json_and_caches_success():
    calls = []
    cache = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(payload=response_payload("Клавиатура", confidence=1.2, reason="certain"))

    result = svc.predict_openai_category(
        "Logitech Keyboard",
        ["Мышь", "Клавиатура"],
        local_hint="keyboard",
        api_key="secret",
        model="test-model",
        timeout_sec=3,
        cache=cache,
        requests_post=fake_post,
    )

    assert result == ("Клавиатура", 1.0, "certain")
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["json"]["model"] == "test-model"
    assert calls[0]["timeout"] == 3
    assert cache


def test_predict_openai_category_rejects_category_out_of_allowed():
    result = svc.predict_openai_category(
        "Logitech Keyboard",
        ["Мышь"],
        api_key="key",
        requests_post=lambda *args, **kwargs: FakeResponse(payload=response_payload("Клавиатура")),
    )

    assert result == ("", 0.0, "category_out_of_allowed")


def test_predict_openai_category_reports_http_status():
    result = svc.predict_openai_category(
        "Mouse",
        ["Мышь"],
        api_key="key",
        requests_post=lambda *args, **kwargs: FakeResponse(ok=False, status_code=429),
    )

    assert result == ("", 0.0, "http_429")


def test_build_autosort_preview_payload_uses_ai_suggestion():
    df = pd.DataFrame([
        {"Название": "Logitech Keyboard K120", "Поставщик": "A", "Категория": "Мышь", "OnlinerID": "11"},
        {"Название": "A4Tech Keyboard", "Поставщик": "B", "Категория": "Клавиатура", "OnlinerID": ""},
        {"Название": "Gembird Keyboard", "Поставщик": "C", "Категория": "Клавиатура", "OnlinerID": ""},
    ])

    def predict_category(name, categories, local_hint=""):
        assert "Клавиатура" in categories
        assert "current_category=Мышь" in local_hint
        return "Клавиатура", 0.92, "test"

    payload = svc.build_autosort_preview_payload(
        df,
        {"categories": ["Мышь"], "min_confidence": 0.8},
        overrides={},
        openai_api_key="key",
        max_items=10,
        max_workers=1,
        predict_category=predict_category,
        name_tokens=lambda value: str(value).lower().split(),
        row_category=lambda row, overrides=None: str(row.get("Категория", "")),
        build_item_category_key=lambda row: str(row.get("Название", "")).lower(),
        build_item_category_keys=lambda row: [str(row.get("Название", "")).lower()],
        normalize_onliner_id=lambda value: str(value or "").strip(),
        category_sort_key=lambda value: str(value or ""),
    )

    assert payload["checked"] == 1
    assert payload["ai_checked"] == 1
    assert payload["ai_suggested"] == 1
    assert payload["items"][0]["target_category"] == "Клавиатура"
    assert payload["items"][0]["affected_rows"] == 1


def test_apply_autosort_items_updates_rows_and_overrides():
    df = pd.DataFrame([
        {"Название": "Logitech Keyboard K120", "Категория": "Мышь"},
        {"Название": "Other", "Категория": "Мышь"},
    ])
    overrides = {}

    result, updated_df, updated_overrides = svc.apply_autosort_items(
        df,
        [{"item_key": "logitech keyboard k120", "target_category": "Клавиатура"}],
        overrides=overrides,
        build_item_category_keys=lambda row: [str(row.get("Название", "")).lower()],
        row_category=lambda row, overrides=None: str(row.get("Категория", "")),
    )

    assert result == {"status": "ok", "updated_keys": 1, "updated_rows": 1}
    assert updated_df.loc[0, "Категория"] == "Клавиатура"
    assert updated_df.loc[1, "Категория"] == "Мышь"
    assert updated_overrides["logitech keyboard k120"] == "Клавиатура"
