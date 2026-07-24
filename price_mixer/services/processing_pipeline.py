"""Supplier upload processing pipeline helpers."""

from __future__ import annotations

from pathlib import Path
import shutil
import time
from typing import Any, Callable

import pandas as pd

from price_mixer.logging_config import get_logger


LOGGER = get_logger("price_mixer.processing")


def _manual_binding_supplier_names(manual):
    if not isinstance(manual, dict):
        return []
    raw_suppliers = manual.get("suppliers", None)
    if raw_suppliers is None:
        raw_suppliers = manual.get("supplier", "")
    if isinstance(raw_suppliers, str):
        items = [part.strip() for part in raw_suppliers.replace(";", ",").split(",")]
    elif isinstance(raw_suppliers, (list, tuple, set)):
        items = list(raw_suppliers)
    else:
        items = []
    return [str(item or "").strip().upper() for item in items if str(item or "").strip()]


def _manual_binding_applies_to_supplier(manual, supplier_name):
    suppliers = set(_manual_binding_supplier_names(manual))
    if not suppliers:
        return True
    supplier = str(supplier_name or "").strip().upper()
    return supplier in suppliers


def infer_supplier_from_filename(filename, app_settings=None, load_app_settings: Callable[[], dict] | None = None):
    name = str(filename or "").strip().lower()
    if not name:
        return ""
    compact_name = name.replace("-", "").replace("_", "").replace(" ", "")
    settings = app_settings if app_settings is not None else (load_app_settings() if callable(load_app_settings) else {})
    rules = (((settings or {}).get("suppliers") or {}).get("filename_rules") or [])
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("pattern", "") or "").strip().lower()
        supplier = str(rule.get("supplier", "") or "").strip()
        if pattern and supplier and pattern in name:
            supplier_compact = supplier.lower().replace("-", "").replace("_", "").replace(" ", "")
            if supplier_compact == "ntech":
                return "N-Tech"
            if supplier_compact == "ivenzakaz":
                return "IVEN_zakaz"
            if supplier_compact == "iven":
                return "IVEN"
            return supplier
    if "ntech" in name or "n-tech" in name or "n_tech" in name:
        return "N-Tech"
    if "ivenzakaz" in compact_name:
        return "IVEN_zakaz"
    if "iven" in name:
        return "IVEN"
    if "tradex" in name:
        return "Tradex"
    if "1030z" in name:
        return "BN-1030Z"
    if "1030" in name:
        return "BN-1030"
    if "1374" in name:
        return "BN-1374"
    if "price_bn" in name:
        return "TGPC"
    return ""


def process_supplier_files(
    file_entries,
    *,
    session_id=None,
    session_dir=None,
    create_session_dir: Callable[[], tuple[str, Path]],
    load_app_settings: Callable[[], dict],
    parse_generic_excel: Callable[[Path, str], pd.DataFrame],
    consolidate_simple: Callable[[pd.DataFrame], pd.DataFrame],
    normalize_consolidated_columns: Callable[[pd.DataFrame], pd.DataFrame],
    ensure_category_column: Callable[[pd.DataFrame], pd.DataFrame],
    apply_saved_markups_to_df: Callable[[pd.DataFrame], pd.DataFrame],
    load_manual_id_bindings: Callable[[], dict],
    expand_iven_pc_manual_aliases: Callable[[dict], tuple[dict, bool]],
    save_manual_id_bindings: Callable[[dict], None],
    load_id_cache: Callable[[], dict],
    sanitize_id_cache: Callable[[dict], tuple[dict, bool]],
    save_id_cache: Callable[[dict], None],
    build_id_fanout_map: Callable[[dict], Any],
    normalize_name_key: Callable[[Any], str],
    normalize_onliner_id: Callable[[Any], str],
    is_iven_pc_name: Callable[[Any], bool],
    iven_pc_onliner_id_mismatch_known: Callable[[Any, Any], bool],
    allow_manual_binding_for_supplier: Callable[[str, Any, Any], bool],
    lookup_manual_binding_for_name: Callable[[dict, Any], dict | None],
    id_cache_keys_for_iven_pc_name: Callable[[Any], list[str]],
    get_id_cache_key_for_name: Callable[[Any], str],
    is_trusted_cached_id: Callable[..., bool],
    iven_pc_onliner_id_matches_name: Callable[[Any, Any], bool],
    clear_duplicate_onliner_ids_for_suppliers: Callable[[pd.DataFrame, list[str]], int],
    write_consolidated_df: Callable[[Path, pd.DataFrame], None],
    write_consolidated_json: Callable[[pd.DataFrame, Path], None],
    save_session_supplier_diff: Callable[[Path, dict], None],
    count_rows_without_onliner_id: Callable[[pd.DataFrame], int],
    count_rows_with_duplicate_onliner_id: Callable[[pd.DataFrame], int],
    coerce_bool: Callable[..., bool],
    maybe_cleanup_old_uploads: Callable[..., Any],
    last_active_session_dir=None,
):
    started_perf = time.monotonic()

    def log_step(step, **extra):
        parts = [f"[process_supplier_files] {step}", f"elapsed={time.monotonic() - started_perf:.2f}s"]
        parts.extend(f"{key}={value}" for key, value in extra.items())
        LOGGER.info(" ".join(parts))

    app_settings = load_app_settings()
    if session_id and session_dir:
        session_id = str(session_id)
        session_dir = Path(session_dir)
        session_dir.mkdir(exist_ok=True)
    else:
        session_id, session_dir = create_session_dir()
    all_frames = []
    supplier_names = set()
    parse_errors = []
    log_step("start", files=len(file_entries or []))

    for entry in file_entries:
        filepath = Path(entry.get("filepath", ""))
        if not filepath.exists():
            continue
        display_name = str(entry.get("display_name", filepath.name) or filepath.name)
        supplier_name = (
            str(entry.get("supplier_name", "") or "").strip()
            or infer_supplier_from_filename(display_name, app_settings)
            or "Unknown"
        )
        try:
            df = parse_generic_excel(filepath, supplier_name)
            if df.empty:
                parse_errors.append(
                    f"{display_name}: не найдено товарных строк с названием и ценой"
                )
                LOGGER.warning(
                    "supplier file has no product rows file=%s",
                    display_name,
                )
                continue
            all_frames.append(df)
            supplier_names.add(supplier_name)
            LOGGER.info(
                "supplier file parsed file=%s rows=%s supplier=%s",
                display_name,
                len(df),
                supplier_name,
            )
        except Exception as exc:
            parse_errors.append(f"{display_name}: {str(exc)[:120]}")
            LOGGER.exception("supplier file parsing failed file=%s", display_name)

    if parse_errors:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError("Не обработаны прайсы поставщиков: " + " | ".join(parse_errors[:5]))

    if not all_frames:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError("Не удалось обработать файлы")

    all_data = pd.concat(all_frames, ignore_index=True)
    LOGGER.info(
        "supplier files combined rows=%s columns=%s",
        len(all_data),
        len(all_data.columns),
    )
    if "onliner_id" in all_data.columns:
        LOGGER.info(
            "supplier rows with Onliner ID count=%s",
            int(all_data["onliner_id"].notna().sum()),
        )
    log_step("parsed", source_rows=len(all_data), suppliers=len(supplier_names))

    consolidated_df = consolidate_simple(all_data)
    log_step("consolidated", rows=len(consolidated_df))
    consolidated_df = normalize_consolidated_columns(consolidated_df)
    log_step("columns_normalized", rows=len(consolidated_df), cols=len(consolidated_df.columns))
    consolidated_df = ensure_category_column(consolidated_df)
    log_step("categories_applied", rows=len(consolidated_df))

    ids_before_overlays = consolidated_df.get(
        "OnlinerID",
        pd.Series("", index=consolidated_df.index, dtype="object"),
    ).map(normalize_onliner_id)

    manual_bindings = load_manual_id_bindings()
    log_step("manual_bindings_loaded", records=len(manual_bindings))
    manual_bindings, manual_aliases_changed = expand_iven_pc_manual_aliases(manual_bindings)
    log_step("manual_aliases_expanded", changed=manual_aliases_changed)
    if manual_aliases_changed:
        save_manual_id_bindings(manual_bindings)
    id_cache, id_cache_changed = sanitize_id_cache(load_id_cache())
    log_step("id_cache_loaded", records=len(id_cache), changed=id_cache_changed)
    if id_cache_changed:
        save_id_cache(id_cache)
    id_fanout = build_id_fanout_map(id_cache)
    log_step("id_state_loaded", manual_bindings=len(manual_bindings), id_cache=len(id_cache))
    if "Ссылка" not in consolidated_df.columns:
        consolidated_df["Ссылка"] = ""
    for i, row in consolidated_df.iterrows():
        name = row.get("Название", "")
        supplier_name = str(row.get("Поставщик", "") or "").strip().upper()
        is_iven_supplier = supplier_name in {"IVEN"}
        is_ntech_supplier = supplier_name in {"N-TECH", "NTECH"}
        if is_iven_supplier and is_iven_pc_name(name):
            current_id = normalize_onliner_id(row.get("OnlinerID", ""))
            if current_id and iven_pc_onliner_id_mismatch_known(name, current_id):
                consolidated_df.at[i, "OnlinerID"] = ""
                consolidated_df.at[i, "Ссылка"] = ""

        # manual_bindings are user decisions and must override supplier-provided IDs.
        allow_manual_binding = allow_manual_binding_for_supplier(supplier_name, name, row.get("Категория", ""))
        if allow_manual_binding:
            try:
                manual = lookup_manual_binding_for_name(manual_bindings, name, supplier_name)
            except TypeError:
                manual = lookup_manual_binding_for_name(manual_bindings, name)
            if isinstance(manual, dict):
                if not _manual_binding_applies_to_supplier(manual, supplier_name):
                    manual = None
            if isinstance(manual, dict):
                if bool(manual.get("blocked", False)):
                    consolidated_df.at[i, "OnlinerID"] = ""
                    consolidated_df.at[i, "Ссылка"] = ""
                    continue
                mid = normalize_onliner_id(manual.get("id", ""))
                if mid:
                    consolidated_df.at[i, "OnlinerID"] = mid
                    murl = str(manual.get("url", "")).strip()
                    if murl:
                        consolidated_df.at[i, "Ссылка"] = murl
                    continue

        allow_id_cache = (not is_iven_supplier and not is_ntech_supplier) or (
            is_iven_supplier and is_iven_pc_name(name)
        )
        if allow_id_cache:
            oid = row.get("OnlinerID")
            if not oid or str(oid).strip() == "" or str(oid) == "nan":
                cache_keys = id_cache_keys_for_iven_pc_name(name) if is_iven_supplier else [get_id_cache_key_for_name(name)]
                for cache_key in cache_keys:
                    if not cache_key or cache_key not in id_cache:
                        continue
                    cached = id_cache[cache_key]
                    if is_trusted_cached_id(cache_key, cached, id_fanout=id_fanout):
                        cached_id = normalize_onliner_id(cached.get("id", ""))
                        if cached_id:
                            if is_iven_supplier and not iven_pc_onliner_id_matches_name(name, cached_id):
                                continue
                            consolidated_df.at[i, "OnlinerID"] = cached_id
                            break

    duplicate_ids_cleared = clear_duplicate_onliner_ids_for_suppliers(consolidated_df, ["IVEN"])
    ids_after_overlays = consolidated_df["OnlinerID"].map(normalize_onliner_id)
    changed_id_mask = ids_after_overlays.ne(ids_before_overlays)
    changed_id_count = int(changed_id_mask.sum())
    log_step(
        "id_overlays_applied",
        changed_ids=changed_id_count,
        duplicate_ids_cleared=duplicate_ids_cleared,
    )

    if changed_id_count:
        changed_rows = ensure_category_column(consolidated_df.loc[changed_id_mask].copy())
        if "Категория" in changed_rows.columns:
            consolidated_df.loc[changed_id_mask, "Категория"] = changed_rows["Категория"]
    log_step("changed_id_categories_refreshed", rows=changed_id_count)

    consolidated_df = apply_saved_markups_to_df(consolidated_df)
    log_step("markups_applied", rows=len(consolidated_df))

    output_path = session_dir / "consolidated_price.xlsx"
    write_consolidated_json(consolidated_df, session_dir / "consolidated.json")
    log_step("json_written", rows=len(consolidated_df))
    output_path.unlink(missing_ok=True)
    log_step("xlsx_deferred", path=output_path.name)

    snapshot_diff = {}
    save_session_supplier_diff(session_dir, {})

    stats = {
        "total": len(all_data),
        "suppliers": len(supplier_names),
        "consolidated": len(consolidated_df),
        "matched": int(all_data["onliner_id"].notna().sum()) if "onliner_id" in all_data.columns else 0,
        "without_id": count_rows_without_onliner_id(consolidated_df),
        "duplicate_id_rows": count_rows_with_duplicate_onliner_id(consolidated_df),
        "show_checks_block": coerce_bool((((app_settings or {}).get("ui") or {}).get("show_checks_block", True)), default=True),
        "snapshot_diff": snapshot_diff,
    }

    try:
        maybe_cleanup_old_uploads(exclude_dirs=[session_dir, last_active_session_dir], min_interval_sec=60)
    except Exception:
        pass
    log_step("done", rows=len(consolidated_df), without_id=stats["without_id"])

    return {
        "session_id": session_id,
        "session_dir": session_dir,
        "output_path": output_path,
        "stats": stats,
    }
