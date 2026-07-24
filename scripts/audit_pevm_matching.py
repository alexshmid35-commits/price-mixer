#!/usr/bin/env python3
"""Dry-run audit of N-Tech and IVEN PC matching against the local catalog."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from price_mixer.services.product_normalization import (  # noqa: E402
    normalize_onliner_id,
)


def classify_candidate_scores(top_id, top_score, second_score):
    if not normalize_onliner_id(top_id):
        return "not_found"
    if top_score >= 0.95:
        return "confident"
    if top_score >= 0.92 and (top_score - second_score) >= 0.05:
        return "confident"
    return "manual_review"


def audit_profile(
    dataframe,
    *,
    supplier,
    product_predicate,
    identity_extractor,
    candidate_search,
    catalog_product_lookup,
    normalize_name_key,
    max_items=0,
):
    supplier_token = str(supplier).strip().upper()
    identities = {}
    tasks = []
    existing = []
    for row_index, row in dataframe.iterrows():
        if str(row.get("Поставщик", "") or "").strip().upper() != supplier_token:
            continue
        name = str(row.get("Название", "") or "").strip()
        if not name or not product_predicate(name):
            continue
        identity = str(identity_extractor(name) or "").strip().casefold()
        if identity:
            identities.setdefault(identity, set()).add(
                normalize_name_key(name)
            )
        existing_id = normalize_onliner_id(row.get("OnlinerID", ""))
        if existing_id:
            existing.append((int(row_index), name, identity, existing_id))
            continue
        tasks.append((int(row_index), name, identity))
    if max_items:
        tasks = tasks[:max(0, int(max_items))]

    items = []
    counts = Counter()
    for row_index, name, identity in tasks:
        if identity and len(identities.get(identity, set())) > 1:
            classification = "ambiguous_identity"
            candidates = []
        else:
            candidates = candidate_search(name, limit=24) or []
            top = candidates[0] if candidates else {}
            second = candidates[1] if len(candidates) > 1 else {}
            classification = classify_candidate_scores(
                top.get("id", ""),
                float(top.get("score", 0) or 0),
                float(second.get("score", 0) or 0),
            )
        counts[classification] += 1
        top = candidates[0] if candidates else {}
        second = candidates[1] if len(candidates) > 1 else {}
        items.append({
            "row_idx": row_index,
            "name": name,
            "identity": identity,
            "classification": classification,
            "candidate_count": len(candidates),
            "top_id": normalize_onliner_id(top.get("id", "")),
            "top_name": str(top.get("name", "") or "").strip(),
            "top_score": round(float(top.get("score", 0) or 0), 4),
            "second_score": round(float(second.get("score", 0) or 0), 4),
        })
    validation_counts = Counter()
    validation_mismatches = []
    for row_index, name, identity, onliner_id in existing:
        product = catalog_product_lookup(onliner_id)
        if not isinstance(product, dict):
            classification = "catalog_missing"
            catalog_name = ""
            catalog_identity = ""
        else:
            catalog_name = str(product.get("name", "") or "").strip()
            catalog_identity = str(
                identity_extractor(catalog_name) or ""
            ).strip().casefold()
            classification = (
                "exact_identity"
                if identity and catalog_identity == identity
                else "identity_mismatch"
            )
        validation_counts[classification] += 1
        if classification != "exact_identity" and len(validation_mismatches) < 30:
            validation_mismatches.append({
                "row_idx": row_index,
                "name": name,
                "identity": identity,
                "onliner_id": onliner_id,
                "catalog_name": catalog_name,
                "catalog_identity": catalog_identity,
                "classification": classification,
            })

    return {
        "supplier": supplier,
        "total_without_id": len(tasks),
        "counts": dict(sorted(counts.items())),
        "existing_id_validation": {
            "total": len(existing),
            "counts": dict(sorted(validation_counts.items())),
            "mismatches": validation_mismatches,
        },
        "items": items,
    }


def build_report(session_dir, *, max_items=0):
    import app

    session_path = Path(session_dir).resolve()
    dataframe = app.read_consolidated_json_fast_df(session_path)
    profiles = [
        audit_profile(
            dataframe,
            supplier="N-Tech",
            product_predicate=app._is_tgpc_pc_name,
            identity_extractor=app._extract_tgpc_pc_code,
            candidate_search=app.db_search_tgpc_pc_candidates,
            catalog_product_lookup=app.db_get_product_by_id,
            normalize_name_key=app._normalize_name_key,
            max_items=max_items,
        ),
        audit_profile(
            dataframe,
            supplier="IVEN",
            product_predicate=app._is_iven_pc_name,
            identity_extractor=app._extract_iven_pc_code,
            candidate_search=app.db_search_iven_pc_candidates,
            catalog_product_lookup=app.db_get_product_by_id,
            normalize_name_key=app._normalize_name_key,
            max_items=max_items,
        ),
    ]
    return {
        "schema": "price-mixer-pevm-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_dir": str(session_path),
        "dry_run": True,
        "profiles": profiles,
    }


def _parser():
    parser = argparse.ArgumentParser(
        description="Audit PC ID matching without changing the price",
    )
    parser.add_argument("session_dir")
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--output")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    report = build_report(
        args.session_dir,
        max_items=max(0, int(args.max_items)),
    )
    payload = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "dry_run": True,
        "profiles": [
            {
                "supplier": profile["supplier"],
                "total_without_id": profile["total_without_id"],
                "counts": profile["counts"],
                "existing_id_validation": {
                    "total": profile["existing_id_validation"]["total"],
                    "counts": profile["existing_id_validation"]["counts"],
                },
            }
            for profile in report["profiles"]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
