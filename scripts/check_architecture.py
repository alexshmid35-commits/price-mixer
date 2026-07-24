#!/usr/bin/env python3
"""Fail fast when completed module boundaries regress."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fail(message):
    raise SystemExit(f"architecture check failed: {message}")


def main():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    if re.search(r"^@app\.(?:route|get|post|put|patch|delete)\b", app_source, re.MULTILINE):
        _fail("new HTTP routes must live in price_mixer/api blueprints")

    facade = ROOT / "price_mixer" / "services" / "review_candidates.py"
    if len(facade.read_text(encoding="utf-8").splitlines()) > 50:
        _fail("review_candidates.py must remain a compatibility facade")

    matching_dir = ROOT / "price_mixer" / "services" / "review_matching"
    category_modules = [
        path for path in matching_dir.glob("*.py") if path.name not in {"__init__.py", "engine.py", "features.py"}
    ]
    if len(category_modules) < 12:
        _fail("all review categories must remain isolated plugins")
    oversized = [path.name for path in category_modules if len(path.read_text(encoding="utf-8").splitlines()) > 500]
    if oversized:
        _fail(f"category plugins exceed 500 lines: {', '.join(oversized)}")

    for path in (ROOT / "price_mixer").rglob("*.py"):
        if "workers" in path.relative_to(ROOT / "price_mixer").parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {item.name for item in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            if "app" in names and path.name != "__init__.py":
                _fail(f"package module imports app.py: {path.relative_to(ROOT)}")

    print(f"architecture ok: blueprints only, matching facade thin, {len(category_modules)} category plugins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
