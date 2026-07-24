"""CLI for verified backups and restore dry-runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from price_mixer.services.backup_restore import (  # noqa: E402
    build_restore_plan,
    create_backup,
    verify_backup,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Price Mixer verified backup utility"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("destination")
    create.add_argument(
        "--root",
        default=str(PROJECT_ROOT),
    )
    create.add_argument(
        "--include-secrets",
        action="store_true",
        help="Explicitly include local .env/service-account files.",
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("backup")

    restore = subparsers.add_parser("restore-plan")
    restore.add_argument("backup")
    restore.add_argument("target")
    restore.add_argument("--include-secrets", action="store_true")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(
                args.root,
                args.destination,
                include_secrets=args.include_secrets,
            )
            result = {
                "status": "ok",
                "destination": str(Path(args.destination).resolve()),
                "files": len(manifest["files"]),
                "includes_secrets": manifest["includes_secrets"],
            }
        elif args.command == "verify":
            result = verify_backup(args.backup)
        else:
            result = build_restore_plan(
                args.backup,
                args.target,
                include_secrets=args.include_secrets,
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
