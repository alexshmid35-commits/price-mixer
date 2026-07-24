"""Shared low-level features used by category matching plugins."""

from __future__ import annotations

import re


def normalize_feature_code(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def bounded_score(value, *, ceiling=0.999):
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return round(min(float(ceiling), max(0.0, score)), 3)


def contains_meaningful_code(shorter, longer, *, min_length=5):
    short = normalize_feature_code(shorter)
    long = normalize_feature_code(longer)
    return len(short) >= int(min_length) and short in long
