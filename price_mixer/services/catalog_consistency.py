"""All_Catalog ID reconciliation helpers."""

from pathlib import Path

import pandas as pd


EMPTY_CONSISTENCY_SUMMARY = {
    "checked": 0,
    "set_from_catalog": 0,
    "corrected_conflicts": 0,
    "cleared_unverified": 0,
    "report_rows": 0,
}


def reconcile_ids_from_catalog(df, lookup_id_from_catalog_sheet=None, normalize_onliner_id=None):
    if "OnlinerID" not in df.columns:
        return 0
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    lookup_id_from_catalog_sheet = lookup_id_from_catalog_sheet or (lambda name: ("", ""))
    normalize_onliner_id = normalize_onliner_id or (lambda value: str(value or "").strip())

    corrected = 0
    for index, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)
        if not catalog_id:
            continue
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        if current_id != str(catalog_id):
            df.at[index, "OnlinerID"] = str(catalog_id)
            if catalog_url:
                df.at[index, "Ссылка"] = catalog_url
            corrected += 1
        elif catalog_url and not str(row.get("Ссылка", "")).strip():
            df.at[index, "Ссылка"] = catalog_url
    return corrected


def enforce_catalog_consistency(
    df,
    session_dir=None,
    lookup_id_from_catalog_sheet=None,
    normalize_onliner_id=None,
    get_article_from_name=None,
    save_summary=None,
):
    if "OnlinerID" not in df.columns:
        return dict(EMPTY_CONSISTENCY_SUMMARY)

    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    lookup_id_from_catalog_sheet = lookup_id_from_catalog_sheet or (lambda name: ("", ""))
    normalize_onliner_id = normalize_onliner_id or (lambda value: str(value or "").strip())
    get_article_from_name = get_article_from_name or (lambda name: "")

    checked = 0
    set_from_catalog = 0
    corrected_conflicts = 0
    cleared_unverified = 0
    report_rows = []

    for index, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        checked += 1
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        article = get_article_from_name(name)
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)

        if catalog_id:
            catalog_id = str(catalog_id).strip()
            if not current_id:
                df.at[index, "OnlinerID"] = catalog_id
                set_from_catalog += 1
            elif current_id != catalog_id:
                report_rows.append(_report_row(index, row, name, article, current_id, catalog_id, "corrected_to_catalog"))
                df.at[index, "OnlinerID"] = catalog_id
                corrected_conflicts += 1
            if catalog_url:
                df.at[index, "Ссылка"] = str(catalog_url).strip()
            continue

        if article and current_id:
            report_rows.append(_report_row(index, row, name, article, current_id, "", "cleared_unverified_no_catalog_match"))
            df.at[index, "OnlinerID"] = ""
            df.at[index, "Ссылка"] = ""
            cleared_unverified += 1

    summary = {
        "checked": checked,
        "set_from_catalog": set_from_catalog,
        "corrected_conflicts": corrected_conflicts,
        "cleared_unverified": cleared_unverified,
        "report_rows": len(report_rows),
    }
    if session_dir:
        _write_quality_report(session_dir, report_rows, summary, save_summary)
    return summary


def _report_row(index, row, name, article, current_id, catalog_id, action):
    return {
        "row": int(index) + 2,
        "supplier": str(row.get("Поставщик", "")).strip(),
        "name": name,
        "article": article,
        "current_id": current_id,
        "catalog_id": catalog_id,
        "action": action,
    }


def _write_quality_report(session_dir, report_rows, summary, save_summary):
    session_dir = Path(session_dir)
    report_df = pd.DataFrame(report_rows)
    report_path = session_dir / "id_quality_report.csv"
    report_df.to_csv(report_path, index=False, encoding="utf-8-sig")
    payload = dict(summary)
    payload["report_file"] = str(report_path)
    if callable(save_summary):
        save_summary(session_dir / "id_quality_report.json", payload)
