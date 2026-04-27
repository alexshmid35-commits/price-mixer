"""
Price Mixer — Unified Configuration

Reads secrets from environment variables (.env file)
and overlays them on top of app_settings.json values.
Environment variables always take precedence.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.resolve()

# File paths
APP_SETTINGS_PATH = PROJECT_ROOT / "app_settings.json"
ONLINER_API_SETTINGS_PATH = PROJECT_ROOT / "onliner_api_settings.json"
ONLINER_DB_PATH = PROJECT_ROOT / "onliner_products.db"


def _env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, "")
    if val.lower() in ("1", "true", "yes", "on"):
        return True
    if val.lower() in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, default))
    except ValueError:
        return default


class Config:
    """Centralized configuration."""

    # Paths
    project_root = PROJECT_ROOT
    uploads_dir = PROJECT_ROOT / "uploads"

    # Google Sheets
    google_sheets_sa_json = _env_str(
        "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "ai2025-462421-df1d36f12313.json"
    )
    google_sheets_spreadsheet_id = _env_str(
        "GOOGLE_SHEETS_SPREADSHEET_ID", "11zEGNWLqcOxhlm6SubOlW2xFvjQSrJAJJaUm-ga8iHM"
    )

    # Onliner B2B
    onliner_b2b_client_id = _env_str("ONLINER_B2B_CLIENT_ID", "")
    onliner_b2b_client_secret = _env_str("ONLINER_B2B_CLIENT_SECRET", "")
    onliner_b2b_base_url = _env_str("ONLINER_B2B_BASE_URL", "https://b2bapi.onliner.by")
    onliner_b2b_price_api_base_url = _env_str(
        "ONLINER_B2B_PRICE_API_BASE_URL", "https://price.api.onliner.by"
    )
    onliner_b2b_token_url = _env_str(
        "ONLINER_B2B_TOKEN_URL", "https://b2bapi.onliner.by/oauth/token"
    )

    # N-Tech API
    ntech_username = _env_str("NTECH_USERNAME", "")
    ntech_password = _env_str("NTECH_PASSWORD", "")
    ntech_auth_url = _env_str("NTECH_AUTH_URL", "https://api.nt-d.by/authorization/login")
    ntech_price_url = _env_str("NTECH_PRICE_URL", "https://api.nt-d.by/price/download_buh")

    # IVEN / Tradex direct URLs
    iven_file_url = _env_str("IVEN_FILE_URL", "")
    tradex_file_url = _env_str("TRADEX_FILE_URL", "")

    # Onliner API caching / proxy settings
    onliner_api_allow_direct = _env_bool("ONLINER_API_ALLOW_DIRECT", True)
    onliner_api_retry_attempts = _env_int("ONLINER_API_RETRY_ATTEMPTS", 3)
    onliner_api_backoff_sec = float(os.getenv("ONLINER_API_BACKOFF_SEC", "0.6"))
    onliner_api_proxy_cooldown_sec = _env_int("ONLINER_API_PROXY_COOLDOWN_SEC", 180)
    onliner_api_max_parallel_workers = _env_int("ONLINER_API_MAX_PARALLEL_WORKERS", 10)

    # Admin auth
    admin_username = _env_str("ADMIN_USERNAME", "admin")
    admin_password = _env_str("ADMIN_PASSWORD", "")

    @classmethod
    def load_app_settings(cls) -> dict:

        """Load app_settings.json as a dict."""
        if APP_SETTINGS_PATH.exists():
            with open(APP_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @classmethod
    def load_onliner_api_settings(cls) -> dict:
        """Load onliner_api_settings.json as a dict."""
        if ONLINER_API_SETTINGS_PATH.exists():
            with open(ONLINER_API_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}


# Convenience singleton-like access
cfg = Config()
