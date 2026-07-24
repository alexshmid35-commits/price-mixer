"""Create one verified production backup for the systemd timer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from price_mixer.logging_config import configure_price_mixer_logging  # noqa: E402
from price_mixer.services.backup_schedule import (  # noqa: E402
    create_scheduled_backup,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Create one verified Price Mixer scheduled backup"
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument(
        "--destination-root",
        default=os.getenv(
            "PRICE_MIXER_BACKUP_DIR",
            "/srv/price-mixer-backups",
        ),
    )
    parser.add_argument(
        "--keep-daily",
        type=int,
        default=int(os.getenv("PRICE_MIXER_BACKUP_KEEP_DAILY", "7")),
    )
    parser.add_argument(
        "--keep-weekly",
        type=int,
        default=int(os.getenv("PRICE_MIXER_BACKUP_KEEP_WEEKLY", "4")),
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    configure_price_mixer_logging()
    try:
        result = create_scheduled_backup(
            args.root,
            args.destination_root,
            include_secrets=False,
            keep_daily=args.keep_daily,
            keep_weekly=args.keep_weekly,
        )
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        result = {
            "status": "error",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
