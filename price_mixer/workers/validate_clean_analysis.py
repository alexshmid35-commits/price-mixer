"""Network analysis worker for the visible validate-clean workflow."""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from price_mixer.services.id_validation import validate_clean_api_row
from price_mixer.state_store import load_dict, save_json_atomic


def _fetch_product_name(oid, hard_timeout=9):
    request = urllib.request.Request(
        f"https://catalog.api.onliner.by/products/{oid}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=min(max(float(hard_timeout), 1), 8)) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace")) or {}
        name = str(data.get("full_name") or data.get("name") or "").strip()
        url = str(data.get("html_url") or "").strip()
        return (name, url, "ok" if name else "empty_payload")
    except urllib.error.HTTPError as exc:
        return ("", "", "not_found" if exc.code == 404 else "http_error")
    except Exception:
        return ("", "", "error")


def _write_status(path, job_id, state, **updates):
    state.update(updates)
    state.update({"job_id": job_id, "running": True, "updated_at": time.time()})
    save_json_atomic(path, state)


def run_analysis(payload, status_path, job_id):
    import app as app_module

    tasks = list(payload.get("tasks", []) or [])
    total = len(tasks)
    max_workers = max(1, min(int(payload.get("max_workers", 8) or 8), 12, total or 1))
    product_cache = app_module.load_onliner_product_cache()
    product_cache_lock = threading.Lock()
    fetch_results = {}
    fetch_events = {}
    fetch_lock = threading.Lock()
    state = {
        "total": total,
        "done": 0,
        "confirmed": 0,
        "cleared": 0,
        "skipped_api": 0,
        "errors": 0,
        "message": f"Фаза 1: проверяю {total} товаров в отдельном процессе...",
    }
    _write_status(status_path, job_id, state)

    def fetch_once(oid, hard_timeout=9):
        with fetch_lock:
            if oid in fetch_results:
                return fetch_results[oid]
            event = fetch_events.get(oid)
            owns_request = event is None
            if owns_request:
                event = threading.Event()
                fetch_events[oid] = event
        if owns_request:
            result = _fetch_product_name(oid, hard_timeout=hard_timeout)
            with fetch_lock:
                fetch_results[oid] = result
                fetch_events.pop(oid, None)
                event.set()
            return result
        event.wait(timeout=30)
        with fetch_lock:
            return fetch_results.get(oid, ("", "", "error"))

    def analyze(task):
        row = {
            "Название": str(task.get("name", "")),
            "OnlinerID": str(task.get("onliner_id", "")),
            "Поставщик": str(task.get("supplier", "")),
        }
        return validate_clean_api_row(
            int(task.get("row_idx", 0)),
            row,
            product_cache=product_cache,
            product_cache_ttl=int(payload.get("product_cache_ttl", 0) or 0),
            fetch_product_name=fetch_once,
            is_manually_confirmed_id=lambda *_args: bool(task.get("manual_confirmed")),
            calc_name_match=app_module.calc_name_match,
            clear_threshold=float(payload.get("clear_threshold", 0.65) or 0.65),
            hard_timeout=9,
            cache_lock=product_cache_lock,
        )

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                result = None
                state["errors"] += 1
            state["done"] += 1
            if result is not None:
                result["supplier"] = str(futures[future].get("supplier", ""))
                results.append(result)
                if result.get("record_confirm"):
                    state["confirmed"] += 1
                elif result.get("mutate_df_clear"):
                    state["cleared"] += 1
                else:
                    state["skipped_api"] += 1
            if state["done"] == total or state["done"] % 10 == 0:
                _write_status(
                    status_path,
                    job_id,
                    state,
                    message=f"Фаза 1: проверено {state['done']}/{total}.",
                )

    clear_names = sorted({str(item.get("name", "")).strip() for item in results if item.get("mutate_df_clear")})
    candidate_map = {}
    if clear_names:
        _write_status(
            status_path,
            job_id,
            state,
            message=f"Фаза 2: ищу кандидатов для {len(clear_names)} товаров...",
        )

        def find_candidates(name):
            try:
                return app_module.search_onliner_candidates(
                    name,
                    category_name="",
                    query="",
                    limit=min(int(payload.get("limit_candidates", 80) or 80), 10),
                    max_queries=3,
                    timeout_sec=6,
                )
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=min(6, len(clear_names))) as executor:
            future_names = {executor.submit(find_candidates, name): name for name in clear_names}
            for future in as_completed(future_names):
                candidate_map[future_names[future]] = future.result()

    _write_status(status_path, job_id, state, message="Проверка завершена. Применяю актуальные результаты...")
    return {
        "job_id": job_id,
        "results": results,
        "candidate_map": candidate_map,
        "errors": int(state["errors"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze validate-clean API tasks")
    parser.add_argument("--input", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    status_path = Path(args.status)
    try:
        payload = load_dict(Path(args.input))
        if str(payload.get("job_id", "")) != args.job_id:
            raise RuntimeError("validate-clean job id mismatch")
        result = run_analysis(payload, status_path, args.job_id)
        save_json_atomic(Path(args.result), result)
        return 0
    except Exception as exc:
        save_json_atomic(status_path, {
            "job_id": args.job_id,
            "running": False,
            "state": "error",
            "message": f"Ошибка отдельного процесса проверки ID: {exc}",
            "updated_at": time.time(),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
