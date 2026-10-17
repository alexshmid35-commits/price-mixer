"""Techlab price import, direct downloads and supplier isolation."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
import requests

from price_mixer import settings
from price_mixer.services import api_sources
from price_mixer.services.export_stats import export_rows_from_json_rows
from price_mixer.services._legacy import consolidate_simple, parse_generic_excel
from price_mixer.services.processing_pipeline import infer_supplier_from_filename
from price_mixer.services.techlab import parse_techlab_excel


@pytest.fixture
def techlab_price(tmp_path):
    path = tmp_path / "techlab_bn.xlsx"
    rows = [
        ['ООО "Теч-Лаб"', None, None],
        ["Все цены с учётом НДС!", None, None],
        ["Группа", "Код товара", "Наименование", "Парт-номер", "Vip", "Дил", "Опт", "РРЦ", "Гар", "Наличие", "Количество", "Производитель", "Внешний ID", "Внешняя ссылка"],
        ["SSD", None, None, None, None, 0, 0],
        ["SSD", "1001", "SSD Kingston Test", "SA400S37/480G", "49,65", 50.60, 52.02, "65,00", "24", "Склад", ">10", "Kingston", "1234567", "https://catalog.onliner.by/ssd/kingston/test"],
        ["SSD", "1002", "SSD Kingston SA400S37/960G", "SA400S37/960G", "90,50", 95, "100,50", None, "12", "Под заказ", "1", "Kingston", None, None],
        ["SSD", "1003", "Sold out SSD", "ZERO", 1, 2, 3, None, None, "Склад", "0", None, None, None],
    ]
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


def test_techlab_imports_opt_with_ids_warranty_and_no_section_rows(techlab_price):
    parsed = parse_techlab_excel(techlab_price)
    assert parsed["supplier_code"].tolist() == ["1001", "1002"]
    assert parsed["price_byn"].tolist() == [52.02, 100.5]
    assert parsed["supplier"].tolist() == ["Techlab", "Techlab"]
    assert parsed["delivery_days"].tolist() == [2, 2]
    assert parsed["onliner_id"].iloc[0] == "1234567"
    assert pd.isna(parsed["onliner_id"].iloc[1])
    assert parsed["warranty"].tolist() == [24, 12]
    assert parsed["rrc"].iloc[0] == 65
    assert parsed["product_name"].tolist() == [
        "SSD Kingston Test (SA400S37/480G)", "SSD Kingston SA400S37/960G"
    ]
    consolidated = consolidate_simple(parsed)
    row = consolidated[consolidated["OnlinerID"] == "1234567"].iloc[0]
    assert row["Ссылка"] == "https://catalog.onliner.by/ssd/kingston/test"
    assert row["Цена"] == 52.02


@pytest.mark.parametrize("column,expected", [("Vip", 49.65), ("Дил", 50.6), ("Опт", 52.02)])
def test_techlab_respects_price_tier_and_delivery_settings(techlab_price, column, expected):
    parsed = parse_techlab_excel(techlab_price, settings={
        "price_column": column, "stock_delivery_days": 1, "order_delivery_days": 5,
    })
    assert parsed["price_byn"].iloc[0] == expected
    assert parsed["delivery_days"].tolist() == [1, 5]


def test_techlab_does_not_guess_missing_price_column(techlab_price):
    frame = pd.read_excel(techlab_price, header=2).drop(columns=["Опт"])
    frame.to_excel(techlab_price, index=False)
    with pytest.raises(ValueError, match="отсутствует выбранная цена"):
        parse_techlab_excel(techlab_price)


def test_techlab_rejects_internal_code_as_onliner_id(techlab_price):
    frame = pd.read_excel(techlab_price, header=2, dtype=str)
    frame.loc[1, "Внешний ID"] = "not-an-id"
    frame.to_excel(techlab_price, index=False)
    parsed = parse_techlab_excel(techlab_price)
    assert parsed["onliner_id"].isna().all()


def test_techlab_uses_same_parser_for_manual_upload(techlab_price, monkeypatch):
    monkeypatch.setattr(settings, "load_app_settings", lambda: {
        "api_sources": {"techlab": {"price_column": "Опт"}},
    })
    parsed = parse_generic_excel(techlab_price, "Techlab")
    assert parsed["price_byn"].tolist() == [52.02, 100.5]


@pytest.mark.parametrize("other_price,winner", [(60, "Techlab"), (40, "IVEN")])
def test_techlab_and_other_supplier_keep_rows_until_cheapest_export(techlab_price, other_price, winner):
    techlab = parse_techlab_excel(techlab_price).iloc[[0]].copy()
    other = techlab.copy()
    other["supplier"] = "IVEN"
    other["price_byn"] = other_price
    consolidated = consolidate_simple(pd.concat([techlab, other], ignore_index=True))
    assert len(consolidated) == 2
    rows = [
        [row["OnlinerID"], row["Название"], row["Цена"], row["Поставщик"]]
        for _, row in consolidated.iterrows()
    ]
    exported = export_rows_from_json_rows(
        rows, {"export": {"keep_lowest_price_per_onliner_id": True}},
        normalize_onliner_id=lambda value: str(value or ""),
        normalize_name_key=lambda value: str(value).lower(),
        normalize_supplier_name_list=lambda value: list(value or []),
        is_pc_export_row=lambda row: False,
    )
    assert len(exported) == 1
    assert exported[0]["supplier"] == winner


@pytest.mark.parametrize("filename", ["techlab_bn.xlsx", "techlab.xlsx", "tech-lab_bn.xlsx"])
def test_techlab_manual_filename_identifies_supplier(filename):
    assert infer_supplier_from_filename(filename) == "Techlab"


def test_techlab_source_is_added_to_existing_settings_without_changing_other_sources(monkeypatch, tmp_path):
    path = tmp_path / "app_settings.json"
    path.write_text('{"api_sources":{"iven":{"enabled":true}}}', encoding="utf-8")
    monkeypatch.setattr(settings, "APP_SETTINGS_FILE", path)
    loaded = settings.load_app_settings()
    assert loaded["api_sources"]["iven"]["enabled"] is True
    techlab = loaded["api_sources"]["techlab"]
    assert techlab["enabled"] is True
    assert techlab["file_url"] == "http://tech-lab.by/price/techlab_bn.xlsx"
    assert techlab["price_column"] == "Опт"
    assert techlab["stock_delivery_days"] == techlab["order_delivery_days"] == 2
    normalized = settings._normalize_api_sources({"techlab": {
        "price_column": "random", "stock_delivery_days": "broken", "order_delivery_days": -10,
    }})["techlab"]
    assert normalized["price_column"] == "Опт"
    assert normalized["stock_delivery_days"] == 2
    assert normalized["order_delivery_days"] == 0


def _fetch_techlab(tmp_path):
    api_sources.fetch_api_source_worker(
        "techlab", "test-techlab", upload_dir=tmp_path,
        load_settings=lambda: {"api_sources": {"techlab": {
            "label": "Techlab", "supplier": "Techlab", "mode": "direct_file",
            "file_url": "http://tech-lab.by/price/techlab_bn.xlsx", "verify_ssl": True,
        }}}, append_history=lambda record: None,
    )
    return api_sources.get_source_runtime("techlab", "test-techlab")


def test_techlab_downloads_public_file_without_iven_downloader(tmp_path, techlab_price, monkeypatch):
    monkeypatch.setenv("PRICE_MIXER_JOB_MODE", "inline")
    def stream(url, target, *args, **kwargs):
        assert kwargs["timeout"] == (8, 25)
        shutil.copyfile(techlab_price, target)
    monkeypatch.setattr(api_sources, "stream_download_to_path", stream)
    state = _fetch_techlab(tmp_path)
    assert state["ready"] is True
    assert state["supplier"] == "Techlab"


def test_techlab_rejects_html_instead_of_excel(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICE_MIXER_JOB_MODE", "inline")
    def stream(url, target, *args, **kwargs):
        Path(target).write_text("<html>Site unavailable</html>")
    monkeypatch.setattr(api_sources, "stream_download_to_path", stream)
    state = _fetch_techlab(tmp_path)
    assert state["ready"] is False
    assert state["status"] == "error"
    assert "Excel" in state["message"]


def test_techlab_network_failure_uses_only_its_configured_ssh_host(tmp_path, techlab_price, monkeypatch):
    monkeypatch.setenv("PRICE_MIXER_JOB_MODE", "inline")
    monkeypatch.setenv("PRICE_MIXER_TECHLAB_SSH_HOST", "root@reserve.test")
    monkeypatch.setenv("PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST", "root@iven-only.test")
    def stream(*args, **kwargs):
        raise requests.exceptions.ReadTimeout("timeout")
    def ssh(url, target, *args, **kwargs):
        assert kwargs["host"] == "root@reserve.test"
        shutil.copyfile(techlab_price, target)
    monkeypatch.setattr(api_sources, "stream_download_to_path", stream)
    monkeypatch.setattr(api_sources, "ssh_download_to_path", ssh)
    assert _fetch_techlab(tmp_path)["ready"] is True
    monkeypatch.delenv("PRICE_MIXER_TECHLAB_SSH_HOST")
    assert api_sources.source_ssh_fallback_host("techlab") == ""
    state = _fetch_techlab(tmp_path)
    assert state["ready"] is False
    assert "PRICE_MIXER_TECHLAB_SSH_HOST" in state["message"]
