"""Autofill worker orchestration for TGPC PC and IVEN bridge flows."""

from __future__ import annotations

from functools import wraps
from pathlib import Path
import time

from price_mixer.logging_config import get_logger, log_context, new_job_id
from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.manual_id_store import (
    build_supplier_binding_record,
    supplier_scoped_binding_key,
)

LOGGER = get_logger("price_mixer.jobs.autofill")


def _with_status_job_context(func):
    @wraps(func)
    def _wrapped(*args, **kwargs):
        status = kwargs.get("status")
        if not isinstance(status, dict):
            return func(*args, **kwargs)
        job_id = str(status.get("job_id", "") or "").strip() or new_job_id()
        status["job_id"] = job_id
        with log_context(job_id=job_id):
            return func(*args, **kwargs)

    return _wrapped


def make_pc_autofill_status(label="TGPC ПЭВМ", now_fn=time.time):
    return {
        "job_id": new_job_id(),
        "running": True,
        "total": 0,
        "done": 0,
        "applied": 0,
        "skipped": 0,
        "percent": 0,
        "items": [],
        "started_at": int(now_fn()),
        "finished_at": 0,
        "message": f"Подготовка автоподбора {label}...",
    }


def make_tgpc_pc_status(now_fn=time.time):
    return make_pc_autofill_status("TGPC ПЭВМ", now_fn=now_fn)


def make_iven_bridge_status(prefer_b2b=False, now_fn=time.time):
    return {
        "job_id": new_job_id(),
        "running": True,
        "total": 0,
        "done": 0,
        "applied": 0,
        "skipped": 0,
        "percent": 0,
        "started_at": int(now_fn()),
        "finished_at": 0,
        "message": "Подготовка IVEN-бриджа..." + (" Режим: B2B без кеша." if prefer_b2b else ""),
        "matches": [],
        "no_match": [],
        "report_mode": "iven",
        "report_title": "Отчёт подбора IVEN-бридж",
        "report_subtitle": "Сопоставление N-Tech товаров с базой Onliner ID",
    }


def start_autofill_payload(
    session_dir,
    *,
    cons_exists,
    status,
    lock,
    start_worker,
    status_factory,
    now_fn=time.time,
    stale_after_sec=1800,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    if not cons_exists:
        return {"status": "error", "message": "Нет данных для обработки"}, 400
    with lock:
        if status.get("running"):
            started_at = int(status.get("started_at", 0) or 0)
            is_stale = bool(started_at and (int(now_fn()) - started_at) > int(stale_after_sec))
            if not is_stale:
                return {"status": "already_running"}
            status.update({
                "running": False,
                "finished_at": int(now_fn()),
                "message": "Предыдущий автоподбор завис по таймауту, запускаю заново...",
            })
        status.clear()
        status.update(status_factory())
    start_worker()
    return {"status": "started"}


def status_payload(status, lock, *, include_items=True):
    with lock:
        payload = dict(status)
    if include_items:
        payload["items"] = list(payload.get("items", []) or [])
    return payload


def build_iven_id_index(df, *, normalize_name_key, normalize_id=normalize_onliner_id):
    index = {}
    if df is None or df.empty:
        return index
    skip_suppliers = {"N-TECH", "NTECH", "TGPC"}
    supplier_col = "Поставщик" if "Поставщик" in df.columns else None
    for _, row in df.iterrows():
        oid = normalize_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        if supplier_col:
            supplier = str(row.get(supplier_col, "")).strip().upper()
            if supplier in skip_suppliers:
                continue
        key = normalize_name_key(name)
        if key and key not in index:
            index[key] = {"id": oid, "name": name, "url": str(row.get("Ссылка", "")).strip()}
    return index


def lookup_iven_match(product_name, iven_index, *, calc_name_match, threshold=0.85):
    if not product_name or not iven_index:
        return None
    best_score = 0.0
    best_record = None
    for record in iven_index.values():
        match = calc_name_match(product_name, record["name"])
        score = float(match.get("score", 0.0) or 0.0)
        if score > best_score:
            best_score = score
            best_record = record
    if best_score >= threshold and best_record:
        return {**best_record, "score": round(best_score, 3)}
    return None


@_with_status_job_context
def run_iven_bridge_worker(
    session_dir,
    *,
    ignore_manual_cache=False,
    prefer_b2b=False,
    status,
    lock,
    db_stats,
    read_consolidated_df,
    db_populate_from_df,
    db_find_id_for_name,
    db_find_top_candidates,
    is_tgpc_pc_name,
    normalize_name_key,
    get_id_cache_key_for_name,
    load_manual_id_bindings,
    save_manual_id_bindings,
    load_id_cache,
    save_id_cache,
    append_id_change_journal,
    write_consolidated_df,
    write_consolidated_json,
    now_fn=time.time,
):
    try:
        db_state = db_stats()
        db_total = db_state.get("total_products", 0)
        LOGGER.info(
            "IVEN bridge started db_products=%s db_names=%s",
            db_total,
            db_state.get("total_names", 0),
        )

        df = read_consolidated_df(session_dir)
        if df.empty:
            with lock:
                status.update({"running": False, "message": "Нет данных", "finished_at": int(now_fn())})
            return

        if "OnlinerID" not in df.columns:
            df["OnlinerID"] = ""
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"] = df["Ссылка"].astype("object")

        if db_total == 0:
            LOGGER.info("IVEN bridge populating empty catalog database")
            db_populate_from_df(df, "price_load", skip_suppliers=["N-Tech", "TGPC"])
            db_state = db_stats()
            db_total = db_state.get("total_products", 0)
            if db_total == 0:
                with lock:
                    status.update({
                        "running": False,
                        "message": "БД пуста. Загрузи прайс IVEN/BN чтобы заполнить базу.",
                        "finished_at": int(now_fn()),
                    })
                return

        tasks = []
        for row_idx, row in df.iterrows():
            if normalize_onliner_id(row.get("OnlinerID", "")):
                continue
            name = str(row.get("Название", "")).strip()
            if not name or is_tgpc_pc_name(name):
                continue
            supplier = str(row.get("Поставщик", "") or "").strip()
            tasks.append((int(row_idx), name, supplier))

        with lock:
            status.update({
                "total": len(tasks),
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 0,
                "message": (
                    f"Найдено {len(tasks)} товаров без ID. БД: {db_total} позиций..."
                    + (" Режим: B2B без кеша." if prefer_b2b else "")
                ),
            })

        if not tasks:
            with lock:
                status.update({
                    "running": False,
                    "message": "Все товары уже имеют OnlinerID.",
                    "finished_at": int(now_fn()),
                })
            return

        manual_bindings = load_manual_id_bindings()
        id_cache = load_id_cache()
        applied = 0
        skipped = 0
        journal_changes = []
        matches_log = []
        no_match_log = []

        for done_idx, (row_idx, name, supplier) in enumerate(tasks, start=1):
            percent = max(1, int(round(done_idx / len(tasks) * 100)))
            with lock:
                status.update({
                    "done": done_idx - 1,
                    "applied": applied,
                    "skipped": skipped,
                    "percent": percent,
                    "message": f"Ищу {done_idx}/{len(tasks)}: {name[:60]}",
                })

            name_key = normalize_name_key(name)
            manual_key = supplier_scoped_binding_key(name_key, supplier)
            if (not ignore_manual_cache) and manual_key and manual_key in manual_bindings:
                cached_manual = manual_bindings.get(manual_key) or {}
                manual_id = normalize_onliner_id(cached_manual.get("id", ""))
                manual_url = str(cached_manual.get("url", "")).strip()
                if manual_id:
                    old_id = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                    df.at[row_idx, "OnlinerID"] = manual_id
                    df.at[row_idx, "Ссылка"] = manual_url
                    journal_changes.append({
                        "row_idx": row_idx,
                        "name": name,
                        "supplier": supplier,
                        "old_onliner_id": old_id,
                        "old_url": old_url,
                        "new_onliner_id": manual_id,
                        "new_url": manual_url,
                        "matched_name": "manual_cache",
                        "reason": "db_bridge manual_cache",
                    })
                    matches_log.append({
                        "name": name,
                        "supplier": supplier,
                        "row_idx": row_idx,
                        "matched_name": "Ручная привязка из вечного кеша",
                        "score": 1.0,
                        "id": manual_id,
                        "url": manual_url,
                        "source": "manual_cache",
                    })
                    applied += 1
                    continue
                skipped += 1
                continue

            match = db_find_id_for_name(name, threshold=0.40, allow_b2b=prefer_b2b)
            top_candidates = db_find_top_candidates(name, top_n=3, min_score=0.40, allow_b2b=prefer_b2b)
            if not match:
                skipped += 1
                no_match_log.append({"name": name, "supplier": supplier, "row_idx": row_idx, "candidates": top_candidates})
                continue

            oid = normalize_onliner_id(match["id"])
            url = str(match.get("url", "") or "").strip()
            score = float(match.get("score") or 0.0)
            match_source = str(match.get("source", "") or "").strip()
            matched_name = str(match.get("name", "") or "").strip()

            if match_source == "db_exact":
                LOGGER.debug(
                    "IVEN bridge exact match id=%s score=%.3f",
                    oid,
                    score,
                )
                if name_key:
                    manual_bindings[manual_key] = build_supplier_binding_record(oid, url, supplier)
                cache_key = get_id_cache_key_for_name(name)
                if cache_key:
                    id_cache[cache_key] = {"id": oid, "url": url}

                old_id = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                df.at[row_idx, "OnlinerID"] = oid
                df.at[row_idx, "Ссылка"] = url
                journal_changes.append({
                    "row_idx": row_idx,
                    "name": name,
                    "supplier": supplier,
                    "old_onliner_id": old_id,
                    "old_url": old_url,
                    "new_onliner_id": oid,
                    "new_url": url,
                    "matched_name": matched_name,
                    "reason": f"db_bridge {match_source or 'exact'} score={round(score, 3)}",
                })
                matches_log.append({
                    "name": name,
                    "supplier": supplier,
                    "row_idx": row_idx,
                    "matched_name": matched_name,
                    "score": round(score, 3),
                    "id": oid,
                    "url": url,
                    "source": match_source,
                })
                applied += 1
                continue

            merged_candidates = []
            seen_candidate_ids = set()

            def _push_candidate(candidate_id, candidate_name, candidate_url, candidate_score):
                candidate_id = normalize_onliner_id(candidate_id)
                if not candidate_id or candidate_id in seen_candidate_ids:
                    return
                seen_candidate_ids.add(candidate_id)
                merged_candidates.append({
                    "id": candidate_id,
                    "name": str(candidate_name or "").strip(),
                    "url": str(candidate_url or "").strip(),
                    "score": round(float(candidate_score or 0.0), 3),
                })

            _push_candidate(oid, matched_name, url, score)
            for candidate in top_candidates:
                _push_candidate(candidate.get("id", ""), candidate.get("name", ""), candidate.get("url", ""), candidate.get("score", 0.0))

            skipped += 1
            no_match_log.append({
                "name": name,
                "supplier": supplier,
                "row_idx": row_idx,
                "best_score": round(score, 3),
                "best_id": oid,
                "best_name": matched_name,
                "best_source": match_source,
                "needs_manual": True,
                "candidates": merged_candidates[:5],
            })
            LOGGER.debug(
                "IVEN bridge manual review id=%s source=%s score=%.3f",
                oid,
                match_source,
                score,
            )

        save_manual_id_bindings(manual_bindings)
        save_id_cache(id_cache)
        if journal_changes:
            append_id_change_journal({
                "ts": int(now_fn()),
                "action": "autofill_iven_bridge",
                "session_dir": str(session_dir),
                "source": "api_autofill_iven_bridge",
                "changes": journal_changes,
            })
        if applied > 0:
            write_consolidated_df(session_dir, df)
            write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        mode_suffix = " Режим: B2B без кеша." if prefer_b2b else ""
        message = f"Готово. Автоподобрано 100%: {applied}, на ручную проверку: {len(no_match_log)}.{mode_suffix}"
        LOGGER.info(
            "IVEN bridge completed total=%s applied=%s review=%s",
            len(tasks),
            applied,
            len(no_match_log),
        )
        with lock:
            status.update({
                "running": False,
                "done": len(tasks),
                "applied": applied,
                "skipped": skipped,
                "percent": 100,
                "message": message,
                "finished_at": int(now_fn()),
                "matches": matches_log,
                "no_match": no_match_log,
            })
    except Exception as exc:
        LOGGER.exception("IVEN bridge failed")
        with lock:
            status.update({
                "running": False,
                "message": f"Ошибка IVEN-бриджа: {str(exc)[:180]}",
                "finished_at": int(now_fn()),
            })


@_with_status_job_context
def run_tgpc_pc_worker(
    session_dir,
    *,
    max_items=0,
    status,
    lock,
    read_consolidated_df,
    load_app_settings,
    row_category,
    is_tgpc_pc_name,
    db_search_tgpc_pc_candidates,
    get_id_cache_key_for_name,
    normalize_name_key,
    load_id_cache,
    save_id_cache,
    load_manual_id_bindings,
    save_manual_id_bindings,
    append_id_change_journal,
    write_consolidated_df,
    write_consolidated_json,
    target_supplier_names=None,
    pc_label="TGPC ПЭВМ",
    action_name="autofill_tgpc_pc_ids",
    source_name="db_autofill_tgpc_pc_ids",
    get_id_cache_keys_for_name=None,
    get_manual_binding_keys_for_name=None,
    get_match_identity_for_name=None,
    clear_duplicate_ids_for_suppliers=None,
    now_fn=time.time,
):
    df = read_consolidated_df(session_dir)
    report_items = []
    try:
        if df.empty:
            with lock:
                status.update({
                    "running": False,
                    "message": "Нет данных для обработки",
                    "finished_at": int(now_fn()),
                })
            return
        if "OnlinerID" not in df.columns:
            df["OnlinerID"] = ""
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"] = df["Ссылка"].astype("object")

        settings = load_app_settings()
        no_id_cfg = settings.get("no_id_search") or {}
        limit = max(10, min(int(no_id_cfg.get("max_candidates", 80) or 80), 80))

        tasks = []
        identity_names = {}
        supplier_lookup = {
            str(name or "").strip().upper()
            for name in (target_supplier_names or [])
            if str(name or "").strip()
        }
        for row_idx, row in df.iterrows():
            supplier = str(row.get("Поставщик", "") or "").strip().upper()
            if supplier_lookup and supplier not in supplier_lookup:
                continue
            name = str(row.get("Название", "")).strip()
            if not name or not is_tgpc_pc_name(name):
                continue
            if callable(get_match_identity_for_name):
                identity = str(get_match_identity_for_name(name) or "").strip().lower()
                if identity:
                    identity_names.setdefault((supplier, identity), set()).add(normalize_name_key(name))
            if normalize_onliner_id(row.get("OnlinerID", "")):
                continue
            tasks.append((
                int(row_idx),
                name,
                str(row_category(row) or "").strip(),
                str(row.get("Поставщик", "") or "").strip(),
            ))

        if max_items and len(tasks) > int(max_items):
            tasks = tasks[:int(max_items)]

        with lock:
            status.update({
                "total": int(len(tasks)),
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 0,
                "items": [],
                "message": f"Найдено {pc_label} без ID: {len(tasks)}. Начинаю подбор...",
            })

        id_cache = load_id_cache()
        manual_bindings = load_manual_id_bindings()
        journal_entry = {
            "ts": int(now_fn()),
            "action": action_name,
            "session_dir": str(session_dir),
            "source": source_name,
            "changes": [],
        }

        applied = 0
        skipped = 0
        for done_idx, (row_idx, name, _category, supplier) in enumerate(tasks, start=1):
            in_progress_percent = max(1, int(round(((done_idx - 1) / len(tasks)) * 100))) if tasks else 100
            with lock:
                status.update({
                    "done": int(done_idx - 1),
                    "applied": int(applied),
                    "skipped": int(skipped),
                    "percent": int(in_progress_percent),
                    "message": f"Проверяю {done_idx} из {len(tasks)}: {name[:72]}",
                })
            match_identity = ""
            if callable(get_match_identity_for_name):
                match_identity = str(get_match_identity_for_name(name) or "").strip().lower()
            identity_variants = identity_names.get((str(supplier or "").strip().upper(), match_identity), set())
            if match_identity and len(identity_variants) > 1:
                skipped += 1
                report_items.append({
                    "row_idx": int(row_idx),
                    "name": name,
                    "supplier": supplier,
                    "status": "ambiguous_identity",
                    "onliner_id": "",
                    "onliner_name": "",
                    "score": 0.0,
                    "reason": "Одинаковый код поставщика встречается у разных конфигураций",
                })
                percent = int(round((done_idx / len(tasks)) * 100)) if tasks else 100
                with lock:
                    status.update({
                        "done": int(done_idx),
                        "applied": int(applied),
                        "skipped": int(skipped),
                        "percent": int(percent),
                        "items": report_items[-20:],
                        "message": f"Обработано {done_idx} из {len(tasks)}. Подставлено: {applied}.",
                    })
                continue
            try:
                candidates = db_search_tgpc_pc_candidates(name, limit=min(limit, 24))
            except Exception:
                skipped += 1
                candidates = []

            if candidates:
                top = candidates[0] if isinstance(candidates[0], dict) else {}
                top_id = normalize_onliner_id(top.get("id", ""))
                top_url = str(top.get("url", "")).strip()
                top_score = float(top.get("score", 0) or 0)
                second_score = 0.0
                if len(candidates) > 1 and isinstance(candidates[1], dict):
                    try:
                        second_score = float(candidates[1].get("score", 0) or 0)
                    except Exception:
                        second_score = 0.0

                confident = bool(top_id and (top_score >= 0.95 or (top_score >= 0.92 and (top_score - second_score) >= 0.05)))
                if confident:
                    cache_keys = []
                    if callable(get_id_cache_keys_for_name):
                        cache_keys = list(get_id_cache_keys_for_name(name) or [])
                    else:
                        cache_keys = [get_id_cache_key_for_name(name)]
                    for cache_key in _unique_nonempty(cache_keys):
                        id_cache[cache_key] = {"id": top_id, "url": top_url}
                    binding_keys = []
                    if callable(get_manual_binding_keys_for_name):
                        binding_keys = list(get_manual_binding_keys_for_name(name) or [])
                    else:
                        binding_keys = [normalize_name_key(name)]
                    for name_key in _unique_nonempty(binding_keys):
                        binding_key = supplier_scoped_binding_key(name_key, supplier)
                        manual_bindings[binding_key] = build_supplier_binding_record(top_id, top_url, supplier)

                    old_id = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                    df.at[row_idx, "OnlinerID"] = top_id
                    if top_url:
                        df.at[row_idx, "Ссылка"] = top_url
                    journal_entry["changes"].append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "supplier": supplier,
                        "old_onliner_id": old_id,
                        "old_url": old_url,
                        "new_onliner_id": top_id,
                        "new_url": top_url,
                        "score": round(top_score, 4),
                    })
                    applied += 1
                    report_items.append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "supplier": supplier,
                        "status": "matched",
                        "onliner_id": top_id,
                        "onliner_name": str(top.get("name", "")).strip(),
                        "score": round(top_score, 3),
                    })
                else:
                    skipped += 1
                    report_items.append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "supplier": supplier,
                        "status": "skipped",
                        "onliner_id": top_id,
                        "onliner_name": str(top.get("name", "")).strip(),
                        "score": round(top_score, 3),
                    })
            else:
                skipped += 1
                report_items.append({
                    "row_idx": int(row_idx),
                    "name": name,
                    "supplier": supplier,
                    "status": "not_found",
                    "onliner_id": "",
                    "onliner_name": "",
                    "score": 0.0,
                })

            percent = int(round((done_idx / len(tasks)) * 100)) if tasks else 100
            with lock:
                status.update({
                    "done": int(done_idx),
                    "applied": int(applied),
                    "skipped": int(skipped),
                    "percent": int(percent),
                    "items": report_items[-20:],
                    "message": f"Обработано {done_idx} из {len(tasks)}. Подставлено: {applied}.",
                })

        save_id_cache(id_cache)
        save_manual_id_bindings(manual_bindings)
        if journal_entry["changes"]:
            append_id_change_journal(journal_entry)
        if callable(clear_duplicate_ids_for_suppliers):
            clear_duplicate_ids_for_suppliers(df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")
        write_consolidated_df(session_dir, df)
        with lock:
            status.update({
                "running": False,
                "done": int(len(tasks)),
                "applied": int(applied),
                "skipped": int(skipped),
                "percent": 100 if tasks else 0,
                "items": report_items[-50:],
                "finished_at": int(now_fn()),
                "message": f"Автоподбор завершён: подставлено {applied} из {len(tasks)} {pc_label}.",
            })
    except Exception as exc:
        with lock:
            status.update({
                "running": False,
                "items": report_items[-50:],
                "done": int(len(report_items)),
                "finished_at": int(now_fn()),
                "message": f"Ошибка автоподбора {pc_label}: " + str(exc)[:180],
            })


def _unique_nonempty(values):
    out = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def reject_iven_match_payload(
    session_dir,
    payload,
    *,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    normalize_name_key,
    load_manual_id_bindings,
    save_manual_id_bindings,
    blank_id_value="",
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    payload = payload if isinstance(payload, dict) else {}
    item_name = str(payload.get("name", "")).strip()
    supplier = str(payload.get("supplier", "") or "").strip()
    row_idx = payload.get("row_idx")
    if not item_name:
        return {"status": "error", "message": "name required"}, 400
    try:
        df = read_consolidated_df(session_dir)
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        if "Ссылка" in df.columns:
            df["Ссылка"] = df["Ссылка"].astype("object")
        cleared = 0
        if row_idx is not None:
            try:
                row_int = int(row_idx)
                if row_int in df.index:
                    row = df.loc[row_int]
                    same_name = normalize_name_key(str(row.get("Название", ""))) == normalize_name_key(item_name)
                    same_supplier = not supplier or str(row.get("Поставщик", "") or "").strip().upper() == supplier.upper()
                    if same_name and same_supplier:
                        df.at[row_int, "OnlinerID"] = blank_id_value
                        if "Ссылка" in df.columns:
                            df.at[row_int, "Ссылка"] = ""
                        cleared = 1
            except Exception:
                pass
        if cleared == 0 and item_name:
            name_key = normalize_name_key(item_name)
            if "Название" in df.columns:
                for idx, row in df.iterrows():
                    if normalize_name_key(str(row.get("Название", ""))) == name_key:
                        if supplier and str(row.get("Поставщик", "") or "").strip().upper() != supplier.upper():
                            continue
                        df.at[idx, "OnlinerID"] = blank_id_value
                        if "Ссылка" in df.columns:
                            df.at[idx, "Ссылка"] = ""
                        cleared += 1
                        break
        name_key = normalize_name_key(item_name)
        manual_bindings = load_manual_id_bindings()
        binding_key = supplier_scoped_binding_key(name_key, supplier)
        if binding_key and binding_key in manual_bindings:
            del manual_bindings[binding_key]
            save_manual_id_bindings(manual_bindings)
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")
        return {"status": "ok", "cleared": cleared}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}, 500
