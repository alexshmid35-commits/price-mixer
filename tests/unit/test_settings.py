"""Unit tests for settings normalization and persistence."""

import json

from price_mixer import settings


def test_load_app_settings_overlays_env_config(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    app_path.write_text(json.dumps({"onliner_b2b": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)
    monkeypatch.setattr(settings.cfg, "onliner_b2b_client_id", "env-client")
    monkeypatch.setattr(settings.cfg, "onliner_b2b_client_secret", "env-secret")
    monkeypatch.setattr(settings.cfg, "google_sheets_tab", "Price")

    loaded = settings.load_app_settings()

    assert loaded["onliner_b2b"]["enabled"] is True
    assert loaded["onliner_b2b"]["client_id"] == "env-client"
    assert loaded["onliner_b2b"]["client_secret"] == "env-secret"
    assert loaded["export"]["google_sheets_tab"] == "Price"


def test_load_app_settings_keeps_saved_google_tab_over_env_default(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    app_path.write_text(
        json.dumps({"export": {"google_sheets_tab": "Прайс N-Tech"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)
    monkeypatch.setattr(settings.cfg, "google_sheets_tab", "Price")

    loaded = settings.load_app_settings()

    assert loaded["export"]["google_sheets_tab"] == "Прайс N-Tech"


def test_load_app_settings_uses_safe_export_defaults(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)

    loaded = settings.load_app_settings()

    assert loaded["export"]["include_without_id"] is False
    assert loaded["export"]["keep_lowest_price_per_onliner_id"] is True
    assert loaded["export"]["exclude_category_prefixes"] == ["Требует сортировки"]
    assert loaded["export"]["exclude_name_contains"] == ["патрон", "milwaukee", "p.i.t"]


def test_load_app_settings_does_not_ship_credential_urls(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)

    loaded = settings.load_app_settings()

    assert loaded["api_sources"]["iven_zakaz"]["file_url"] == ""


def test_save_app_settings_strips_secrets_and_syncs_api_settings(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    api_path = tmp_path / "onliner_api_settings.json"
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)
    monkeypatch.setattr(settings, "ONLINER_API_SETTINGS_FILE", api_path)
    settings.ONLINER_API_SETTINGS_CACHE["data"] = None

    saved = settings.save_app_settings({
        "onliner_b2b": {"client_id": "secret-id", "client_secret": "secret-value"},
        "export": {
            "google_sheets_spreadsheet_url_or_id": "sheet-id",
            "google_sheets_service_account_json": "service.json",
            "google_sheets_tab": "Tab",
        },
        "api_sources": {
            "iven": {"file_url": "https://example.test/iven.xlsx"},
            "ntech": {"username": "user", "password": "pass"},
        },
        "cache_api": {"retry_attempts": 99, "max_parallel_workers": 99},
    })

    persisted = json.loads(app_path.read_text(encoding="utf-8"))
    api_persisted = json.loads(api_path.read_text(encoding="utf-8"))

    assert saved["onliner_b2b"]["client_id"] == ""
    assert persisted["onliner_b2b"]["client_secret"] == ""
    assert persisted["export"]["google_sheets_spreadsheet_url_or_id"] == "sheet-id"
    assert persisted["export"]["google_sheets_tab"] == "Tab"
    assert persisted["export"]["google_sheets_service_account_json"] == ""
    assert persisted["api_sources"]["iven"]["file_url"] == ""
    assert persisted["api_sources"]["ntech"]["password"] == ""
    assert api_persisted["retry_attempts"] == 12
    assert api_persisted["max_parallel_workers"] == 24


def test_auto_refresh_settings_normalize_allowed_interval(monkeypatch, tmp_path):
    path = tmp_path / "auto_refresh_settings.json"
    monkeypatch.setattr(settings, "AUTO_REFRESH_SETTINGS_FILE", path)

    saved = settings.save_auto_refresh_settings({"enabled": True, "interval_hours": 99})
    loaded = settings.load_auto_refresh_settings()

    assert saved["interval_hours"] == 12
    assert loaded["enabled"] is True
    assert loaded["interval_hours"] == 12


def test_filename_rules_keep_core_supplier_detection(monkeypatch, tmp_path):
    app_path = tmp_path / "app_settings.json"
    app_path.write_text(
        json.dumps({"suppliers": {"filename_rules": [{"pattern": "custom", "supplier": "Custom"}]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", app_path)

    loaded = settings.load_app_settings()
    rules = {item["pattern"]: item["supplier"] for item in loaded["suppliers"]["filename_rules"]}

    assert rules["ntech"] == "N-Tech"
    assert rules["iven_zakaz"] == "IVEN_zakaz"
    assert rules["iven"] == "IVEN"
    assert rules["custom"] == "Custom"
