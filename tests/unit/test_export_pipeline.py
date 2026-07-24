"""Unit tests for export preparation and quality helpers."""

import json

import numpy as np
import pandas as pd

from price_mixer.services import export_pipeline as svc


def test_parse_google_spreadsheet_id_accepts_url_and_plain_id():
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"

    assert svc.parse_google_spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{sid}/edit") == sid
    assert svc.parse_google_spreadsheet_id(sid) == sid
    assert svc.parse_google_spreadsheet_id("bad") == ""


def test_resolve_service_account_json_path_searches_base_dir_and_cwd(tmp_path):
    base_dir = tmp_path / "app"
    cwd = tmp_path / "cwd"
    base_dir.mkdir()
    cwd.mkdir()
    key_file = base_dir / "sa.json"
    key_file.write_text(json.dumps({"client_email": "svc@example.com"}), encoding="utf-8")

    path, error = svc.resolve_service_account_json_path("sa.json", base_dir=base_dir, cwd=cwd)

    assert path == key_file.resolve()
    assert error == ""


def test_prepare_consolidated_for_export_applies_configured_filters(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("exists", encoding="utf-8")
    df = pd.DataFrame({
        "Название": ["No ID", "High", "Low", "PC", "Mouse"],
        "OnlinerID": ["", "111", "111", "222", "333"],
        "Цена": [1, 50, 40, 500, 10],
        "Поставщик": ["A", "A", "B", "PCSupplier", "PCSupplier"],
        "Категория": ["SSD", "SSD", "SSD", "Компьютер", "Мышь"],
    })
    settings = {
        "export": {
            "include_without_id": False,
            "keep_lowest_price_per_onliner_id": True,
            "price_name": "main",
            "exclude_duplicate_id_suppliers": ["B"],
            "only_pc_suppliers": ["PCSupplier"],
            "only_pc_price_name": "pc_only",
        }
    }

    result, download_name = svc.prepare_consolidated_for_export(
        tmp_path,
        settings,
        read_consolidated_df=lambda session_dir: df,
        apply_visibility_filter=lambda frame, session_dir: frame,
        apply_keep_lowest_price_per_onliner_id=lambda frame: frame.sort_values("Цена").drop_duplicates("OnlinerID"),
        apply_duplicate_id_filter=lambda frame, suppliers: frame[~frame["Поставщик"].isin(suppliers)],
        apply_only_pc_filter=lambda frame, suppliers: frame[
            (frame["Поставщик"] != "PCSupplier") | (frame["Категория"] == "Компьютер")
        ],
    )

    assert download_name == "pc_only.xlsx"
    assert list(result["Название"]) == ["PC"]


def test_prepare_consolidated_for_export_accepts_fast_json_before_xlsx_exists(tmp_path):
    (tmp_path / "consolidated.json").write_text('{"data":[]}', encoding="utf-8")
    df = pd.DataFrame({
        "Название": ["SSD"],
        "OnlinerID": ["111"],
        "Цена": [10],
        "Поставщик": ["A"],
        "Категория": ["SSD"],
    })

    result, download_name = svc.prepare_consolidated_for_export(
        tmp_path,
        {"export": {"price_name": "main"}},
        read_consolidated_df=lambda session_dir: df,
        apply_visibility_filter=lambda frame, session_dir: frame,
    )

    assert download_name == "main.xlsx"
    assert list(result["Название"]) == ["SSD"]


def test_prepare_consolidated_for_export_excludes_hidden_category_even_with_onliner_id(tmp_path):
    (tmp_path / "consolidated.json").write_text('{"data":[]}', encoding="utf-8")
    df = pd.DataFrame({
        "Название": ["Hidden SSD", "Visible monitor", "Hidden without ID"],
        "OnlinerID": ["111", "222", ""],
        "Поставщик": ["A", "A", "A"],
        "Категория": ["SSD", "Монитор", "SSD"],
    })

    result, _ = svc.prepare_consolidated_for_export(
        tmp_path,
        {"export": {"include_without_id": False}},
        read_consolidated_df=lambda session_dir: df,
        apply_visibility_filter=lambda frame, session_dir: frame[frame["Категория"] != "SSD"],
    )

    assert list(result["Название"]) == ["Visible monitor"]


def test_prepare_consolidated_for_export_excludes_configured_category_prefix(tmp_path):
    (tmp_path / "consolidated.json").write_text('{"data":[]}', encoding="utf-8")
    df = pd.DataFrame({
        "Название": ["Ready SSD", "Needs sorting", "Needs sorting plain"],
        "OnlinerID": ["111", "222", "333"],
        "Цена": [100, 120, 130],
        "Поставщик": ["A", "A", "A"],
        "Категория": ["SSD", "Требует сортировки · родитель: SSD", "Требует сортировки"],
    })

    result, _ = svc.prepare_consolidated_for_export(
        tmp_path,
        {"export": {"exclude_category_prefixes": ["Требует сортировки"]}},
        read_consolidated_df=lambda session_dir: df,
        apply_visibility_filter=lambda frame, session_dir: frame,
    )

    assert list(result["Название"]) == ["Ready SSD"]


def test_prepare_consolidated_for_export_excludes_configured_name_contains(tmp_path):
    (tmp_path / "consolidated.json").write_text('{"data":[]}', encoding="utf-8")
    df = pd.DataFrame({
        "Название": [
            "USB cable",
            "Патрон бесключевой Milwaukee",
            "Стойка для дрели P.I.T. P0010001",
            "Адаптер Milwaukee 4932367166",
        ],
        "OnlinerID": ["111", "222", "333", "444"],
        "Цена": [100, 120, 130, 140],
        "Поставщик": ["A", "A", "A", "A"],
        "Категория": ["Кабели и переходники", "Кабели и переходники", "Кабели и переходники", "Кабели и переходники"],
    })

    result, _ = svc.prepare_consolidated_for_export(
        tmp_path,
        {"export": {"exclude_name_contains": ["патрон", "milwaukee", "p.i.t"]}},
        read_consolidated_df=lambda session_dir: df,
        apply_visibility_filter=lambda frame, session_dir: frame,
    )

    assert list(result["Название"]) == ["USB cable"]


def test_dataframe_to_sheet_values_uses_fixed_layout_and_normalizes_values():
    df = pd.DataFrame({
        "Наименование": ["SSD", "Mouse"],
        "Опт цена": ["1 234,5", np.nan],
        "Поставщик": ["A", "B"],
        "Гарантия": [24, None],
        "Срок поставки": ["2", "nan"],
        "РРЦ": [1500, float("inf")],
        "Цена без скидки": [1600.126, ""],
        "Onliner ID": [" 00123 ", "bad id"],
    })

    assert svc.dataframe_to_sheet_values(df) == [
        ["", "Название", "Цена", "Поставщик", "Гарантия", "Дней доставки", "РРЦ", "Цена без скидки", "OnlinerID"],
        ["", "SSD", 1234.5, "A", "24.0", "2", 1500.0, 1600.13, "00123"],
        ["", "Mouse", "", "B", "", "", "", "", "bad id"],
    ]


def test_dataframe_to_sheet_values_keeps_large_money_as_numeric_value():
    df = pd.DataFrame({
        "Название": ["Notebook"],
        "Цена": [7892.07],
        "РРЦ": [8440],
        "Цена без скидки": [9710],
        "OnlinerID": ["4952334"],
    })

    assert svc.dataframe_to_sheet_values(df)[1] == [
        "",
        "Notebook",
        7892.07,
        "",
        "",
        "",
        8440.0,
        9710.0,
        "4952334",
    ]


def test_dataframe_to_export_dataframe_matches_google_sheet_layout():
    source = pd.DataFrame({
        "Название": ["SSD"],
        "Цена": [1234.5],
        "Поставщик": ["A"],
        "Гарантия": [24],
        "Дней доставки": [2],
        "РРЦ": [1500],
        "Цена без скидки": [1600.126],
        "OnlinerID": ["00123"],
        "Категория": ["SSD"],
        "Ссылка": ["https://example.test/product"],
    })

    result = svc.dataframe_to_export_dataframe(source)

    assert list(result.columns) == [
        "",
        "Название",
        "Цена",
        "Поставщик",
        "Гарантия",
        "Дней доставки",
        "РРЦ",
        "Цена без скидки",
        "OnlinerID",
    ]
    assert result.iloc[0].tolist() == [
        "",
        "SSD",
        1234.5,
        "A",
        "24",
        "2",
        1500.0,
        1600.13,
        "00123",
    ]
    assert "Категория" not in result.columns
    assert "Ссылка" not in result.columns


def test_dataframe_to_export_dataframe_keeps_target_headers_when_empty():
    result = svc.dataframe_to_export_dataframe(pd.DataFrame())

    assert list(result.columns) == [
        "",
        "Название",
        "Цена",
        "Поставщик",
        "Гарантия",
        "Дней доставки",
        "РРЦ",
        "Цена без скидки",
        "OnlinerID",
    ]
    assert result.empty


def test_google_sheet_money_column_ranges_target_export_price_columns():
    assert svc.google_sheet_money_column_ranges(3, lambda row, col: f"R{row}C{col}") == [
        "R2C3:R4C3",
        "R2C7:R4C7",
        "R2C8:R4C8",
    ]


def test_build_preexport_quality_payload_counts_missing_ids_price_issues_and_duplicates():
    df = pd.DataFrame({
        "Категория": ["SSD", "SSD", "SSD", "RAM"],
        "Название": ["No ID", "Duplicate", "Duplicate", "Bad RRC"],
        "OnlinerID": ["", "1", "2", "3"],
        "Цена": [100, 100, 120, 100],
        "РРЦ": [130, 130, 150, 90],
        "Поставщик": ["A", "B", "B", "C"],
    })

    payload = svc.build_preexport_quality_payload(df)

    assert payload["status"] == "ok"
    assert payload["checked"] == 4
    assert payload["missing_id_count"] == 1
    assert payload["suspicious_price_count"] == 1
    assert payload["duplicate_count"] == 2
    assert payload["missing_id_samples"] == ["[SSD] No ID"]
    assert "РРЦ <= опт" in payload["suspicious_price_samples"][0]
    assert payload["duplicate_samples"] == ["[B] Duplicate (x2)", "[B] Duplicate (x2)"]


def test_build_preexport_quality_payload_handles_empty_df():
    payload = svc.build_preexport_quality_payload(pd.DataFrame())

    assert payload == {
        "status": "ok",
        "checked": 0,
        "missing_id_count": 0,
        "suspicious_price_count": 0,
        "duplicate_count": 0,
        "missing_id_samples": [],
        "suspicious_price_samples": [],
        "duplicate_samples": [],
    }


class FakeApiError(Exception):
    pass


class FakeSpreadsheetNotFound(Exception):
    pass


class FakeWorksheetNotFound(Exception):
    pass


class FakeWorksheet:
    def __init__(self, title="Export", fail_update=False, sheet_id=1):
        self.title = title
        self.id = sheet_id
        self.row_count = 1000
        self.col_count = 26
        self.cleared = False
        self.fail_update = fail_update
        self.resized = None
        self.updates = []
        self.formats = []

    def clear(self):
        self.cleared = True

    def resize(self, rows, cols):
        self.resized = (rows, cols)
        self.row_count = rows
        self.col_count = cols

    def update(self, chunk, rng, value_input_option=None):
        if self.fail_update:
            raise FakeApiError("write failed")
        self.updates.append((chunk, rng, value_input_option))

    def format(self, rng, fmt):
        self.formats.append((rng, fmt))

    def update_title(self, title):
        self.title = title


class FakeSpreadsheet:
    def __init__(self, existing_title=None, fail_staging_update=False, fail_batch_update=False):
        self.ws = FakeWorksheet(sheet_id=2)
        self.existing_ws = FakeWorksheet(existing_title, sheet_id=1) if existing_title else None
        self.fail_staging_update = fail_staging_update
        self.fail_batch_update = fail_batch_update
        self.added = []
        self.deleted = []
        self.batch_updates = []

    def worksheet(self, title):
        if self.existing_ws is not None and self.existing_ws.title == title:
            return self.existing_ws
        raise FakeWorksheetNotFound(title)

    def add_worksheet(self, title, rows, cols):
        self.added.append((title, rows, cols))
        self.ws = FakeWorksheet(title, fail_update=self.fail_staging_update, sheet_id=2)
        self.ws.row_count = rows
        self.ws.col_count = cols
        return self.ws

    def del_worksheet(self, worksheet):
        self.deleted.append(worksheet)
        if worksheet is self.existing_ws:
            self.existing_ws = None

    def batch_update(self, body):
        if self.fail_batch_update:
            raise FakeApiError("batch update failed")
        self.batch_updates.append(body)


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet
        self.opened_key = None

    def open_by_key(self, sid):
        self.opened_key = sid
        return self.spreadsheet


class FakeGspread:
    def __init__(self, client):
        self.client = client
        self.service_account_filename = None

    def service_account(self, filename):
        self.service_account_filename = filename
        return self.client


def test_export_google_sheets_payload_creates_sheet_and_writes_values(tmp_path):
    spreadsheet = FakeSpreadsheet()
    client = FakeClient(spreadsheet)
    gspread = FakeGspread(client)
    key_file = tmp_path / "service.json"
    key_file.write_text("{}", encoding="utf-8")
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    settings = {
        "export": {
            "google_sheets_spreadsheet_url_or_id": f"https://docs.google.com/spreadsheets/d/{sid}/edit",
            "google_sheets_tab": "Export",
            "google_sheets_service_account_json": str(key_file),
        }
    }
    df = pd.DataFrame({"Название": ["SSD"], "Цена": [123.4], "Поставщик": ["A"], "OnlinerID": ["111"]})

    payload = svc.export_google_sheets_payload(
        tmp_path,
        settings,
        prepare_consolidated_for_export=lambda session_dir: (df, "price.xlsx"),
        resolve_service_account_json_path_func=lambda raw: (key_file, ""),
        gspread_module=gspread,
        api_error_cls=FakeApiError,
        spreadsheet_not_found_cls=FakeSpreadsheetNotFound,
        worksheet_not_found_cls=FakeWorksheetNotFound,
    )

    assert payload["status"] == "ok"
    assert payload["rows"] == 1
    assert payload["columns"] == 9
    assert payload["spreadsheet_url"] == f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    assert gspread.service_account_filename == str(key_file)
    assert client.opened_key == sid
    assert spreadsheet.added == [("Export", 1000, 26)]
    assert spreadsheet.ws.updates[0][1] == "A1:I2"
    assert spreadsheet.ws.updates[0][2] == "USER_ENTERED"
    assert spreadsheet.ws.formats[0][0] == "A1:I2"
    assert spreadsheet.ws.formats[1:] == [
        ("C2:C2", {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}),
        ("G2:G2", {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}),
        ("H2:H2", {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}),
    ]


def test_export_google_sheets_payload_validates_missing_sheet_id(tmp_path):
    payload, status = svc.export_google_sheets_payload(
        tmp_path,
        {"export": {"google_sheets_spreadsheet_url_or_id": "bad"}},
        prepare_consolidated_for_export=lambda session_dir: (pd.DataFrame(), "price.xlsx"),
        gspread_module=FakeGspread(FakeClient(FakeSpreadsheet())),
        api_error_cls=FakeApiError,
        spreadsheet_not_found_cls=FakeSpreadsheetNotFound,
        worksheet_not_found_cls=FakeWorksheetNotFound,
    )

    assert status == 400
    assert payload["status"] == "error"
    assert "Google Таблица" in payload["message"]


def test_export_google_sheets_payload_preserves_existing_sheet_id(tmp_path):
    spreadsheet = FakeSpreadsheet(existing_title="Export")
    old_ws = spreadsheet.existing_ws
    client = FakeClient(spreadsheet)
    key_file = tmp_path / "service.json"
    key_file.write_text("{}", encoding="utf-8")
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    df = pd.DataFrame({"Название": ["SSD"], "Цена": [123.4], "Поставщик": ["A"], "OnlinerID": ["111"]})

    payload = svc.export_google_sheets_payload(
        tmp_path,
        {"export": {
            "google_sheets_spreadsheet_url_or_id": sid,
            "google_sheets_tab": "Export",
            "google_sheets_service_account_json": str(key_file),
        }},
        prepare_consolidated_for_export=lambda session_dir: (df, "price.xlsx"),
        resolve_service_account_json_path_func=lambda raw: (key_file, ""),
        gspread_module=FakeGspread(client),
        api_error_cls=FakeApiError,
        spreadsheet_not_found_cls=FakeSpreadsheetNotFound,
        worksheet_not_found_cls=FakeWorksheetNotFound,
    )

    assert payload["status"] == "ok"
    assert old_ws.cleared is False
    assert old_ws not in spreadsheet.deleted
    assert old_ws.title == "Export"
    assert old_ws.id == 1
    assert spreadsheet.ws in spreadsheet.deleted
    assert spreadsheet.batch_updates[0]["requests"][0] == {
        "updateCells": {"range": {"sheetId": 1}, "fields": "*"}
    }
    copy_request = spreadsheet.batch_updates[0]["requests"][1]["copyPaste"]
    assert copy_request["source"]["sheetId"] == 2
    assert copy_request["destination"]["sheetId"] == 1
    assert spreadsheet.ws.updates[0][1] == "A1:I2"


def test_export_google_sheets_payload_keeps_existing_sheet_when_staging_write_fails(tmp_path):
    spreadsheet = FakeSpreadsheet(existing_title="Export", fail_staging_update=True)
    old_ws = spreadsheet.existing_ws
    client = FakeClient(spreadsheet)
    key_file = tmp_path / "service.json"
    key_file.write_text("{}", encoding="utf-8")
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    df = pd.DataFrame({"Название": ["SSD"], "Цена": [123.4], "Поставщик": ["A"], "OnlinerID": ["111"]})

    payload, status = svc.export_google_sheets_payload(
        tmp_path,
        {"export": {
            "google_sheets_spreadsheet_url_or_id": sid,
            "google_sheets_tab": "Export",
            "google_sheets_service_account_json": str(key_file),
        }},
        prepare_consolidated_for_export=lambda session_dir: (df, "price.xlsx"),
        resolve_service_account_json_path_func=lambda raw: (key_file, ""),
        gspread_module=FakeGspread(client),
        api_error_cls=FakeApiError,
        spreadsheet_not_found_cls=FakeSpreadsheetNotFound,
        worksheet_not_found_cls=FakeWorksheetNotFound,
    )

    assert status == 500
    assert payload["status"] == "error"
    assert old_ws.title == "Export"
    assert old_ws.cleared is False
    assert old_ws not in spreadsheet.deleted
    assert spreadsheet.ws in spreadsheet.deleted


def test_export_google_sheets_payload_keeps_existing_sheet_when_atomic_copy_fails(tmp_path):
    spreadsheet = FakeSpreadsheet(existing_title="Export", fail_batch_update=True)
    old_ws = spreadsheet.existing_ws
    client = FakeClient(spreadsheet)
    key_file = tmp_path / "service.json"
    key_file.write_text("{}", encoding="utf-8")
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz_12345"
    df = pd.DataFrame({"Название": ["SSD"], "Цена": [123.4], "Поставщик": ["A"], "OnlinerID": ["111"]})

    payload, status = svc.export_google_sheets_payload(
        tmp_path,
        {"export": {
            "google_sheets_spreadsheet_url_or_id": sid,
            "google_sheets_tab": "Export",
            "google_sheets_service_account_json": str(key_file),
        }},
        prepare_consolidated_for_export=lambda session_dir: (df, "price.xlsx"),
        resolve_service_account_json_path_func=lambda raw: (key_file, ""),
        gspread_module=FakeGspread(client),
        api_error_cls=FakeApiError,
        spreadsheet_not_found_cls=FakeSpreadsheetNotFound,
        worksheet_not_found_cls=FakeWorksheetNotFound,
    )

    assert status == 500
    assert payload["status"] == "error"
    assert "сохранением его ID" in payload["message"]
    assert old_ws.title == "Export"
    assert old_ws.id == 1
    assert old_ws not in spreadsheet.deleted
    assert spreadsheet.ws in spreadsheet.deleted
