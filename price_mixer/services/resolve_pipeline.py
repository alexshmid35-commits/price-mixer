"""Onliner URL resolve orchestration helpers."""

from __future__ import annotations

from pathlib import Path


def make_resolve_status():
    return {"running": False, "resolved": 0, "total": 0, "cached": 0}


def resolve_status_snapshot(status):
    return dict(status or make_resolve_status())


def start_resolve_payload(
    status,
    *,
    session_dir,
    has_consolidated_session_file,
    read_consolidated_json_fast_df,
    load_url_cache,
    resolve_onliner_urls,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    thread_factory,
):
    if status.get("running"):
        return {"status": "already_running"}

    if not session_dir:
        return {"status": "error", "message": "No session"}
    session_dir = Path(session_dir)

    if not has_consolidated_session_file(session_dir):
        return {"status": "error", "message": "No data"}

    df = read_consolidated_json_fast_df(session_dir)

    id_to_name = {}
    for _, row in df.iterrows():
        oid = row.get("OnlinerID")
        name = row.get("Название", "")
        if oid and str(oid).strip() and str(oid) != "nan":
            id_to_name[str(oid)] = name

    all_ids = list(id_to_name.keys())
    cache = load_url_cache()
    uncached = [oid for oid in all_ids if oid not in cache]

    status.clear()
    status.update({
        "running": True,
        "resolved": 0,
        "total": len(uncached),
        "cached": len(cache),
    })

    def _run_resolve():
        try:
            def progress(done, total):
                status["resolved"] = done
                status["cached"] = len(cache)

            resolve_onliner_urls(
                uncached,
                cache=cache,
                max_workers=5,
                progress_callback=progress,
                id_to_name=id_to_name,
            )
            status["resolved"] = status["total"]
            status["cached"] = len(cache)

            df_current = read_consolidated_df(session_dir)
            for i, row in df_current.iterrows():
                oid = row.get("OnlinerID")
                if oid and str(oid) in cache:
                    df_current.at[i, "Ссылка"] = cache.get(str(oid), "")
            write_consolidated_df(session_dir, df_current)
            write_consolidated_json(df_current, session_dir / "consolidated.json")
        finally:
            status["running"] = False

    thread_factory(_run_resolve)

    return {"status": "started", "total": len(uncached)}
