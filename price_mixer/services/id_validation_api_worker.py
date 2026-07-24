"""Orchestration for the isolated API validate/clean worker."""

from __future__ import annotations


def run_api_validation_worker(session_dir, dependencies):
    """Analyze API responses outside Flask and atomically apply unchanged rows."""
    d = dependencies
    clear_threshold = float(d.get("clear_threshold", 0.65))

    try:
        with d["mutation_lock"]:
            df = d["read_consolidated_df"](session_dir)
            df = d["ensure_category_column"](df)
            if "OnlinerID" not in df.columns:
                d["progress_update"](d["build_no_column_state"]())
                return

            manual_bindings = d["load_manual_id_bindings"]()
            tasks, _skipped_tgpc_pc = d["collect_tasks"](
                df,
                is_tgpc_pc_name=d["is_tgpc_pc_name"],
                require_name=True,
            )
            app_settings = d["load_app_settings"]()
            no_id_cfg = app_settings.get("no_id_search") or {}
            limit_cands = max(
                10,
                min(int(no_id_cfg.get("max_candidates", 80) or 80), 80),
            )
            task_payload = []
            for row_idx, row in tasks:
                name = str(row.get("Название", "")).strip()
                onliner_id = d["normalize_onliner_id"](row.get("OnlinerID", ""))
                supplier = str(row.get("Поставщик", "")).strip()
                manual_confirmed = d["is_manually_confirmed_id"](
                    name,
                    onliner_id,
                    supplier_name=supplier,
                    load_bindings=lambda: manual_bindings,
                    normalize_name_key_func=d["normalize_name_key"],
                )
                task_payload.append({
                    "row_idx": int(row_idx),
                    "name": name,
                    "onliner_id": onliner_id,
                    "supplier": supplier,
                    "manual_confirmed": bool(manual_confirmed),
                })

        d["progress_update"](d["build_prepare_state"]("api", len(task_payload)))
        if not task_payload:
            d["progress_update"](d["build_no_tasks_state"]("api"))
            return

        analysis = d["analysis_runner"].run(
            session_dir,
            {
                "tasks": task_payload,
                "clear_threshold": clear_threshold,
                "product_cache_ttl": d["product_cache_ttl"],
                "limit_candidates": limit_cands,
                "max_workers": max(1, min(d["get_max_workers"](default=8), 10)),
            },
            progress_update=d["progress_update"],
        )
        d["raise_if_cancelled"]()

        with d["mutation_lock"]:
            current_df = d["ensure_category_column"](
                d["read_consolidated_df"](session_dir)
            )
            current_bindings = d["load_manual_id_bindings"]()
            review_queue = d["load_review_queue"]()
            confirmed_rows = []
            skipped_rows = []
            cleared_items = []
            journal_changes = []
            confirmed = 0
            skipped = 0
            apply_errors = 0

            results = sorted(
                analysis.get("results", []) or [],
                key=lambda item: int(item.get("row_idx", 0)),
            )
            for result in results:
                d["raise_if_cancelled"]()
                try:
                    row_idx = int(result.get("row_idx", 0))
                    if row_idx not in current_df.index:
                        raise KeyError("row disappeared")

                    current_row = current_df.loc[row_idx]
                    current_id = d["normalize_onliner_id"](
                        current_row.get("OnlinerID", "")
                    )
                    current_name = str(current_row.get("Название", "")).strip()
                    source_id = d["normalize_onliner_id"](
                        result.get("onliner_id", "")
                    )
                    source_name = str(result.get("name", "")).strip()
                    if current_id != source_id or current_name != source_name:
                        skipped += 1
                        skipped_rows.append({
                            "name": str(result.get("name", "")),
                            "onliner_id": str(result.get("onliner_id", "")),
                            "reason": "state_changed_during_validation",
                        })
                        continue

                    supplier = str(current_row.get("Поставщик", "")).strip()
                    deltas = d["apply_api_result"](
                        current_df,
                        result,
                        d["normalize_name_key"](current_name),
                        current_bindings,
                        confirmed_rows,
                        skipped_rows,
                        cleared_items,
                        journal_changes,
                        supplier_name=supplier,
                        clear_value=d["clear_value"],
                    )
                    confirmed += int(deltas.get("confirmed", 0) or 0)
                    skipped += int(deltas.get("skipped_api", 0) or 0)
                except Exception:
                    apply_errors += 1

            candidate_map = analysis.get("candidate_map", {}) or {}
            queued = d["populate_review_queue"](
                cleared_items,
                review_queue,
                lambda name, **_kwargs: list(
                    candidate_map.get(str(name).strip(), []) or []
                ),
                limit_cands,
                progress_update=d["progress_update"],
                should_cancel=d["cancel_requested"],
            )
            d["raise_if_cancelled"]()
            d["save_results"](
                mode="api",
                session_dir=session_dir,
                df=current_df,
                manual_bindings=current_bindings,
                review_queue=review_queue,
                journal_changes=journal_changes,
                save_manual_id_bindings=d["save_manual_id_bindings"],
                save_review_queue=d["save_review_queue"],
                append_id_change_journal=d["append_id_change_journal"],
                write_consolidated_df=d["write_consolidated_df"],
                write_consolidated_json=d["write_consolidated_json"],
            )

        d["progress_update"](d["build_finish_state"](
            mode="api",
            total=len(task_payload),
            confirmed=confirmed,
            cleared_items=cleared_items,
            skipped=skipped,
            queued=queued,
            errors=int(analysis.get("errors", 0) or 0) + apply_errors,
            confirmed_rows=confirmed_rows,
            skipped_rows=skipped_rows,
        ))
    except d["cancelled_error"]:
        d["progress_update"](d["build_cancelled_state"]("api"))
    except Exception as exc:
        d["progress_update"](d["build_error_state"]("api", exc))
