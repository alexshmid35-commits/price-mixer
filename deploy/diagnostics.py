"""CLI for creating privacy-safe Price Mixer diagnostic bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from price_mixer.services.diagnostic_bundle import (  # noqa: E402
    create_diagnostic_bundle,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Create a Price Mixer diagnostic ZIP without state or secrets"
    )
    parser.add_argument("destination")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        snapshot = create_diagnostic_bundle(args.root, args.destination)
        result = {
            "status": "ok",
            "destination": str(Path(args.destination).resolve()),
            "schema_version": snapshot["schema_version"],
        }
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        result = {
            "status": "error",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
