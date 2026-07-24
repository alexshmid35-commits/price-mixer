"""Orchestration for bulk OnlinerID verification."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def run_verify_all_worker(session_dir, dependencies):
    """Verify every eligible OnlinerID and publish incremental status updates."""
    d = dependencies

    try:
        df = d["read_consolidated_df"](session_dir)
        df = d["ensure_category_column"](df)
        df = d["apply_visibility_filter"](df, session_dir)
        if "OnlinerID" not in df.columns:
            d["status_update"]({
                "running": False,
                "state": "done",
                "total": 0,
                "done": 0,
                "matched": 0,
                "mismatched": 0,
                "errors": 0,
                "items": [],
                "report_items": [],
                "finished_at": int(d["clock"]()),
                "message": "В текущем прайсе нет колонки OnlinerID.",
            })
            return

        tasks, skipped_tgpc_pc = d["collect_tasks"](
            df,
            is_tgpc_pc_name=d["is_tgpc_pc_name"],
            require_name=False,
        )
        skip_note = (
            f" (TGPC ПЭВМ пропущено: {skipped_tgpc_pc})"
            if skipped_tgpc_pc
            else ""
        )
        d["status_update"]({
            "running": True,
            "state": "running",
            "total": len(tasks),
            "done": 0,
            "matched": 0,
            "mismatched": 0,
            "errors": 0,
            "items": [],
            "report_items": [],
            "message": f"Проверка ID запущена{skip_note}.",
        })

        if not tasks:
            d["status_update"]({
                "running": False,
                "state": "done",
                "finished_at": int(d["clock"]()),
                "message": "В текущем прайсе нет товаров с OnlinerID.",
            })
            return

        result_items = []
        report_items = []
        matched = 0
        mismatched = 0
        errors = 0
        settings = d["load_app_settings"]()
        product_cache = d["load_product_cache"]()
        manual_bindings = d["load_manual_id_bindings"]()
        product_info_results = {}
        product_info_events = {}
        product_info_lock = threading.Lock()
        workers = max(
            1,
            min(d["get_max_workers"](default=8), 10, len(tasks)),
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    d["verify_one"],
                    row_idx,
                    row,
                    settings,
                    product_cache,
                    manual_bindings,
                    product_info_results,
                    product_info_events,
                    product_info_lock,
                ): row_idx
                for row_idx, row in tasks
            }
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception:
                    item = None
                    errors += 1
                else:
                    if item is not None:
                        report_items.append(item)
                        if item.get("needs_review"):
                            mismatched += 1
                            result_items.append(item)
                        else:
                            matched += 1
                finally:
                    with d["status_lock"]:
                        done = int(d["status"].get("done", 0) or 0) + 1
                    d["status_update"]({
                        "done": done,
                        "matched": int(matched),
                        "mismatched": int(mismatched),
                        "errors": int(errors),
                    })

        result_items, report_items = d["sort_result_items"](
            result_items,
            report_items,
        )
        d["status_update"]({
            "running": False,
            "state": "done",
            "matched": int(matched),
            "mismatched": int(mismatched),
            "errors": int(errors),
            "items": result_items,
            "report_items": report_items,
            "finished_at": int(d["clock"]()),
            "message": (
                f"Проверено ID: {len(tasks)}. "
                f"Несовпадений: {mismatched}.{skip_note}"
            ),
        })
    except Exception as exc:
        d["status_update"]({
            "running": False,
            "state": "error",
            "finished_at": int(d["clock"]()),
            "message": "Ошибка проверки ID: " + str(exc)[:180],
        })
