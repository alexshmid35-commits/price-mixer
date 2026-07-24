"""Export preparation, Google Sheets payload, and pre-export quality helpers."""

import math
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from price_mixer.logging_config import get_logger
from price_mixer.services.product_normalization import normalize_name_key, normalize_onliner_id

GOOGLE_SHEETS_HTTP_TIMEOUT = (10, 60)
LOGGER = get_logger("price_mixer.export")

EXPORT_TARGET_LAYOUT = (
    ("", ()),
    ("Название", ("наименование", "название")),
    ("Цена", ("опт цена", "лучшая цена", "цена")),
    ("Поставщик", ("поставщик",)),
    ("Гарантия", ("гарантия",)),
    ("Дней доставки", ("дней доставки", "дни доставки", "доставка дней", "срок поставки")),
    ("РРЦ", ("ррц",)),
    ("Цена без скидки", ("цена без скидки",)),
    ("OnlinerID", ("onlinerid", "onliner id")),
)


def parse_google_spreadsheet_id(url_or_id):
    text = str(url_or_id or "").strip()
    if not text:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1).strip()
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", text):
        return text
    return ""


def resolve_service_account_json_path(raw, base_dir=None, cwd=None):
    raw = str(raw or "").strip().strip('"').strip("'").strip("\u200b").strip()
    raw = os.path.expanduser(raw)
    if not raw:
        return None, "В настройках пустое поле пути к JSON — введите путь и нажмите «Сохранить настройки»."

    candidates = []
    path = Path(raw)
    if path.is_absolute():
        candidates.append(path)
    else:
        if base_dir is not None:
            candidates.append(Path(base_dir) / raw)
        candidates.append(Path(cwd) / raw if cwd is not None else Path.cwd() / raw)

    tried = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        tried.append(key)
        if resolved.is_file():
            return resolved, ""
    return None, "Файл не найден. Проверьте путь и что настройки сохранены. Искали: " + " · ".join(tried)


def prepare_consolidated_for_export(
    session_dir,
    settings,
    read_consolidated_df,
    apply_visibility_filter,
    apply_keep_lowest_price_per_onliner_id=None,
    apply_duplicate_id_filter=None,
    apply_only_pc_filter=None,
):
    export_cfg = (settings or {}).get("export", {})
    include_without_id = bool(export_cfg.get("include_without_id", True))
    keep_lowest_id_price = bool(export_cfg.get("keep_lowest_price_per_onliner_id", False))
    exclude_category_prefixes = _normalize_prefixes(export_cfg.get("exclude_category_prefixes", []))
    exclude_name_contains = _normalize_contains_patterns(export_cfg.get("exclude_name_contains", []))
    allowed_categories = _normalize_allowed_categories(export_cfg.get("allowed_categories", []))
    base_name = str(export_cfg.get("price_name", "consolidated_price")).strip() or "consolidated_price"
    exclude_duplicate_id_suppliers = export_cfg.get("exclude_duplicate_id_suppliers", [])
    only_pc_suppliers = export_cfg.get("only_pc_suppliers", [])
    only_pc_price_name = str(export_cfg.get("only_pc_price_name", "N-tech_TGPC_Beznal")).strip() or "N-tech_TGPC_Beznal"
    download_name = f"{base_name}.xlsx"

    sd = str(session_dir or "").strip()
    if not sd:
        return None, download_name
    session_path = Path(sd)
    if not (session_path / "consolidated_price.xlsx").exists() and not (session_path / "consolidated.json").exists():
        return None, download_name

    filtered = read_consolidated_df(sd)
    filtered = apply_visibility_filter(filtered, sd)
    if exclude_category_prefixes and "Категория" in filtered.columns:
        category_text = filtered["Категория"].fillna("").astype(str).str.strip()
        mask = ~category_text.apply(lambda value: _starts_with_any_prefix(value, exclude_category_prefixes))
        filtered = filtered[mask].copy()
    if allowed_categories and "Категория" in filtered.columns:
        category_text = filtered["Категория"].fillna("").astype(str).str.strip()
        mask = category_text.apply(lambda value: value.casefold() in allowed_categories)
        filtered = filtered[mask].copy()
    if exclude_name_contains and "Название" in filtered.columns:
        name_text = filtered["Название"].fillna("").astype(str)
        mask = ~name_text.apply(lambda value: _contains_any_pattern(value, exclude_name_contains))
        filtered = filtered[mask].copy()
    if not include_without_id and "OnlinerID" in filtered.columns:
        mask = filtered["OnlinerID"].apply(lambda value: bool(normalize_onliner_id(value)))
        filtered = filtered[mask].copy()
    if keep_lowest_id_price and callable(apply_keep_lowest_price_per_onliner_id):
        filtered = apply_keep_lowest_price_per_onliner_id(filtered)
    if callable(apply_duplicate_id_filter):
        filtered = apply_duplicate_id_filter(filtered, exclude_duplicate_id_suppliers)

    before_only_pc_len = len(filtered)
    if callable(apply_only_pc_filter):
        filtered = apply_only_pc_filter(filtered, only_pc_suppliers)
    if only_pc_suppliers and len(filtered) != before_only_pc_len:
        download_name = f"{only_pc_price_name}.xlsx"
    return filtered, download_name


def _normalize_prefixes(value):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n;]+", str(value or ""))
    prefixes = []
    for item in raw_items:
        prefix = str(item or "").strip().casefold()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _starts_with_any_prefix(value, prefixes):
    text = str(value or "").strip().casefold()
    return bool(text) and any(text.startswith(prefix) for prefix in prefixes)


def _normalize_contains_patterns(value):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n;]+", str(value or ""))
    patterns = []
    for item in raw_items:
        pattern = str(item or "").strip().casefold()
        if pattern and pattern not in patterns:
            patterns.append(pattern)
    return patterns


def _contains_any_pattern(value, patterns):
    text = str(value or "").strip().casefold()
    return bool(text) and any(pattern in text for pattern in patterns)


def _normalize_allowed_categories(value):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n;]+", str(value or ""))
    return {
        str(item or "").strip().casefold()
        for item in raw_items
        if str(item or "").strip()
    }


def export_column_is_onliner_id(name):
    raw = str(name or "").strip().lower().replace("\xa0", " ")
    compact = re.sub(r"[\s_]+", "", raw)
    return compact == "onlinerid" or ("onliner" in compact and compact.endswith("id"))


def normalize_export_column_name(name):
    raw = str(name or "").strip().lower().replace("\xa0", " ")
    return re.sub(r"\s+", " ", raw)


def export_column_is_money(name):
    normalized = normalize_export_column_name(name)
    if not normalized:
        return False
    money_cols = {
        "цена",
        "лучшая цена",
        "ррц",
        "цена без скидки",
        "цена без ндс",
        "цена с ндс",
    }
    return normalized in money_cols or ("цена" in normalized and "ссылка" not in normalized)


def coerce_money_value(value):
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float, np.integer, np.floating)):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ""
        return round(numeric, 2)
    text = str(value).strip()
    if not text:
        return ""
    normalized = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        numeric = float(normalized)
        if not math.isfinite(numeric):
            return ""
        return round(numeric, 2)
    except Exception:
        return str(value)


def dataframe_to_sheet_values(df):
    if df is None or df.empty:
        return []
    original_cols = list(df.columns)
    normalized_map = {normalize_export_column_name(col): col for col in original_cols}

    resolved_columns = []
    for _header_name, aliases in EXPORT_TARGET_LAYOUT:
        picked = None
        for alias in aliases:
            if alias in normalized_map:
                picked = normalized_map[alias]
                break
        resolved_columns.append(picked)

    rows = [[item[0] for item in EXPORT_TARGET_LAYOUT]]
    for _, row in df.iterrows():
        line = []
        for idx, src_col in enumerate(resolved_columns):
            if idx == 0 or not src_col:
                line.append("")
                continue
            value = row.get(src_col)
            if export_column_is_onliner_id(src_col):
                line.append(normalize_onliner_id(value))
            elif export_column_is_money(src_col):
                line.append(coerce_money_value(value))
            else:
                line.append(_sheet_text_value(value))
        rows.append(line)
    return rows


def dataframe_to_export_dataframe(df):
    """Return the exact fixed layout shared by Excel and Google Sheets exports."""
    headers = [header for header, _aliases in EXPORT_TARGET_LAYOUT]
    values = dataframe_to_sheet_values(df)
    if not values:
        return pd.DataFrame(columns=headers)
    return pd.DataFrame(values[1:], columns=values[0])


def google_sheet_money_column_ranges(row_count, rowcol_to_a1):
    if row_count <= 0:
        return []
    money_columns = (3, 7, 8)
    return [
        f"{rowcol_to_a1(2, col)}:{rowcol_to_a1(row_count + 1, col)}"
        for col in money_columns
    ]


def build_preexport_quality_payload(df):
    if df.empty:
        return {
            "status": "ok",
            "checked": 0,
            "missing_id_count": 0,
            "suspicious_price_count": 0,
            "duplicate_count": 0,
            "missing_id_samples": [],
            "suspicious_price_samples": [],
            "duplicate_samples": [],
        }

    missing_id_samples = []
    missing_id_count = 0
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            continue
        missing_id_count += 1
        if len(missing_id_samples) < 8:
            missing_id_samples.append(f"[{str(row.get('Категория', '')).strip()}] {str(row.get('Название', '')).strip()}")

    suspicious_price_count, suspicious_price_samples = _preexport_price_issues(df)
    duplicate_count, duplicate_samples = _preexport_duplicate_issues(df)

    return {
        "status": "ok",
        "checked": int(len(df)),
        "missing_id_count": int(missing_id_count),
        "suspicious_price_count": int(suspicious_price_count),
        "duplicate_count": int(duplicate_count),
        "missing_id_samples": missing_id_samples,
        "suspicious_price_samples": suspicious_price_samples,
        "duplicate_samples": duplicate_samples,
    }


def export_google_sheets_payload(
    session_dir,
    settings,
    prepare_consolidated_for_export,
    resolve_service_account_json_path_func=resolve_service_account_json_path,
    dataframe_to_sheet_values_func=dataframe_to_sheet_values,
    gspread_module=None,
    rowcol_to_a1_func=None,
    api_error_cls=None,
    spreadsheet_not_found_cls=None,
    worksheet_not_found_cls=None,
):
    started_at = time.monotonic()

    def log_step(step, **extra):
        parts = [f"[google_export] {step}", f"elapsed={time.monotonic() - started_at:.2f}s"]
        for key, value in extra.items():
            parts.append(f"{key}={value}")
        LOGGER.info(" ".join(parts))

    log_step("start")
    runtime = _resolve_gspread_runtime(
        gspread_module,
        rowcol_to_a1_func,
        api_error_cls,
        spreadsheet_not_found_cls,
        worksheet_not_found_cls,
    )
    if runtime[0] is None:
        return {"status": "error", "message": "Не установлен пакет gspread."}, 500

    gspread, rowcol_to_a1, api_error, spreadsheet_not_found, worksheet_not_found = runtime

    def _service_account_client():
        try:
            from gspread.http_client import HTTPClient

            class TimeoutHTTPClient(HTTPClient):
                def __init__(self, auth, session=None):
                    super().__init__(auth, session=session)
                    self.timeout = GOOGLE_SHEETS_HTTP_TIMEOUT

            return gspread.service_account(filename=str(sa_path), http_client=TimeoutHTTPClient)
        except TypeError:
            return gspread.service_account(filename=str(sa_path))

    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400

    ex = (settings or {}).get("export", {})
    sheet_ref = str(ex.get("google_sheets_spreadsheet_url_or_id", "") or "").strip()
    tab = str(ex.get("google_sheets_tab", "Price") or "Price").strip() or "Price"
    sa_raw = str(ex.get("google_sheets_service_account_json", "") or "").strip()
    sid = parse_google_spreadsheet_id(sheet_ref)
    if not sid:
        return {
            "status": "error",
            "message": "В настройках не указана ссылка или ID таблицы (поле «Google Таблица — ссылка или ID»).",
        }, 400

    sa_path, sa_err = resolve_service_account_json_path_func(sa_raw)
    if not sa_path:
        return {
            "status": "error",
            "message": sa_err or "Укажите путь к JSON сервисного аккаунта и убедитесь, что файл существует.",
        }, 400

    log_step("prepare_export_dataframe_start")
    filtered, _ = prepare_consolidated_for_export(session_dir)
    if filtered is None:
        return {"status": "error", "message": "Нет сводного прайса (consolidated_price.xlsx) в текущей сессии."}, 400
    if filtered.empty:
        return {"status": "error", "message": "Сводный прайс пуст после применения фильтров выгрузки."}, 400

    log_step("prepare_export_dataframe_done", rows=len(filtered), cols=len(filtered.columns))
    values = dataframe_to_sheet_values_func(filtered)
    log_step("build_sheet_values_done", rows=len(values) - 1 if values else 0, cols=len(values[0]) if values else 0)
    if len(values) < 2:
        return {"status": "error", "message": "Нет строк данных для выгрузки."}, 400

    try:
        log_step("authorize_google", timeout=GOOGLE_SHEETS_HTTP_TIMEOUT)
        gc = _service_account_client()
        log_step("open_google_sheet", tab=tab)
        sh = gc.open_by_key(sid)
        log_step("open_google_sheet_done", tab=tab)
    except spreadsheet_not_found:
        return {
            "status": "error",
            "message": "Таблица не найдена. Проверьте ID/ссылку и что файл расшарен на e-mail сервисного аккаунта из JSON (доступ «Редактор»).",
        }, 400
    except api_error as exc:
        return {"status": "error", "message": f"Google Sheets API: {exc}"}, 400
    except Exception as exc:
        return {"status": "error", "message": f"Не удалось открыть таблицу: {exc}"}, 400

    previous_ws = None
    staging_ws = None
    try:
        log_step("open_worksheet", tab=tab)
        previous_ws = sh.worksheet(tab)
    except worksheet_not_found:
        previous_ws = None

    if previous_ws is None:
        ncols0 = max(len(values[0]), 26)
        nrows0 = max(len(values) + 200, 1000)
        log_step("create_worksheet", rows=nrows0, cols=ncols0)
        ws = sh.add_worksheet(title=tab[:99], rows=nrows0, cols=ncols0)
    else:
        ncols0 = max(len(values[0]), 26)
        nrows0 = max(len(values) + 200, 1000)
        staging_title = f"__price_mixer_tmp_{int(time.time_ns())}"[:99]
        log_step("create_staging_worksheet", rows=nrows0, cols=ncols0)
        staging_ws = sh.add_worksheet(title=staging_title, rows=nrows0, cols=ncols0)
        ws = staging_ws

    ncols = len(values[0])
    nvals = len(values)
    pad_rows = max(nvals + 200, 1000)
    pad_cols = max(ncols + 2, 26)
    try:
        cur_r = int(ws.row_count)
        cur_c = int(ws.col_count)
    except Exception:
        cur_r, cur_c = pad_rows, pad_cols
    if cur_r < pad_rows or cur_c < pad_cols:
        try:
            log_step("resize_worksheet", rows=max(pad_rows, cur_r), cols=max(pad_cols, cur_c))
            ws.resize(rows=max(pad_rows, cur_r), cols=max(pad_cols, cur_c))
        except api_error as exc:
            return {"status": "error", "message": f"Не удалось расширить лист под данные ({nvals} строк): {exc}"}, 500
        except Exception as exc:
            return {"status": "error", "message": f"Не удалось расширить лист под данные: {exc}"}, 500

    batch = 4000
    try:
        for i in range(0, len(values), batch):
            chunk = values[i : i + batch]
            top = i + 1
            bottom = i + len(chunk)
            rng = f"{rowcol_to_a1(top, 1)}:{rowcol_to_a1(bottom, ncols)}"
            log_step("write_batch", range=rng, rows=len(chunk))
            ws.update(chunk, rng, value_input_option="USER_ENTERED")
    except api_error as exc:
        _delete_worksheet_quietly(sh, staging_ws)
        return {"status": "error", "message": f"Ошибка записи в лист: {exc}"}, 500
    except Exception as exc:
        _delete_worksheet_quietly(sh, staging_ws)
        return {"status": "error", "message": f"Ошибка записи в лист: {exc}"}, 500

    try:
        full_rng = f"A1:{rowcol_to_a1(len(values), ncols)}"
        log_step("format_range", range=full_rng)
        ws.format(full_rng, {
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        })
        money_format = {
            "numberFormat": {
                "type": "NUMBER",
                "pattern": "0.00",
            }
        }
        for money_rng in google_sheet_money_column_ranges(len(values) - 1, rowcol_to_a1):
            log_step("format_money_range", range=money_rng)
            ws.format(money_rng, money_format)
    except Exception:
        pass

    if previous_ws is not None and staging_ws is not None:
        try:
            log_step("replace_worksheet_contents_preserving_id", tab=tab, sheet_id=previous_ws.id)
            _replace_worksheet_contents_preserving_id(
                sh,
                previous_ws,
                staging_ws,
                rows=nvals,
                cols=ncols,
                min_rows=pad_rows,
                min_cols=pad_cols,
            )
            _delete_worksheet_quietly(sh, staging_ws)
        except Exception as exc:
            _delete_worksheet_quietly(sh, staging_ws)
            return {
                "status": "error",
                "message": f"Данные записаны во временный лист, но обновить рабочий лист с сохранением его ID не удалось: {exc}",
            }, 500

    url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    nrows = len(values) - 1
    elapsed = time.monotonic() - started_at
    log_step("done", rows=nrows, cols=ncols)
    return {
        "status": "ok",
        "message": f"Готово: {nrows} строк, {ncols} колонок на листе «{tab}» за {elapsed:.1f} сек. {url}",
        "spreadsheet_url": url,
        "rows": nrows,
        "columns": ncols,
        "sheet_title": tab,
        "elapsed_sec": round(elapsed, 2),
    }


def _delete_worksheet_quietly(spreadsheet, worksheet):
    if worksheet is None:
        return
    try:
        spreadsheet.del_worksheet(worksheet)
    except Exception:
        pass


def _replace_worksheet_contents_preserving_id(
    spreadsheet,
    destination_ws,
    source_ws,
    *,
    rows,
    cols,
    min_rows,
    min_cols,
):
    destination_rows = int(getattr(destination_ws, "row_count", 0) or 0)
    destination_cols = int(getattr(destination_ws, "col_count", 0) or 0)
    if destination_rows < min_rows or destination_cols < min_cols:
        destination_ws.resize(
            rows=max(min_rows, destination_rows),
            cols=max(min_cols, destination_cols),
        )

    source_id = int(source_ws.id)
    destination_id = int(destination_ws.id)
    source_range = {
        "sheetId": source_id,
        "startRowIndex": 0,
        "endRowIndex": int(rows),
        "startColumnIndex": 0,
        "endColumnIndex": int(cols),
    }
    destination_range = dict(source_range)
    destination_range["sheetId"] = destination_id
    spreadsheet.batch_update({
        "requests": [
            {
                "updateCells": {
                    "range": {"sheetId": destination_id},
                    "fields": "*",
                }
            },
            {
                "copyPaste": {
                    "source": source_range,
                    "destination": destination_range,
                    "pasteType": "PASTE_NORMAL",
                    "pasteOrientation": "NORMAL",
                }
            },
        ]
    })


def _sheet_text_value(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (ValueError, TypeError):
        pass
    try:
        if hasattr(value, "isoformat") and not isinstance(value, (str, bytes, int, float, bool)):
            return str(value.isoformat())
        text = str(value)
        return "" if text.lower() == "nan" else text
    except Exception:
        return str(value)


def _normalize_price_series(series_like):
    return (
        pd.Series(series_like)
        .astype(str)
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )


def _preexport_price_issues(df):
    min_margin_pct = 5.0
    min_margin_abs = 20.0
    raw_wholesale = df.get("Цена", None)
    if raw_wholesale is None:
        raw_wholesale = df.get("Лучшая цена", pd.Series(dtype=float))
    raw_rrc = df.get("РРЦ", pd.Series(dtype=float))
    wholesale = pd.to_numeric(_normalize_price_series(raw_wholesale), errors="coerce")
    rrc = pd.to_numeric(_normalize_price_series(raw_rrc), errors="coerce")

    samples = []
    count = 0
    for index, row in df.iterrows():
        price = wholesale.loc[index] if index in wholesale.index else np.nan
        retail = rrc.loc[index] if index in rrc.index else np.nan
        bad, reason = _price_issue_reason(price, retail, min_margin_abs, min_margin_pct)
        if not bad:
            continue
        count += 1
        if len(samples) >= 8:
            continue
        samples.append(_format_price_issue_sample(row, price, retail, reason))
    return count, samples


def _price_issue_reason(price, retail, min_margin_abs, min_margin_pct):
    if not np.isfinite(price) or price <= 0:
        return True, "невалидный опт"
    if not np.isfinite(retail) or retail <= 0:
        return True, "невалидный РРЦ"
    margin_abs = float(retail - price)
    margin_pct = float((margin_abs / price) * 100.0) if price > 0 else -999.0
    if margin_abs <= 0:
        return True, "РРЦ <= опт"
    if margin_abs < min_margin_abs and margin_pct < min_margin_pct:
        return True, f"низкая маржа (<{min_margin_abs} руб и <{min_margin_pct}%)"
    return False, ""


def _format_price_issue_sample(row, price, retail, reason):
    raw_opt = row.get("Цена", row.get("Лучшая цена", ""))
    raw_rrc = row.get("РРЦ", "")
    shown_opt = "" if not np.isfinite(price) else round(float(price), 2)
    shown_rrc = "" if not np.isfinite(retail) else round(float(retail), 2)
    margin_text = ""
    if np.isfinite(price) and price > 0 and np.isfinite(retail):
        margin_abs = float(retail - price)
        margin_pct = float((margin_abs / price) * 100.0)
        margin_text = f", маржа={round(margin_abs, 2)} ({round(margin_pct, 2)}%)"
    raw_text = ""
    if (not np.isfinite(price) and str(raw_opt).strip()) or (not np.isfinite(retail) and str(raw_rrc).strip()):
        raw_text = f" (raw опт: {str(raw_opt).strip()}, raw РРЦ: {str(raw_rrc).strip()})"
    return (
        f"[{str(row.get('Категория', '')).strip()}] {str(row.get('Название', '')).strip()} "
        f"| причина: {reason or 'проверка цены'} | опт={shown_opt}, РРЦ={shown_rrc}{margin_text}{raw_text}"
    )


def _preexport_duplicate_issues(df):
    duplicate_map = {}
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip().lower()
        name_key = normalize_name_key(row.get("Название", ""))
        if not name_key:
            continue
        key = f"{supplier}|{name_key}"
        duplicate_map[key] = int(duplicate_map.get(key, 0)) + 1
    duplicate_count = int(sum(value for value in duplicate_map.values() if value > 1))
    samples = []
    if not duplicate_count:
        return 0, samples
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip()
        name = str(row.get("Название", "")).strip()
        key = f"{supplier.lower()}|{normalize_name_key(name)}"
        count = duplicate_map.get(key, 0)
        if count > 1:
            samples.append(f"[{supplier}] {name} (x{count})")
            if len(samples) >= 8:
                break
    return duplicate_count, samples


def _resolve_gspread_runtime(
    gspread_module=None,
    rowcol_to_a1_func=None,
    api_error_cls=None,
    spreadsheet_not_found_cls=None,
    worksheet_not_found_cls=None,
):
    if gspread_module is not None:
        return (
            gspread_module,
            rowcol_to_a1_func or _fallback_rowcol_to_a1,
            api_error_cls or Exception,
            spreadsheet_not_found_cls or Exception,
            worksheet_not_found_cls or Exception,
        )
    try:
        import gspread
        from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
        from gspread.utils import rowcol_to_a1
    except ImportError:
        return None, None, None, None, None
    return (
        gspread,
        rowcol_to_a1_func or rowcol_to_a1,
        api_error_cls or APIError,
        spreadsheet_not_found_cls or SpreadsheetNotFound,
        worksheet_not_found_cls or WorksheetNotFound,
    )


def _fallback_rowcol_to_a1(row, col):
    col = int(col)
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{int(row)}"
