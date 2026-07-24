import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path

from price_mixer.services.consolidated_io import has_consolidated_data
from price_mixer.services.onliner_market import (
    empty_market_stats,
    load_onliner_market_cache,
    market_stats_has_values,
    save_onliner_market_cache,
)
from price_mixer.services.product_normalization import normalize_onliner_id


MARKET_REFRESH_POOL_WORKERS = 28
MARKET_REFRESH_IDLE_TIMEOUT_SEC = 45
MARKET_REFRESH_LOCK = threading.RLock()
AUTO_REFRESH_ALLOWED_HOURS = (3, 6, 12)
AUTO_REFRESH_POLL_SEC = 20


def make_market_refresh_status():
    return {
        "running": False,
        "total": 0,
        "done": 0,
        "success": 0,
        "errors": 0,
        "categories": {},
        "recent_errors": [],
        "phase": "idle",
        "message": "",
        "started_at": 0,
        "finished_at": 0,
    }


market_refresh_status = make_market_refresh_status()


def get_market_refresh_status_snapshot(status=market_refresh_status, lock=MARKET_REFRESH_LOCK):
    with lock:
        return dict(status)


def start_market_refresh(
    session_dir,
    categories,
    worker,
    status=market_refresh_status,
    lock=MARKET_REFRESH_LOCK,
    thread_factory=threading.Thread,
    now_fn=time.time,
):
    session_dir = str(session_dir or "").strip()
    if not session_dir:
        return {"status": "error", "message": "No session"}
    if not has_consolidated_data(session_dir):
        return {"status": "error", "message": "No data"}
    if not isinstance(categories, list):
        categories = []
    with lock:
        if status.get("running"):
            return {"status": "already_running"}
        status["running"] = True
        status["started_at"] = int(now_fn())
        status["finished_at"] = 0
        status["total"] = 0
        status["done"] = 0
        status["success"] = 0
        status["errors"] = 0
        status["recent_errors"] = []
        status["categories"] = {}
        status["phase"] = "collecting"
        status["message"] = "Собираю товары с OnlinerID для обновления цен."
    thread = thread_factory(target=worker, args=(session_dir, categories), daemon=True)
    thread.start()
    return {"status": "started"}


def market_refresh_worker(
    session_dir,
    categories,
    read_consolidated_df,
    ensure_category_column,
    row_category,
    fetch_market_stats,
    load_cache=load_onliner_market_cache,
    save_cache=save_onliner_market_cache,
    status=market_refresh_status,
    lock=MARKET_REFRESH_LOCK,
    max_workers=MARKET_REFRESH_POOL_WORKERS,
    idle_timeout_sec=MARKET_REFRESH_IDLE_TIMEOUT_SEC,
    now_fn=time.time,
):
    try:
        if not has_consolidated_data(session_dir):
            with lock:
                status.update({"running": False, "finished_at": int(now_fn())})
            return

        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        selected = {str(category).strip() for category in categories if str(category).strip()}
        if selected:
            df = df[df.apply(lambda row: row_category(row) in selected, axis=1)]

        cat_to_ids = {}
        for _, row in df.iterrows():
            category = row_category(row)
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            cat_to_ids.setdefault(category, set()).add(oid)

        all_ids = sorted(set().union(*cat_to_ids.values())) if cat_to_ids else []
        with lock:
            status["total"] = len(all_ids)
            status["done"] = 0
            status["success"] = 0
            status["errors"] = 0
            status["recent_errors"] = []
            status["categories"] = {
                category: {"done": 0, "total": len(ids), "percent": 0, "errors": 0, "recent_errors": []}
                for category, ids in cat_to_ids.items()
            }
            status["phase"] = "running" if all_ids else "finished"
            status["message"] = (
                f"Обновляю цены Onliner: {len(all_ids)} уникальных ID."
                if all_ids else "В выбранных категориях нет товаров с OnlinerID."
            )

        cache = load_cache()
        now = int(now_fn())
        id_to_categories = {}
        for category, ids in cat_to_ids.items():
            for oid in ids:
                id_to_categories.setdefault(oid, []).append(category)

        id_hints = market_id_hints_from_dataframe(df, row_category)

        def _fetch_market_for_refresh(oid):
            hint = id_hints.get(oid) or {}
            return fetch_market_stats(
                oid,
                product_name=str(hint.get("name", "") or ""),
                category_name=str(hint.get("category", "") or ""),
            )

        success_count = 0
        error_count = 0
        done_count = 0

        def _record_result(oid, stats):
            nonlocal done_count, success_count, error_count
            had_values_before = market_stats_has_values(cache.get(oid))
            has_values_now = market_stats_has_values(stats)
            error_reason = str(stats.get("_error_reason", "") or "").strip()
            if has_values_now:
                cache[oid] = {"updated_at": now, **stats}
                success_count += 1
            elif not had_values_before:
                cache[oid] = {"updated_at": now, **stats}
                error_count += 1
            else:
                error_count += 1
            done_count += 1
            with lock:
                status["done"] = done_count
                status["success"] = success_count
                status["errors"] = error_count
                status["message"] = f"Обновляю цены Onliner: {done_count}/{len(all_ids)} уникальных ID."
                for category in id_to_categories.get(oid, []):
                    category_status = status["categories"].get(category)
                    if not category_status:
                        continue
                    category_status["done"] += 1
                    category_status["percent"] = int(round((category_status["done"] / max(category_status["total"], 1)) * 100))
                    if not has_values_now:
                        category_status["errors"] = int(category_status.get("errors", 0)) + 1
                        if error_reason:
                            line = f"{category}: {oid} -> {error_reason}"
                            recent = list(category_status.get("recent_errors", []) or [])
                            recent.append(line)
                            category_status["recent_errors"] = recent[-5:]
                            all_recent = list(status.get("recent_errors", []) or [])
                            all_recent.append(line)
                            status["recent_errors"] = all_recent[-12:]

        executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_oid = {executor.submit(_fetch_market_for_refresh, oid): oid for oid in all_ids}
        pending = set(future_to_oid)
        try:
            idle_timeout = float(idle_timeout_sec or MARKET_REFRESH_IDLE_TIMEOUT_SEC)
            if idle_timeout <= 0:
                idle_timeout = MARKET_REFRESH_IDLE_TIMEOUT_SEC
            while pending:
                done_futures, pending = wait(
                    pending,
                    timeout=idle_timeout,
                    return_when=FIRST_COMPLETED,
                )
                if not done_futures:
                    timeout_reason = f"таймаут обновления цен: нет ответа {idle_timeout:g}с"
                    for future in list(pending):
                        oid = future_to_oid.get(future, "")
                        future.cancel()
                        _record_result(oid, {**empty_market_stats(), "_error": True, "_error_reason": timeout_reason})
                    pending.clear()
                    break
                for future in done_futures:
                    oid = future_to_oid[future]
                    try:
                        stats = future.result()
                    except Exception:
                        stats = {**empty_market_stats(), "_error": True, "_error_reason": "ошибка запроса цен"}
                    _record_result(oid, stats)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        save_cache(cache)
    finally:
        with lock:
            status["running"] = False
            status["phase"] = "finished"
            status["message"] = f"Обновление кэша Onliner завершено: {status.get('done', 0)}/{status.get('total', 0)} ID."
            status["finished_at"] = int(now_fn())


def collect_known_onliner_ids(
    max_ids,
    session_dir=None,
    read_consolidated_df=None,
    load_market_cache=load_onliner_market_cache,
    load_id_cache=None,
):
    ids = []
    try:
        sdir = str(session_dir or "").strip()
        if sdir and callable(read_consolidated_df):
            if has_consolidated_data(sdir):
                df = read_consolidated_df(sdir)
                for _, row in df.iterrows():
                    oid = normalize_onliner_id(row.get("OnlinerID", ""))
                    if oid:
                        ids.append(oid)
    except Exception:
        pass

    cache = load_market_cache()
    if isinstance(cache, dict):
        ids.extend(cache.keys())

    id_cache = load_id_cache() if callable(load_id_cache) else {}
    if isinstance(id_cache, dict):
        for _, record in id_cache.items():
            if not isinstance(record, dict):
                continue
            oid = normalize_onliner_id(record.get("id", ""))
            if oid:
                ids.append(oid)

    out = []
    seen = set()
    for oid in ids:
        if oid and oid not in seen:
            seen.add(oid)
            out.append(oid)
        if len(out) >= int(max_ids):
            break
    return out


def market_id_hints_from_dataframe(df, row_category):
    hints = {}
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid or oid in hints:
            continue
        hints[oid] = {
            "name": str(row.get("Название", "") or ""),
            "category": row_category(row),
        }
    return hints


def market_id_hints_from_session(session_dir, read_consolidated_df, ensure_category_column, row_category):
    try:
        sdir = str(session_dir or "").strip()
        if not sdir:
            return {}
        if not has_consolidated_data(sdir):
            return {}
        df = read_consolidated_df(sdir)
        df = ensure_category_column(df)
        return market_id_hints_from_dataframe(df, row_category)
    except Exception:
        return {}


def auto_market_refresh_once(
    load_settings,
    save_settings,
    collect_known_ids,
    get_last_session_dir,
    get_id_hints,
    fetch_market_stats,
    load_cache=load_onliner_market_cache,
    save_cache=save_onliner_market_cache,
    status=market_refresh_status,
    lock=MARKET_REFRESH_LOCK,
    allowed_hours=AUTO_REFRESH_ALLOWED_HOURS,
    max_workers=MARKET_REFRESH_POOL_WORKERS,
    now_fn=time.time,
):
    try:
        settings = load_settings()
        if not settings.get("enabled"):
            return {"status": "disabled"}

        with lock:
            manual_running = bool(status.get("running"))
        if manual_running:
            return {"status": "manual_running"}

        interval_hours = _coerce_auto_interval_hours(settings.get("interval_hours", 12), allowed_hours)
        now = int(now_fn())
        last_run = int(settings.get("last_run_ts", 0) or 0)
        due = (last_run <= 0) or (now - last_run >= interval_hours * 3600)
        if not due:
            return {"status": "not_due"}

        session_dir = get_last_session_dir()
        ids = collect_known_ids(session_dir=session_dir)
        if not ids:
            settings["last_run_ts"] = now
            settings["last_status"] = "idle"
            settings["last_count"] = 0
            settings["last_message"] = "Нет товаров с OnlinerID для автообновления."
            save_settings(settings)
            return {"status": "idle", "count": 0}

        settings["last_started_ts"] = now
        settings["last_status"] = "running"
        settings["last_message"] = f"Автообновление запущено, товаров: {len(ids)}"
        save_settings(settings)

        cache = load_cache()
        auto_hints = get_id_hints(session_dir)

        def _auto_fetch_market(oid):
            hint = auto_hints.get(oid) or {}
            return fetch_market_stats(
                oid,
                product_name=str(hint.get("name", "") or ""),
                category_name=str(hint.get("category", "") or ""),
            )

        workers = min(max_workers, max(4, len(ids)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_oid = {executor.submit(_auto_fetch_market, oid): oid for oid in ids}
            for future in as_completed(future_to_oid):
                oid = future_to_oid[future]
                try:
                    stats = future.result()
                except Exception:
                    stats = {**empty_market_stats(), "_error": True}
                had_values_before = market_stats_has_values(cache.get(oid))
                has_values_now = market_stats_has_values(stats)
                if has_values_now or not had_values_before:
                    cache[oid] = {"updated_at": now, **stats}
        save_cache(cache)

        done_ts = int(now_fn())
        latest = load_settings()
        latest["last_run_ts"] = done_ts
        latest["last_status"] = "ok"
        latest["last_count"] = len(ids)
        latest["last_message"] = f"Автообновление завершено. Обновлено ID: {len(ids)}"
        save_settings(latest)
        return {"status": "ok", "count": len(ids)}
    except Exception as exc:
        latest = load_settings()
        latest["last_status"] = "error"
        latest["last_message"] = f"Ошибка автообновления: {str(exc)[:160]}"
        save_settings(latest)
        return {"status": "error", "message": str(exc)[:160]}


def auto_market_refresh_loop(
    load_settings,
    save_settings,
    collect_known_ids,
    get_last_session_dir,
    get_id_hints,
    fetch_market_stats,
    load_cache=load_onliner_market_cache,
    save_cache=save_onliner_market_cache,
    status=market_refresh_status,
    lock=MARKET_REFRESH_LOCK,
    allowed_hours=AUTO_REFRESH_ALLOWED_HOURS,
    max_workers=MARKET_REFRESH_POOL_WORKERS,
    poll_sec=AUTO_REFRESH_POLL_SEC,
    now_fn=time.time,
    sleep_fn=time.sleep,
):
    while True:
        auto_market_refresh_once(
            load_settings=load_settings,
            save_settings=save_settings,
            collect_known_ids=collect_known_ids,
            get_last_session_dir=get_last_session_dir,
            get_id_hints=get_id_hints,
            fetch_market_stats=fetch_market_stats,
            load_cache=load_cache,
            save_cache=save_cache,
            status=status,
            lock=lock,
            allowed_hours=allowed_hours,
            max_workers=max_workers,
            now_fn=now_fn,
        )
        sleep_fn(poll_sec)


def _coerce_auto_interval_hours(value, allowed_hours):
    try:
        interval = int(value or 12)
    except Exception:
        interval = 12
    return interval if interval in set(allowed_hours) else 12
