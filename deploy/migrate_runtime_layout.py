"""Plan or copy the legacy runtime layout into separated directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from price_mixer.runtime_paths import RuntimePaths  # noqa: E402
from price_mixer.services.runtime_migration import (  # noqa: E402
    build_runtime_migration_plan,
    copy_runtime_layout,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Non-destructive Price Mixer runtime layout migration"
    )
    parser.add_argument("command", choices=("plan", "copy"))
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--upload-dir", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument(
        "--confirm-service-stopped",
        action="store_true",
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    paths = RuntimePaths(
        project_root=root,
        state_dir=Path(args.state_dir).resolve(),
        data_dir=Path(args.data_dir).resolve(),
        cache_dir=Path(args.cache_dir).resolve(),
        uploads_dir=Path(args.upload_dir).resolve(),
        logs_dir=Path(args.log_dir).resolve(),
    )
    try:
        if args.command == "plan":
            result = build_runtime_migration_plan(root, paths)
        else:
            result = copy_runtime_layout(
                root,
                paths,
                service_stopped=args.confirm_service_stopped,
            )
    except (FileExistsError, OSError, RuntimeError, TypeError, ValueError) as exc:
        result = {
            "status": "error",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
