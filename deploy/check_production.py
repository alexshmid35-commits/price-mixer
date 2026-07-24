"""Fail-fast production environment check without printing secrets."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from price_mixer.services.production_config import (  # noqa: E402
    validate_production_environment,
)
from price_mixer.services.preflight import check_runtime_readiness  # noqa: E402


def main():
    errors = validate_production_environment(os.environ)
    if not errors:
        errors.extend(check_runtime_readiness(os.environ))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Production environment and runtime preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
