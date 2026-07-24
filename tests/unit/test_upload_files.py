import pytest

from price_mixer.services.upload_files import (
    build_upload_file_entries,
    make_uploaded_filename,
    supplier_mapping_from_form,
    upload_extension,
)
from price_mixer.services.processing_pipeline import infer_supplier_from_filename


class DummyUpload:
    def __init__(self, filename, content=b"x"):
        self.filename = filename
        self.content = content
        self.saved_to = ""

    def save(self, path):
        self.saved_to = str(path)
        with open(path, "wb") as f:
            f.write(self.content)


def test_supplier_mapping_from_form_reads_supplier_fields_only():
    assert supplier_mapping_from_form({
        "supplier_price.xlsx": "IVEN",
        "supplier_%D0%BF%D1%80%D0%B0%D0%B9%D1%81.xlsx": "N-Tech",
        "other": "ignored",
    }) == {
        "price.xlsx": "IVEN",
        "%D0%BF%D1%80%D0%B0%D0%B9%D1%81.xlsx": "N-Tech",
    }


def test_upload_extension_keeps_supported_excel_and_csv_extensions():
    assert upload_extension("price.xls") == ".xls"
    assert upload_extension("price.xlsx") == ".xlsx"
    assert upload_extension("price.xlsm") == ".xlsm"
    assert upload_extension("price.csv") == ".csv"
    assert upload_extension("price.exe") == ""


def test_make_uploaded_filename_uses_token_and_safe_extension():
    assert make_uploaded_filename("прайс.xlsb", token_factory=lambda: "abcdef123456") == "abcdef12.xlsb"
    with pytest.raises(ValueError, match="Неподдерживаемый формат"):
        make_uploaded_filename("прайс.bad", token_factory=lambda: "feedbeef")


def test_build_upload_file_entries_saves_files_and_resolves_suppliers(tmp_path):
    files = [
        DummyUpload("manual.xlsx"),
        DummyUpload("iven-price.xls"),
        DummyUpload(""),
    ]

    entries = build_upload_file_entries(
        files,
        {"supplier_manual.xlsx": "Manual Supplier"},
        tmp_path,
        {},
        lambda filename, settings: "IVEN" if "iven" in filename else "",
        token_factory=iter(["fileone1", "filetwo2"]).__next__,
    )

    assert entries == [
        {
            "filepath": tmp_path / "fileone1.xlsx",
            "display_name": "manual.xlsx",
            "supplier_name": "Manual Supplier",
        },
        {
            "filepath": tmp_path / "filetwo2.xls",
            "display_name": "iven-price.xls",
            "supplier_name": "IVEN",
        },
    ]
    assert (tmp_path / "fileone1.xlsx").read_bytes() == b"x"
    assert (tmp_path / "filetwo2.xls").read_bytes() == b"x"


def test_build_upload_file_entries_rejects_unknown_supplier(tmp_path):
    with pytest.raises(ValueError, match="Не удалось определить поставщика"):
        build_upload_file_entries(
            [DummyUpload("mystery.xlsx")],
            {},
            tmp_path,
            {},
            lambda filename, settings: "",
        )


def test_infer_supplier_from_filename_keeps_iven_zakaz_distinct_from_iven():
    assert infer_supplier_from_filename("iven_zakaz.xlsx") == "IVEN_zakaz"
    assert infer_supplier_from_filename("iven-zakaz.xls") == "IVEN_zakaz"
    assert infer_supplier_from_filename("ivenzakaz_price.xlsx") == "IVEN_zakaz"
    assert infer_supplier_from_filename("iven.xlsx") == "IVEN"
