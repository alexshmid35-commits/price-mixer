"""Onliner ID verification helpers."""

import time
from pathlib import Path

from price_mixer.services.consolidated_io import has_consolidated_data
from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.manual_id_store import (
    build_supplier_binding_record,
    supplier_scoped_binding_key,
)


class ValidationCancelledError(RuntimeError):
    """Raised when a user cancellation must abort before committing results."""


def build_verify_all_start_state(now=None):
    return {
        "running": True,
        "total": 0,
        "done": 0,
        "matched": 0,
        "mismatched": 0,
        "errors": 0,
        "items": [],
        "report_items": [],
        "started_at": int(time.time() if now is None else now),
        "finished_at": 0,
        "message": "Подготовка проверки ID...",
    }


def build_validate_clean_start_state(mode, now=None):
    if mode == "db":
        return {
            "running": True,
            "cancelled": False,
            "cancel_requested": False,
            "total": 0,
            "done": 0,
            "confirmed": 0,
            "cleared": 0,
            "skipped_api": 0,
            "queued": 0,
            "errors": 0,
            "mode": "db",
            "mode_label": "Локальная БД 150k",
            "skipped_label": "Пропуск = ID или имя не найдены в локальной БД, поэтому ID оставили без изменений.",
            "started_at": int(time.time() if now is None else now),
            "finished_at": 0,
            "message": "Подготовка локальной сверки...",
        }
    return {
        "running": True,
        "cancelled": False,
        "cancel_requested": False,
        "total": 0,
        "done": 0,
        "confirmed": 0,
        "cleared": 0,
        "skipped_api": 0,
        "queued": 0,
        "errors": 0,
        "mode": "api",
        "mode_label": "Onliner API",
        "skipped_label": "Пропуск = API не ответил, ID не меняли.",
        "started_at": int(time.time() if now is None else now),
        "finished_at": 0,
        "message": "Подготовка валидации...",
    }


def build_validate_clean_no_column_state(now=None):
    return {
        "running": False,
        "finished_at": int(time.time() if now is None else now),
        "message": "В текущем прайсе нет колонки OnlinerID.",
    }


def build_validate_clean_no_tasks_state(mode, now=None):
    mode = str(mode or "api").strip().lower()
    if mode == "db":
        message = "Нет товаров с OnlinerID для локальной проверки (или все TGPC ПЭВМ)."
    else:
        message = "Нет товаров с OnlinerID для проверки (или все TGPC ПЭВМ)."
    return {
        "running": False,
        "finished_at": int(time.time() if now is None else now),
        "message": message,
    }


def build_validate_clean_error_state(mode, error, now=None):
    mode = str(mode or "api").strip().lower()
    prefix = "Ошибка локальной проверки: " if mode == "db" else "Ошибка валидации: "
    return {
        "running": False,
        "cancelled": False,
        "cancel_requested": False,
        "finished_at": int(time.time() if now is None else now),
        "message": prefix + str(error)[:180],
    }


def build_validate_clean_cancelled_state(mode, now=None):
    mode = str(mode or "api").strip().lower()
    label = "Локальная проверка" if mode == "db" else "Проверка ID"
    return {
        "running": False,
        "cancelled": True,
        "cancel_requested": False,
        "finished_at": int(time.time() if now is None else now),
        "message": f"{label} отменена пользователем. Изменения не применены.",
    }


def build_validate_clean_prepare_progress_state(mode, total):
    total = int(total)
    mode = str(mode or "api").strip().lower()
    state = {
        "total": total,
        "done": 0,
        "confirmed": 0,
        "cleared": 0,
        "queued": 0,
        "errors": 0,
        "message": f"Фаза 1: проверяю {total} товаров...",
    }
    if mode == "db":
        state.update({
            "skipped_api": 0,
            "mode": "db",
            "mode_label": "Локальная БД 150k",
            "skipped_label": "Пропуск = ID или имя не найдены в локальной БД, поэтому ID оставили без изменений.",
            "message": f"Локальная сверка: проверяю {total} товаров...",
        })
    return state


def build_validate_clean_step_progress_state(
    mode,
    done,
    total,
    current_name,
    confirmed,
    cleared,
    skipped,
    errors,
):
    mode = str(mode or "api").strip().lower()
    prefix = "Локальная сверка" if mode == "db" else "Фаза 1"
    current_name = str(current_name or "").strip()
    return {
        "done": int(done),
        "confirmed": int(confirmed),
        "cleared": int(cleared),
        "skipped_api": int(skipped),
        "errors": int(errors),
        "message": f"{prefix}: {int(done)}/{int(total)} — {current_name[:55]}",
    }


def build_validate_clean_candidates_start_state(mode, cleared_count):
    mode = str(mode or "api").strip().lower()
    prefix = "Локальная сверка" if mode == "db" else "Фаза 2"
    return {
        "message": f"{prefix}: ищу кандидатов для {int(cleared_count)} очищенных товаров...",
    }


def build_validate_clean_candidates_step_state(mode, current, total, current_name):
    mode = str(mode or "api").strip().lower()
    prefix = "Локальная сверка" if mode == "db" else "Фаза 2"
    current_name = str(current_name or "").strip()
    return {
        "message": f"{prefix}: кандидаты {int(current)}/{int(total)} — {current_name[:50]}",
    }


def build_validate_clean_queued_state(queued):
    return {"queued": int(queued)}


def save_validate_clean_results(
    mode,
    session_dir,
    df,
    manual_bindings,
    review_queue,
    journal_changes,
    save_manual_id_bindings=None,
    save_review_queue=None,
    append_id_change_journal=None,
    write_consolidated_df=None,
    write_consolidated_json=None,
    now=None,
):
    mode = str(mode or "api").strip().lower()
    if mode == "db":
        action = "validate_clean_ids_db"
        source = "api_validate_clean_ids_db"
    else:
        action = "validate_clean_ids"
        source = "api_validate_clean_ids"

    if callable(save_manual_id_bindings):
        save_manual_id_bindings(manual_bindings)
    if callable(save_review_queue):
        save_review_queue(review_queue)

    journal_entry = None
    if journal_changes:
        journal_entry = {
            "ts": int(time.time() if now is None else now),
            "action": action,
            "session_dir": str(session_dir),
            "source": source,
            "changes": journal_changes,
        }
        if callable(append_id_change_journal):
            append_id_change_journal(journal_entry)

    if callable(write_consolidated_df):
        write_consolidated_df(session_dir, df)
    if callable(write_consolidated_json):
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

    return journal_entry


def run_validate_clean_api_tasks(
    df,
    tasks,
    manual_bindings,
    product_cache,
    product_cache_ttl,
    fetch_product_name,
    is_manually_confirmed_id,
    calc_name_match,
    normalize_name_key,
    progress_update=None,
    log=None,
    product_cache_lock=None,
    clear_threshold=0.65,
    hard_timeout=9,
    clear_value="",
    progress_every=50,
):
    state = _empty_validate_clean_run_state()
    tasks = list(tasks or [])
    _emit_log(log, f"[validate] Старт Фазы 1: {len(tasks)} товаров")
    for task_i, (row_idx, row) in enumerate(tasks):
        name = str(row.get("Название", "")).strip()
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        name_key = normalize_name_key(name) if callable(normalize_name_key) else ""
        result = None
        try:
            result = validate_clean_api_row(
                row_idx,
                row,
                product_cache=product_cache,
                product_cache_ttl=product_cache_ttl,
                fetch_product_name=fetch_product_name,
                is_manually_confirmed_id=is_manually_confirmed_id,
                calc_name_match=calc_name_match,
                clear_threshold=clear_threshold,
                hard_timeout=hard_timeout,
                cache_lock=product_cache_lock,
            )
        except Exception as exc:
            _emit_log(log, f"[validate] ОШИБКА #{task_i + 1}: {name[:50]} | {exc}")
            state["errors"] += 1

        state["done"] += 1
        if state["done"] % int(progress_every) == 0 or state["done"] == 1:
            _emit_log(log, f"[validate] Фаза 1: {state['done']}/{len(tasks)} — {name[:60]}")

        if result is not None:
            deltas = apply_validate_clean_api_result(
                df,
                result,
                name_key,
                manual_bindings,
                state["confirmed_rows"],
                state["skipped_rows"],
                state["cleared_items"],
                state["journal_changes"],
                supplier_name=str(row.get("Поставщик", "") or "").strip(),
                clear_value=clear_value,
            )
            state["confirmed"] += int(deltas.get("confirmed", 0) or 0)
            state["skipped"] += int(deltas.get("skipped_api", 0) or 0)

        _emit_progress(progress_update, build_validate_clean_step_progress_state(
            "api",
            done=state["done"],
            total=len(tasks),
            current_name=name,
            confirmed=state["confirmed"],
            cleared=len(state["cleared_items"]),
            skipped=state["skipped"],
            errors=state["errors"],
        ))

    _emit_log(
        log,
        f"[validate] Фаза 1 завершена: подтверждено={state['confirmed']}, очищено={len(state['cleared_items'])}, "
        f"пропущено (API): {state['skipped']}, ошибок={state['errors']}",
    )
    return state


def run_validate_clean_db_tasks(
    df,
    tasks,
    manual_bindings,
    is_manually_confirmed_id,
    db_get_product_by_id,
    db_find_exact_id_for_name,
    calc_name_match,
    normalize_name_key,
    progress_update=None,
    log=None,
    clear_threshold=0.65,
    clear_value="",
    progress_every=100,
    should_cancel=None,
):
    state = _empty_validate_clean_run_state()
    tasks = list(tasks or [])
    for row_idx, row in tasks:
        if callable(should_cancel) and should_cancel():
            raise ValidationCancelledError("validation cancelled")
        name = str(row.get("Название", "")).strip()
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        name_key = normalize_name_key(name) if callable(normalize_name_key) else ""
        result = None
        try:
            result = validate_clean_db_row(
                name,
                oid,
                supplier=str(row.get("Поставщик", "")).strip(),
                is_manually_confirmed_id=is_manually_confirmed_id,
                db_get_product_by_id=db_get_product_by_id,
                db_find_exact_id_for_name=db_find_exact_id_for_name,
                calc_name_match=calc_name_match,
                clear_threshold=clear_threshold,
            )
        except Exception as exc:
            _emit_log(log, f"[validate-db] ОШИБКА {name[:60]} | {exc}")
            state["errors"] += 1

        state["done"] += 1
        if state["done"] % int(progress_every) == 0 or state["done"] == 1:
            _emit_log(log, f"[validate-db] {state['done']}/{len(tasks)} — {name[:60]}")

        if result is not None:
            deltas = apply_validate_clean_db_result(
                df,
                result,
                row_idx,
                name,
                name_key,
                oid,
                manual_bindings,
                state["confirmed_rows"],
                state["skipped_rows"],
                state["cleared_items"],
                state["journal_changes"],
                supplier_name=str(row.get("Поставщик", "") or "").strip(),
                db_get_product_by_id=db_get_product_by_id,
                clear_value=clear_value,
            )
            state["confirmed"] += int(deltas.get("confirmed", 0) or 0)
            state["skipped"] += int(deltas.get("skipped_local", 0) or 0)

        _emit_progress(progress_update, build_validate_clean_step_progress_state(
            "db",
            done=state["done"],
            total=len(tasks),
            current_name=name,
            confirmed=state["confirmed"],
            cleared=len(state["cleared_items"]),
            skipped=state["skipped"],
            errors=state["errors"],
        ))
    return state


def populate_api_review_queue_for_cleared_items(
    cleared_items,
    review_queue,
    search_onliner_candidates,
    limit_cands,
    progress_update=None,
    should_cancel=None,
):
    queued = 0
    cleared_items = list(cleared_items or [])
    if cleared_items:
        _emit_progress(progress_update, build_validate_clean_candidates_start_state("api", len(cleared_items)))
    for ci_idx, cleared_item in enumerate(cleared_items, 1):
        if callable(should_cancel) and should_cancel():
            raise ValidationCancelledError("validation cancelled")
        _row_idx, name, name_key, old_id, api_name, score, _clear_reason = cleared_item[:7]
        supplier = str(cleared_item[7] if len(cleared_item) > 7 else "").strip()
        _emit_progress(progress_update, build_validate_clean_candidates_step_state(
            "api",
            current=ci_idx,
            total=len(cleared_items),
            current_name=name,
        ))
        try:
            candidates = search_onliner_candidates(
                name,
                category_name="",
                query="",
                limit=min(int(limit_cands), 10),
                max_queries=3,
                timeout_sec=6,
            )
            top_candidates = build_api_review_candidates(candidates, limit=3)
        except Exception:
            top_candidates = []

        if name_key:
            queue_key = supplier_scoped_binding_key(name_key, supplier)
            review_queue[queue_key] = build_api_review_queue_item(
                name=name,
                cleared_id=old_id,
                cleared_score=score,
                onliner_name=api_name,
                candidates=top_candidates,
                supplier=supplier,
                match_name_key=name_key,
            )
        if top_candidates:
            queued += 1
        _emit_progress(progress_update, build_validate_clean_queued_state(queued))
    return queued


def populate_db_review_queue_for_cleared_items(
    cleared_items,
    review_queue,
    db_find_top_candidates,
    progress_update=None,
    should_cancel=None,
):
    queued = 0
    cleared_items = list(cleared_items or [])
    if cleared_items:
        _emit_progress(progress_update, build_validate_clean_candidates_start_state("db", len(cleared_items)))
    for ci_idx, cleared_item in enumerate(cleared_items, 1):
        if callable(should_cancel) and should_cancel():
            raise ValidationCancelledError("validation cancelled")
        _row_idx, name, name_key, old_id, db_name, score, _clear_reason, exact_match = cleared_item[:8]
        supplier = str(cleared_item[8] if len(cleared_item) > 8 else "").strip()
        _emit_progress(progress_update, build_validate_clean_candidates_step_state(
            "db",
            current=ci_idx,
            total=len(cleared_items),
            current_name=name,
        ))
        top_candidates = build_db_review_candidates(
            exact_match=exact_match,
            fuzzy_candidates=db_find_top_candidates(name, top_n=5, min_score=0.40),
        )

        if name_key:
            queue_key = supplier_scoped_binding_key(name_key, supplier)
            review_queue[queue_key] = build_db_review_queue_item(
                name=name,
                cleared_id=old_id,
                cleared_score=score,
                onliner_name=db_name,
                candidates=top_candidates,
                supplier=supplier,
                match_name_key=name_key,
            )
        if top_candidates:
            queued += 1
        _emit_progress(progress_update, build_validate_clean_queued_state(queued))
    return queued


def start_validation_job(session_dir, status, lock, start_state, worker, thread_factory, before_start=None):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    if not has_consolidated_data(session_dir):
        return {"status": "error", "message": "Нет данных"}, 400

    with lock:
        if status.get("running"):
            return {"status": "already_running"}
        if callable(before_start):
            before_start(session_dir)
        status.clear()
        status.update(start_state)

    thread_factory(target=worker, args=(str(session_dir),), daemon=True).start()
    return {"status": "started"}


def cancel_validation_job(session_dir, status, lock, cancel):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    with lock:
        if not status.get("running"):
            return {"status": "not_running", "message": "Активной проверки нет."}
        status["cancel_requested"] = True
        status["message"] = "Останавливаю проверку..."
    if callable(cancel):
        cancel(session_dir)
    return {"status": "cancelling", "message": "Останавливаю проверку..."}


def verify_all_status_snapshot(status, lock):
    with lock:
        snapshot = dict(status)
        snapshot["items"] = list(snapshot.get("items", []) or [])
        return snapshot


def status_snapshot(status, lock):
    with lock:
        return dict(status)


def collect_id_validation_tasks(df, is_tgpc_pc_name=None, require_name=True):
    tasks = []
    skipped_tgpc_pc = 0
    is_tgpc_pc_name = is_tgpc_pc_name or (lambda name: False)
    for index, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        if require_name and not name:
            continue
        if is_tgpc_pc_name(name):
            skipped_tgpc_pc += 1
            continue
        tasks.append((int(index), row.copy()))
    return tasks, skipped_tgpc_pc


def sort_verify_result_items(result_items, report_items):
    result_items.sort(key=lambda item: (float(item.get("score", 0.0) or 0.0), str(item.get("name", "")).lower()))
    report_items.sort(key=lambda item: (
        0 if str(item.get("status", "")).strip().lower() == "mismatch" else 1,
        0 if str(item.get("status", "")).strip().lower() == "review" else 1,
        str(item.get("name", "")).lower(),
    ))
    return result_items, report_items


def build_validate_cleared_rows_report(cleared_items, mode="api"):
    rows = []
    for item in cleared_items:
        if mode == "db":
            row_idx, name, name_key, old_id, db_name, score, clear_reason, exact_match = item[:8]
            if clear_reason == "db_exact_points_other_id" and exact_match:
                api_name = f"Локальная БД знает этот товар как ID {normalize_onliner_id(exact_match.get('id', ''))}"
            else:
                api_name = db_name or "—"
        else:
            row_idx, name, name_key, old_id, api_name, score, clear_reason = (
                item[:7] if len(item) >= 7 else (*item[:6], "")
            )
            if clear_reason == "api_not_found":
                api_name = "HTTP 404 — товара с этим ID нет в каталоге Onliner"
            elif api_name:
                api_name = api_name
            else:
                api_name = "—"
        rows.append({
            "name": name,
            "onliner_id": old_id,
            "api_name": api_name,
            "score": score,
            "clear_reason": clear_reason,
        })
    return rows


def build_validate_clean_finish_state(
    mode,
    total,
    confirmed,
    cleared_items,
    skipped,
    queued,
    errors,
    confirmed_rows,
    skipped_rows,
    now=None,
    skipped_limit=500,
):
    cleared_items = list(cleared_items or [])
    confirmed_rows = list(confirmed_rows or [])
    skipped_rows = list(skipped_rows or [])
    cleared_count = len(cleared_items)
    mode = str(mode or "api").strip().lower()

    if mode == "db":
        message = (
            f"Локальная сверка готова. Подтверждено: {int(confirmed)}, очищено: {cleared_count}"
            + (f", пропущено: {int(skipped)}" if skipped else "")
            + (f", ошибок: {int(errors)}" if errors else "")
            + "."
        )
    else:
        mode = "api"
        message = (
            f"Готово. Подтверждено: {int(confirmed)}, очищено: {cleared_count}"
            + (f", пропущено (сбой API, ID сохранён): {int(skipped)}" if skipped else "")
            + (f", ошибок: {int(errors)}" if errors else "")
            + "."
        )

    return {
        "running": False,
        "done": int(total),
        "confirmed": int(confirmed),
        "cleared": cleared_count,
        "skipped_api": int(skipped),
        "queued": int(queued),
        "errors": int(errors),
        "finished_at": int(time.time() if now is None else now),
        "cleared_rows": build_validate_cleared_rows_report(cleared_items, mode=mode),
        "confirmed_rows": confirmed_rows,
        "skipped_rows": skipped_rows[:skipped_limit],
        "message": message,
    }


def build_db_review_candidates(exact_match=None, fuzzy_candidates=None, limit=5):
    candidates = []
    seen_ids = set()

    def append_candidate(candidate_id, name, url, score, source):
        candidate_id = normalize_onliner_id(candidate_id)
        if not candidate_id or candidate_id in seen_ids:
            return
        seen_ids.add(candidate_id)
        candidates.append({
            "id": candidate_id,
            "name": str(name or "").strip(),
            "score": round(float(score or 0.0), 3),
            "url": str(url or "").strip(),
            "source": str(source or "").strip(),
        })

    if exact_match:
        append_candidate(
            exact_match.get("id", ""),
            exact_match.get("name", ""),
            exact_match.get("url", ""),
            1.0,
            exact_match.get("source", "db_exact"),
        )

    for candidate in fuzzy_candidates or []:
        append_candidate(
            candidate.get("id", ""),
            candidate.get("name", ""),
            candidate.get("url", ""),
            candidate.get("score", 0.0),
            candidate.get("source", "db_fuzzy"),
        )

    return candidates[:limit]


def build_api_review_candidates(candidates, limit=3):
    result = []
    seen_ids = set()
    for candidate in candidates or []:
        candidate_id = normalize_onliner_id(candidate.get("id", ""))
        if not candidate_id or candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        result.append({
            "id": candidate_id,
            "name": str(candidate.get("name", "")).strip(),
            "score": round(float(candidate.get("score", 0.0) or 0.0), 3),
            "url": str(candidate.get("url", "")).strip(),
        })
        if len(result) >= limit:
            break
    return result


def build_review_queue_item(
    name,
    cleared_id,
    cleared_score,
    onliner_name,
    candidates,
    now=None,
    limit=5,
    supplier="",
    match_name_key="",
):
    item = {
        "name": str(name or "").strip(),
        "cleared_id": normalize_onliner_id(cleared_id),
        "cleared_score": round(float(cleared_score or 0.0), 3),
        "onliner_name": str(onliner_name or "").strip(),
        "candidates": list(candidates or [])[:limit],
        "added_at": int(time.time() if now is None else now),
    }
    supplier = str(supplier or "").strip()
    match_name_key = str(match_name_key or "").strip()
    if supplier:
        item["supplier"] = supplier
    if match_name_key:
        item["match_name_key"] = match_name_key
    return item


def build_db_review_queue_item(
    name,
    cleared_id,
    cleared_score,
    onliner_name,
    candidates,
    now=None,
    limit=5,
    supplier="",
    match_name_key="",
):
    return build_review_queue_item(
        name,
        cleared_id,
        cleared_score,
        onliner_name,
        candidates,
        now=now,
        limit=limit,
        supplier=supplier,
        match_name_key=match_name_key,
    )


def build_api_review_queue_item(
    name,
    cleared_id,
    cleared_score,
    onliner_name,
    candidates,
    now=None,
    limit=3,
    supplier="",
    match_name_key="",
):
    return build_review_queue_item(
        name,
        cleared_id,
        cleared_score,
        onliner_name,
        candidates,
        now=now,
        limit=limit,
        supplier=supplier,
        match_name_key=match_name_key,
    )


def validate_clean_db_row(
    name,
    oid,
    supplier="",
    is_manually_confirmed_id=None,
    db_get_product_by_id=None,
    db_find_exact_id_for_name=None,
    calc_name_match=None,
    clear_threshold=0.65,
):
    oid = normalize_onliner_id(oid)
    name = str(name or "").strip()
    is_manually_confirmed_id = is_manually_confirmed_id or (lambda item_name, item_id: False)
    db_get_product_by_id = db_get_product_by_id or (lambda item_id: None)
    db_find_exact_id_for_name = db_find_exact_id_for_name or (lambda item_name: None)
    calc_name_match = calc_name_match or (lambda local, remote: {"score": 0.0, "reason": ""})

    if _is_manually_confirmed(is_manually_confirmed_id, name, oid, supplier):
        return {
            "status": "confirm",
            "db_name": "",
            "score": 1.0,
            "reason": "manual_confirmed",
            "exact_match": None,
        }

    current_db = db_get_product_by_id(oid)
    exact_match = db_find_exact_id_for_name(name)
    if current_db:
        db_name = str(current_db.get("name", "")).strip()
        comparison = calc_name_match(name, db_name)
        score = round(float(comparison.get("score", 0.0) or 0.0), 3)
        if score >= clear_threshold:
            return {
                "status": "confirm",
                "db_name": db_name,
                "score": score,
                "reason": str(comparison.get("reason", "") or ""),
                "exact_match": exact_match,
            }
        return {
            "status": "clear",
            "db_name": db_name,
            "score": score,
            "reason": "db_id_name_mismatch",
            "exact_match": exact_match,
        }

    if exact_match and normalize_onliner_id(exact_match.get("id", "")) != oid:
        return {
            "status": "clear",
            "db_name": str(exact_match.get("name", "")).strip(),
            "score": 0.0,
            "reason": "db_exact_points_other_id",
            "exact_match": exact_match,
        }

    return {
        "status": "skip",
        "db_name": "",
        "score": 0.0,
        "reason": "db_missing_or_uncertain",
        "exact_match": exact_match,
    }


def validate_clean_api_row(
    row_idx,
    row,
    product_cache=None,
    product_cache_ttl=0,
    fetch_product_name=None,
    is_manually_confirmed_id=None,
    calc_name_match=None,
    clear_threshold=0.65,
    now=None,
    hard_timeout=9,
    cache_lock=None,
):
    product_cache = product_cache if isinstance(product_cache, dict) else {}
    fetch_product_name = fetch_product_name or (lambda oid, hard_timeout=hard_timeout: ("", "", "error"))
    is_manually_confirmed_id = is_manually_confirmed_id or (lambda item_name, item_id: False)
    calc_name_match = calc_name_match or (lambda local, remote: {"score": 0.0, "reason": ""})

    local_name = str(row.get("Название", "")).strip()
    oid = normalize_onliner_id(row.get("OnlinerID", ""))
    supplier = str(row.get("Поставщик", "")).strip()
    if not oid:
        return None

    base = {
        "row_idx": int(row_idx),
        "onliner_id": oid,
        "name": local_name,
    }

    if _is_manually_confirmed(is_manually_confirmed_id, local_name, oid, supplier):
        return {
            **base,
            "api_name": "",
            "api_url": "",
            "score": 1.0,
            "reason": "manual_confirmed",
            "record_confirm": True,
            "mutate_df_clear": False,
        }

    now_ts = int(time.time() if now is None else now)
    api_name = ""
    api_url = ""
    cached = product_cache.get(oid)
    if isinstance(cached, dict) and now_ts - int(cached.get("updated_at", 0)) <= product_cache_ttl:
        api_name = str(cached.get("name", "")).strip()
        api_url = str(cached.get("url", "")).strip()
        if not api_name:
            return {
                **base,
                "api_name": "",
                "api_url": api_url,
                "score": 0.0,
                "reason": "api_unreachable_cached_empty",
                "record_confirm": False,
                "mutate_df_clear": False,
            }
    else:
        api_name, api_url, fetch_status = fetch_product_name(oid, hard_timeout=hard_timeout)
        api_name = str(api_name or "").strip()
        api_url = str(api_url or "").strip()
        if fetch_status == "not_found":
            return {
                **base,
                "api_name": "",
                "api_url": "",
                "score": 0.0,
                "reason": "api_not_found",
                "record_confirm": False,
                "mutate_df_clear": True,
            }
        if fetch_status in ("timeout", "http_error", "error", "empty_payload"):
            return {
                **base,
                "api_name": "",
                "api_url": api_url,
                "score": 0.0,
                "reason": "api_unreachable_" + fetch_status,
                "record_confirm": False,
                "mutate_df_clear": False,
            }
        if fetch_status == "ok" and api_name:
            if cache_lock is None:
                product_cache[oid] = {"updated_at": now_ts, "name": api_name, "url": api_url}
            else:
                with cache_lock:
                    product_cache[oid] = {"updated_at": now_ts, "name": api_name, "url": api_url}

    if not api_name:
        return {
            **base,
            "api_name": "",
            "api_url": api_url,
            "score": 0.0,
            "reason": "api_unreachable_no_name",
            "record_confirm": False,
            "mutate_df_clear": False,
        }

    comparison = calc_name_match(local_name, api_name)
    score = round(float(comparison.get("score", 0.0) or 0.0), 3)
    if score >= clear_threshold:
        return {
            **base,
            "api_name": api_name,
            "api_url": api_url,
            "score": score,
            "reason": str(comparison.get("reason", "") or ""),
            "record_confirm": True,
            "mutate_df_clear": False,
        }
    return {
        **base,
        "api_name": api_name,
        "api_url": api_url,
        "score": score,
        "reason": str(comparison.get("reason", "") or ""),
        "record_confirm": False,
        "mutate_df_clear": True,
    }


def apply_validate_clean_api_result(
    df,
    result,
    name_key,
    manual_bindings,
    confirmed_rows,
    skipped_rows,
    cleared_items,
    journal_changes,
    supplier_name="",
    clear_value="",
):
    if result is None:
        return {"confirmed": 0, "skipped_api": 0}

    row_idx = int(result.get("row_idx", 0))
    name = str(result.get("name", "")).strip()
    oid = normalize_onliner_id(result.get("onliner_id", ""))
    score = round(float(result.get("score", 0.0) or 0.0), 3)
    reason = str(result.get("reason", "") or "")
    api_name = str(result.get("api_name", "") or "").strip()
    api_url = str(result.get("api_url", "") or "").strip()
    is_manual = reason == "manual_confirmed"
    do_confirm = bool(result.get("record_confirm"))
    do_clear = bool(result.get("mutate_df_clear"))

    if not do_confirm and not do_clear:
        skipped_rows.append({
            "name": name,
            "onliner_id": oid,
            "reason": reason or "api_unreachable",
        })
        return {"confirmed": 0, "skipped_api": 1}

    confirmed = 0
    if do_confirm:
        if name_key and not is_manual:
            binding_key = supplier_scoped_binding_key(name_key, supplier_name)
            manual_bindings[binding_key] = build_supplier_binding_record(
                oid,
                api_url,
                supplier_name,
            )
        confirmed += 1
        confirmed_rows.append({
            "name": name,
            "onliner_id": oid,
            "api_name": api_name,
            "score": score,
        })

    if not do_clear:
        return {"confirmed": confirmed, "skipped_api": 0}

    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
    _clear_df_cell(df, row_idx, "OnlinerID", clear_value)
    if "Ссылка" in df.columns:
        _clear_df_cell(df, row_idx, "Ссылка", clear_value)

    journal_reason = "validate_clean api_not_found" if reason == "api_not_found" else f"validate_clean score={score}"
    journal_changes.append({
        "row_idx": row_idx,
        "name": name,
        "old_onliner_id": oid,
        "old_url": old_url,
        "new_onliner_id": "",
        "new_url": "",
        "reason": journal_reason,
    })
    cleared_item = (
        row_idx,
        name,
        name_key,
        oid,
        api_name,
        score,
        reason,
    )
    supplier_name = str(supplier_name or "").strip()
    if supplier_name:
        cleared_item += (supplier_name,)
    cleared_items.append(cleared_item)
    return {"confirmed": confirmed, "skipped_api": 0}


def apply_validate_clean_db_result(
    df,
    result,
    row_idx,
    name,
    name_key,
    oid,
    manual_bindings,
    confirmed_rows,
    skipped_rows,
    cleared_items,
    journal_changes,
    supplier_name="",
    db_get_product_by_id=None,
    clear_value="",
):
    if result is None:
        return {"confirmed": 0, "skipped_local": 0}

    db_get_product_by_id = db_get_product_by_id or (lambda item_id: None)
    row_idx = int(row_idx)
    name = str(name or "").strip()
    oid = normalize_onliner_id(oid)
    status = str(result.get("status", "") or "")
    score = round(float(result.get("score", 0.0) or 0.0), 3)
    db_name = str(result.get("db_name", "") or "").strip()
    reason = str(result.get("reason", "") or "").strip()
    exact_match = result.get("exact_match") if isinstance(result.get("exact_match"), dict) else None

    if status == "skip":
        skipped_rows.append({
            "name": name,
            "onliner_id": oid,
            "reason": reason,
        })
        return {"confirmed": 0, "skipped_local": 1}

    if status == "confirm":
        if name_key and reason != "manual_confirmed":
            binding_key = supplier_scoped_binding_key(name_key, supplier_name)
            manual_bindings[binding_key] = build_supplier_binding_record(
                oid,
                str((db_get_product_by_id(oid) or {}).get("url", "")).strip(),
                supplier_name,
            )
        confirmed_rows.append({
            "name": name,
            "onliner_id": oid,
            "api_name": db_name or "Локальная БД",
            "score": score,
        })
        return {"confirmed": 1, "skipped_local": 0}

    if status != "clear":
        return {"confirmed": 0, "skipped_local": 0}

    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
    _clear_df_cell(df, row_idx, "OnlinerID", clear_value)
    if "Ссылка" in df.columns:
        _clear_df_cell(df, row_idx, "Ссылка", clear_value)
    journal_changes.append({
        "row_idx": row_idx,
        "name": name,
        "old_onliner_id": oid,
        "old_url": old_url,
        "new_onliner_id": "",
        "new_url": "",
        "reason": f"validate_clean_db {reason} score={score}",
    })
    cleared_item = (
        row_idx,
        name,
        name_key,
        oid,
        db_name,
        score,
        reason,
        exact_match,
    )
    supplier_name = str(supplier_name or "").strip()
    if supplier_name:
        cleared_item += (supplier_name,)
    cleared_items.append(cleared_item)
    return {"confirmed": 0, "skipped_local": 0}


def verify_onliner_id_row(
    row_idx,
    row,
    settings=None,
    fetch_onliner_product_info=None,
    row_category=None,
    is_manually_confirmed_id=None,
    calc_name_match=None,
    coerce_bool=None,
    coerce_float=None,
):
    settings = settings or {}
    verify_cfg = settings.get("verify_id") or {}
    coerce_bool = coerce_bool or _default_coerce_bool
    coerce_float = coerce_float or _default_coerce_float
    row_category = row_category or (lambda item: item.get("Категория", ""))
    is_manually_confirmed_id = is_manually_confirmed_id or (lambda name, oid: False)
    calc_name_match = calc_name_match or (lambda local, remote: {"score": 0.0, "match": False, "reason": ""})

    local_name = str(row.get("Название", "")).strip()
    oid = normalize_onliner_id(row.get("OnlinerID", ""))
    supplier = str(row.get("Поставщик", "")).strip()
    category = str(row_category(row)).strip()
    if not oid:
        return None

    info = fetch_onliner_product_info(
        oid,
        force_refresh=coerce_bool(verify_cfg.get("force_refresh_api", True), default=True),
        use_cache_on_error=True,
        product_name_hint=local_name,
    ) if callable(fetch_onliner_product_info) else {}
    info = info or {}
    api_name = str(info.get("name", "")).strip()
    api_url = str(info.get("url", "")).strip()
    source = str(info.get("source", "")).strip()
    manual_ok = (
        coerce_bool(verify_cfg.get("trust_manual_confirmed", True), default=True)
        and _is_manually_confirmed(is_manually_confirmed_id, local_name, oid, supplier)
    )

    base = {
        "row_idx": int(row_idx),
        "onliner_id": oid,
        "name": local_name,
        "supplier": supplier,
        "category": category,
        "api_name": api_name,
        "api_url": api_url,
        "source": source,
    }

    if manual_ok:
        return {
            **base,
            "score": 1.0,
            "reason": "manual_confirmed",
            "reason_label": "ID подтвержден вручную и сохранен в постоянный кеш",
            "status": "match",
            "status_label": "OK",
            "source": (source + "|manual_confirmed").strip("|"),
            "needs_review": False,
        }

    if not api_name:
        api_no_name_status = str(verify_cfg.get("api_no_name_status", "review")).strip().lower()
        is_mismatch = api_no_name_status == "mismatch"
        return {
            **base,
            "api_name": "",
            "score": 0.0,
            "reason": "api_no_name",
            "reason_label": "API не вернул название товара по текущему ID",
            "status": "mismatch" if is_mismatch else "review",
            "status_label": "Проверить",
            "needs_review": True,
        }

    comparison = calc_name_match(local_name, api_name)
    score = round(float(comparison.get("score", 0.0) or 0.0), 3)
    is_match = bool(comparison.get("match"))
    threshold = coerce_float(verify_cfg.get("match_threshold", 0.74), 0.74, min_value=0.1, max_value=0.99)
    if score >= threshold:
        is_match = True
    if coerce_bool(verify_cfg.get("require_article_or_model_priority", False), default=False):
        if str(comparison.get("reason", "") or "") not in {"article", "article_like", "paren_model", "model_token"}:
            is_match = False

    return {
        **base,
        "score": score,
        "reason": str(comparison.get("reason", "") or ""),
        "reason_label": "Совпало" if is_match else "Название товара не совпало с Onliner по текущему ID",
        "status": "match" if is_match else "mismatch",
        "status_label": "OK" if is_match else "Несовпадение",
        "needs_review": not is_match,
    }


def _default_coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _is_manually_confirmed(checker, name, onliner_id, supplier=""):
    try:
        return bool(checker(name, onliner_id, supplier))
    except TypeError:
        return bool(checker(name, onliner_id))


def _default_coerce_float(value, default, min_value=None, max_value=None):
    try:
        number = float(value)
    except Exception:
        number = float(default)
    if min_value is not None:
        number = max(float(min_value), number)
    if max_value is not None:
        number = min(float(max_value), number)
    return number


def _clear_df_cell(df, row_idx, column, clear_value):
    try:
        df.at[row_idx, column] = clear_value
    except Exception:
        try:
            df[column] = df[column].astype(object)
            df.at[row_idx, column] = ""
        except Exception:
            pass


def _empty_validate_clean_run_state():
    return {
        "done": 0,
        "confirmed": 0,
        "skipped": 0,
        "errors": 0,
        "cleared_items": [],
        "confirmed_rows": [],
        "skipped_rows": [],
        "journal_changes": [],
    }


def _emit_progress(progress_update, payload):
    if callable(progress_update):
        progress_update(payload)


def _emit_log(log, message):
    if callable(log):
        log(message)
