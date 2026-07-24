"""Orchestration for the local-database validate/clean worker."""

from __future__ import annotations


def run_db_validation_worker(session_dir, dependencies):
    """Run local ID validation and commit only after the full job succeeds."""
    d = dependencies
    status = d["status"]
    lock = d["lock"]
    clear_threshold = float(d.get("clear_threshold", 0.65))

    try:
        df = d["read_consolidated_df"](session_dir)
        df = d["ensure_category_column"](df)
        if "OnlinerID" not in df.columns:
            with lock:
                status.update(d["build_no_column_state"]())
            return

        manual_bindings = d["load_manual_id_bindings"]()
        review_queue = d["load_review_queue"]()
        tasks, _skipped_tgpc_pc = d["collect_tasks"](
            df,
            is_tgpc_pc_name=d["is_tgpc_pc_name"],
            require_name=True,
        )

        with lock:
            status.update(d["build_prepare_state"]("db", len(tasks)))

        if not tasks:
            with lock:
                status.update(d["build_no_tasks_state"]("db"))
            return

        state = d["run_db_tasks"](
            df,
            tasks,
            manual_bindings,
            d["is_manually_confirmed_id"],
            d["db_get_product_by_id"],
            d["db_find_exact_id_for_name"],
            d["calc_name_match"],
            d["normalize_name_key"],
            progress_update=d["progress_update"],
            log=d["log"],
            clear_threshold=clear_threshold,
            clear_value=d["clear_value"],
            should_cancel=d["cancel_requested"],
        )

        d["raise_if_cancelled"]()
        queued = d["populate_review_queue"](
            state["cleared_items"],
            review_queue,
            d["db_find_top_candidates"],
            progress_update=d["progress_update"],
            should_cancel=d["cancel_requested"],
        )

        d["raise_if_cancelled"]()
        d["save_results"](
            mode="db",
            session_dir=session_dir,
            df=df,
            manual_bindings=manual_bindings,
            review_queue=review_queue,
            journal_changes=state["journal_changes"],
            save_manual_id_bindings=d["save_manual_id_bindings"],
            save_review_queue=d["save_review_queue"],
            append_id_change_journal=d["append_id_change_journal"],
            write_consolidated_df=d["write_consolidated_df"],
            write_consolidated_json=d["write_consolidated_json"],
        )

        with lock:
            status.update(d["build_finish_state"](
                mode="db",
                total=len(tasks),
                confirmed=state["confirmed"],
                cleared_items=state["cleared_items"],
                skipped=state["skipped"],
                queued=queued,
                errors=state["errors"],
                confirmed_rows=state["confirmed_rows"],
                skipped_rows=state["skipped_rows"],
            ))
    except d["cancelled_error"]:
        with lock:
            status.update(d["build_cancelled_state"]("db"))
    except Exception as exc:
        with lock:
            status.update(d["build_error_state"]("db", exc))
