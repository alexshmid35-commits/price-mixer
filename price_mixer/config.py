"""Package-level access to the application configuration.

The project still keeps the canonical config module at the repository root
while the refactor is in progress. Importing through ``price_mixer.config``
lets new package modules avoid reaching outside the package directly.
"""

from config import (
    APP_SETTINGS_PATH,
    ONLINER_API_SETTINGS_PATH,
    ONLINER_DB_PATH,
    PROJECT_ROOT,
    Config,
    cfg,
)

__all__ = [
    "APP_SETTINGS_PATH",
    "ONLINER_API_SETTINGS_PATH",
    "ONLINER_DB_PATH",
    "PROJECT_ROOT",
    "Config",
    "cfg",
]
