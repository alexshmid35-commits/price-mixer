"""Unit tests for category DataFrame pipeline helpers."""

import pandas as pd
import pytest

from price_mixer.services import category_pipeline as svc
from price_mixer.services.product_normalization import build_item_category_keys


def item_keys(row):
    return [f"name:{row.get('Название', '')}"]


def infer(name):
    text = str(name).lower()
    if "ssd" in text:
        return "SSD"
    if "mouse" in text:
        return "Мышь"
    return "Прочее"


def test_get_effective_category_prefers_manual_override():
    row = {"Название": "Kingston SSD"}

    assert svc.get_effective_category(
        row,
        overrides={"name:Kingston SSD": "Накопители"},
        build_item_category_keys=item_keys,
        infer_category=infer,
    ) == "Накопители"


def test_get_effective_category_falls_back_to_inference():
    assert svc.get_effective_category(
        {"Название": "Kingston SSD"},
        build_item_category_keys=item_keys,
        infer_category=infer,
    ) == "SSD"


def test_row_category_repairs_high_confidence_existing_category():
    row = {"Название": "Logitech Mouse", "Категория": "Периферия"}

    assert svc.row_category(
        row,
        overrides={"name:Logitech Mouse": "Мышь"},
        build_item_category_keys=item_keys,
        infer_category=infer,
    ) == "Мышь"


def test_high_confidence_inference_can_repair_stale_overrides():
    row = {"Название": "Радиатор для SSD Digma DGRDRM2A"}

    assert svc.get_effective_category(
        row,
        overrides={"name:Радиатор для SSD Digma DGRDRM2A": "SSD"},
        build_item_category_keys=item_keys,
        infer_category=lambda name: "Охлаждение",
    ) == "Охлаждение"


def test_high_confidence_inference_can_repair_existing_category():
    row = {"Название": '27" LG 27U411A-B, 1920x1080, IPS, 120 Гц, HDMI', "Категория": "27"}

    assert svc.row_category(row, infer_category=lambda name: "Монитор") == "Монитор"


def test_high_confidence_inference_repairs_legacy_paper_and_server_accessory_categories():
    paper_row = {"Название": "Бумага Cactus CS-LFP80-841175 A0", "Категория": "БУМАГА"}
    server_accessory_row = {"Название": "Аксессуары для серверов Gooxi ZA-1104", "Категория": "АКСЕССУАРЫ"}

    assert svc.row_category(paper_row, infer_category=lambda name: "Бумага и материалы для печати") == (
        "Бумага и материалы для печати"
    )
    assert svc.row_category(server_accessory_row, infer_category=lambda name: "Аксессуары для серверов") == (
        "Аксессуары для серверов"
    )


def test_high_confidence_inference_repairs_legacy_usb_and_computer_categories():
    usb_row = {"Название": "USB3.0 128Gb Netac U182 USB 3.0 Type-A", "Категория": "USB3"}
    pc_row = {"Название": "Компьютер IVEN BY Gaming White 180995", "Категория": "Компьютер"}
    cable_row = {"Название": "Кабель компьютер - сеть 220V, 1.8м", "Категория": "Компьютер"}
    external_ssd_row = {"Название": "[Накопители USB] 2Tb SSD A-Data SD620 Blue", "Категория": "Накопители USB"}
    external_hdd_row = {"Название": "[Накопители USB] Внешний HDD 2Tb WD Elements Portable", "Категория": "Накопители USB"}
    liquid_cooling_row = {"Название": "[Монитор] Система водяного охлаждения ID-Cooling SL360", "Категория": "Монитор"}
    keyboard_row = {"Название": "[Кабели и переходники] Клавиатура A4Tech Fstyler FK25", "Категория": "Кабели и переходники"}
    cooling_from_cables = {"Название": "[Кабели и переходники] Система охлаждения ID-Cooling FS-04", "Категория": "Кабели и переходники"}
    tool_from_cables = {"Название": "[Кабели и переходники] Стойка для дрели TEH TCD8160-STD", "Категория": "Кабели и переходники"}
    pc_row_from_ssd = {"Название": "[SSD] ПЭВМ TGPC Office.Slim 96064 I-X Celeron G5905", "Категория": "SSD"}
    monitor_from_peripheral = {"Название": "[Периферия] Монитор 27\" Philips 27E1N5600HE", "Категория": "Периферия"}
    bracket_from_monitor = {"Название": "[Монитор] Кронштейн для монитора ErgoSmart Simple II", "Категория": "Монитор"}
    mouse_from_peripheral = {"Название": "[Периферия] Мышь беспроводная Logitech M190", "Категория": "Периферия"}
    splitter_from_peripheral = {"Название": "[Периферия] Разветвитель USB2.0 Ugreen US158 30345", "Категория": "Периферия"}
    hub_from_cables = {"Название": "[Кабели и переходники] USB-хаб TP-Link UH720", "Категория": "Кабели и переходники"}
    speakers_from_headphones = {"Название": "[Наушники] Колонки 2.0 Defender SPK-225, выход на наушники", "Категория": "Наушники"}
    ram_from_pc = {"Название": "[Системный блок] DDR5 16Gb KiTof2 PC-48000 6000MHz", "Категория": "Системный блок"}
    real_pc_with_ram = {"Название": "Компьютер IVEN BY Gaming Black Core i5/16Gb DDR5/SSD", "Категория": "Системный блок"}

    assert svc.row_category(usb_row, infer_category=lambda name: "Накопители USB") == "Накопители USB"
    assert svc.row_category(pc_row, infer_category=lambda name: "Системный блок") == "Системный блок"
    assert svc.row_category(cable_row, infer_category=lambda name: "Кабели и переходники") == "Кабели и переходники"
    assert svc.row_category(external_ssd_row, infer_category=lambda name: "SSD") == "SSD"
    assert svc.row_category(external_hdd_row, infer_category=lambda name: "Жесткий диск") == "Жесткий диск"
    assert svc.row_category(liquid_cooling_row, infer_category=lambda name: "Охлаждение") == "Охлаждение"
    assert svc.row_category(keyboard_row, infer_category=lambda name: "Клавиатура") == "Клавиатура"
    assert svc.row_category(cooling_from_cables, infer_category=lambda name: "Охлаждение") == "Охлаждение"
    assert svc.row_category(
        tool_from_cables,
        infer_category=lambda name: "Строительный, слесарный, монтажный инструмент",
    ) == "Строительный, слесарный, монтажный инструмент"
    assert svc.row_category(pc_row_from_ssd, infer_category=lambda name: "Системный блок") == "Системный блок"
    assert svc.row_category(monitor_from_peripheral, infer_category=lambda name: "Монитор") == "Монитор"
    assert svc.row_category(bracket_from_monitor, infer_category=lambda name: "Кронштейны") == "Кронштейны"
    assert svc.row_category(mouse_from_peripheral, infer_category=lambda name: "Мышь") == "Мышь"
    assert svc.row_category(splitter_from_peripheral, infer_category=lambda name: "Кабели и переходники") == (
        "Кабели и переходники"
    )
    assert svc.row_category(hub_from_cables, infer_category=lambda name: "USB-хабы") == "USB-хабы"
    assert svc.row_category(speakers_from_headphones, infer_category=lambda name: "Акустика") == "Акустика"
    assert svc.row_category(ram_from_pc, infer_category=lambda name: "Оперативная память") == "Оперативная память"
    assert svc.row_category(real_pc_with_ram, infer_category=lambda name: "Системный блок") == "Системный блок"


def test_ensure_category_column_returns_copy_with_categories():
    source = pd.DataFrame({"Название": ["Kingston SSD", "Logitech Mouse"]})

    result = svc.ensure_category_column(
        source,
        build_item_category_keys=item_keys,
        infer_category=infer,
    )

    assert "Категория" not in source.columns
    assert list(result["Категория"]) == ["SSD", "Мышь"]


def test_visibility_map_delegates_storage_callbacks(tmp_path):
    saved = {}

    assert svc.load_visibility_map(tmp_path, load_visibility=lambda: {"A": ["SSD"]}) == {"A": ["SSD"]}

    svc.save_visibility_map(
        tmp_path,
        {"B": ["Мышь"]},
        save_visibility=lambda payload: saved.update(payload),
    )

    assert saved == {"B": ["Мышь"]}


def test_apply_saved_markups_to_df_updates_rrc_from_wholesale_price():
    df = pd.DataFrame({
        "Название": ["Kingston SSD"],
        "Категория": ["SSD"],
        "Цена": [100],
        "OnlinerID": ["123"],
    })

    result = svc.apply_saved_markups_to_df(
        df,
        load_category_markups=lambda: {
            "SSD": {
                "percent": 20,
                "threshold": 0,
                "min_profit": 0,
                "no_discount_percent": 10,
                "base_mode": "wholesale",
            }
        },
        get_category_markup_config=lambda markups, category: markups[category],
        calc_rrc_and_no_discount=lambda base, percent, **kwargs: (
            base * (1 + percent / 100),
            base * (1 + kwargs["no_discount_percent"] / 100),
        ),
        build_item_category_keys=item_keys,
        infer_category=infer,
    )

    assert result.at[0, "РРЦ"] == pytest.approx(120)
    assert result.at[0, "Цена без скидки"] == pytest.approx(110)


def test_apply_saved_markups_uses_precomputed_category_without_reinferring():
    df = pd.DataFrame({
        "Название": ["Already categorized"],
        "Категория": ["Кронштейны"],
        "Цена": [100],
        "OnlinerID": ["123"],
    })

    result = svc.apply_saved_markups_to_df(
        df,
        load_category_markups=lambda: {"Кронштейны": 10},
        get_category_markup_config=lambda markups, category: {
            "percent": 10,
            "threshold": 0,
            "min_profit": 0,
            "no_discount_percent": 0,
            "base_mode": "wholesale",
        },
        calc_rrc_and_no_discount=lambda base, percent, **kwargs: (base + 10, base + 20),
        build_item_category_keys=item_keys,
        infer_category=lambda name: (_ for _ in ()).throw(AssertionError("unexpected inference")),
    )

    assert result.at[0, "РРЦ"] == 110
    assert result.at[0, "Цена без скидки"] == 120


def test_apply_saved_markups_to_df_can_use_onliner_market_base():
    df = pd.DataFrame({
        "Название": ["Kingston SSD"],
        "Категория": ["SSD"],
        "Цена": [100],
        "OnlinerID": [" 123 "],
    })

    result = svc.apply_saved_markups_to_df(
        df,
        load_category_markups=lambda: {
            "SSD": {
                "percent": 10,
                "threshold": 0,
                "min_profit": 0,
                "no_discount_percent": 5,
                "base_mode": "onliner_min",
            }
        },
        get_category_markup_config=lambda markups, category: markups[category],
        calc_rrc_and_no_discount=lambda base, percent, **kwargs: (
            base * (1 + percent / 100),
            base * (1 + kwargs["no_discount_percent"] / 100),
        ),
        normalize_onliner_id=lambda value: str(value).strip(),
        get_onliner_market_stats_from_cache_only=lambda oid: {"min": 200, "avg": 250, "max": 300},
        build_item_category_keys=item_keys,
        infer_category=infer,
    )

    assert result.at[0, "РРЦ"] == pytest.approx(220)
    assert result.at[0, "Цена без скидки"] == pytest.approx(210)


def test_apply_visibility_filter_hides_categories_globally():
    df = pd.DataFrame({
        "Поставщик": ["A", "A", "B"],
        "Название": ["Kingston SSD", "Logitech Mouse", "Kingston SSD"],
        "Категория": ["SSD", "Мышь", "SSD"],
    })

    result = svc.apply_visibility_filter(
        df,
        session_dir="/tmp/session",
        load_visibility_map_func=lambda session_dir: {"A": ["SSD"], "B": ["Мышь"]},
        build_item_category_keys=item_keys,
        infer_category=infer,
    )

    assert list(result["Название"]) == []


def test_apply_visibility_filter_normalizes_supplier_and_category_names():
    df = pd.DataFrame({
        "Поставщик": ["n-tech", "N-Tech"],
        "Название": ["Legacy cooler", "Mouse"],
        "Категория": ["Кулер", "Мышь"],
        "OnlinerID": ["123", "456"],
    })

    result = svc.apply_visibility_filter(
        df,
        session_dir="/tmp/session",
        load_visibility_map_func=lambda session_dir: {"N-Tech": ["Кулеры"]},
        build_item_category_keys=item_keys,
        infer_category=infer,
        normalize_supplier=lambda value: "N-Tech" if value.replace("-", "").lower() == "ntech" else value,
        normalize_category=lambda value: "Кулеры" if value == "Кулер" else value,
    )

    assert list(result["Название"]) == ["Mouse"]


def test_apply_visibility_filter_hides_category_aliases():
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "IVEN"],
        "Название": ["UPS battery", "Mouse"],
        "Категория": ["АККУМУЛЯТОРНАЯ", "Мышь"],
    })

    result = svc.apply_visibility_filter(
        df,
        session_dir="/tmp/session",
        load_visibility_map_func=lambda session_dir: {"IVEN": ["АККУМУЛЯТОР"]},
        build_item_category_keys=item_keys,
        infer_category=infer,
        normalize_category=lambda value: "АККУМУЛЯТОР" if value == "АККУМУЛЯТОРНАЯ" else value,
    )

    assert list(result["Название"]) == ["Mouse"]


def test_apply_visibility_filter_checks_existing_category_before_inferred_category():
    df = pd.DataFrame({
        "Поставщик": ["Tradex", "Tradex"],
        "Название": ["Монитор видеодомофона Dahua", "27 inch HDMI monitor"],
        "Категория": ["Видеодомофоны", "Монитор"],
    })

    result = svc.apply_visibility_filter(
        df,
        session_dir="/tmp/session",
        load_visibility_map_func=lambda session_dir: {"Tradex": ["Видеодомофоны"]},
        build_item_category_keys=item_keys,
        infer_category=lambda name: "Монитор" if "монитор" in str(name).lower() or "hdmi" in str(name).lower() else "",
    )

    assert list(result["Название"]) == ["27 inch HDMI monitor"]


def test_update_category_visibility_validates_and_updates_map():
    payload, visibility, status = svc.update_category_visibility(
        {"supplier": "A", "categories": ["SSD", " Мышь "], "hidden": True},
        {"A": ["RAM"]},
        category_sort_key=lambda value: str(value),
    )

    assert status == 200
    assert payload["status"] == "ok"
    assert visibility == {svc.GLOBAL_VISIBILITY_KEY: ["RAM", "SSD", "Мышь"]}
    assert payload["categories"] == [
        {"name": "RAM", "hidden": True},
        {"name": "SSD", "hidden": True},
        {"name": "Мышь", "hidden": True},
    ]

    payload, visibility, status = svc.update_category_visibility(
        {"supplier": "", "categories": ["SSD"]},
        {},
        category_sort_key=lambda value: str(value),
    )
    assert status == 200
    assert visibility == {svc.GLOBAL_VISIBILITY_KEY: ["SSD"]}


def test_build_category_override_items_payload_filters_and_marks_manual():
    df = pd.DataFrame({
        "Название": ["Kingston SSD", "Logitech Mouse"],
        "Поставщик": ["A", "B"],
        "Категория": ["SSD", ""],
    })

    payload = svc.build_category_override_items_payload(
        df,
        query="mouse",
        limit=10,
        overrides={"name:Logitech Mouse": "Периферия"},
        build_item_category_key=lambda row: f"name:{row.get('Название', '')}",
        infer_category=infer,
        row_category=lambda row, overrides=None: svc.row_category(
            row,
            overrides,
            item_keys,
            infer,
        ),
    )

    assert payload == {
        "items": [{
            "key": "name:Logitech Mouse",
            "name": "Logitech Mouse",
            "supplier": "B",
            "auto_category": "Мышь",
            "category": "Мышь",
            "manual": False,
        }]
    }


def test_apply_category_override_to_df_updates_matching_rows_and_keys():
    df = pd.DataFrame({
        "Название": ["Kingston SSD", "Kingston SSD"],
        "Категория": ["SSD", "SSD"],
    })

    payload, updated_df, overrides, changed = svc.apply_category_override_to_df(
        df,
        {"item_key": "name:Kingston SSD", "target_category": "Накопители"},
        overrides={},
        build_item_category_keys=item_keys,
    )

    assert payload == {"status": "ok"}
    assert changed == 2
    assert list(updated_df["Категория"]) == ["Накопители", "Накопители"]
    assert overrides == {"name:Kingston SSD": "Накопители"}


def test_apply_category_override_to_df_updates_same_normalized_name_for_all_suppliers():
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "N-Tech", "IVEN"],
        "Название": [" Controller  USB ", "Controller USB", "Different item"],
        "Категория": ["Требует сортировки", "Требует сортировки", "Прочее"],
    })
    explicit_overrides = {}

    payload, updated_df, overrides, changed = svc.apply_category_override_to_df(
        df,
        {"item_key": "sname:iven:controller usb", "target_category": "Контроллеры"},
        overrides={},
        build_item_category_keys=build_item_category_keys,
        explicit_overrides=explicit_overrides,
    )

    assert payload == {"status": "ok"}
    assert changed == 2
    assert list(updated_df["Категория"]) == ["Контроллеры", "Контроллеры", "Прочее"]
    assert explicit_overrides == {
        "name:controller usb": "Контроллеры",
        "sname:iven:controller usb": "Контроллеры",
        "sname:n-tech:controller usb": "Контроллеры",
    }
    assert overrides == explicit_overrides


def test_build_category_preview_items_payload_includes_market_stats():
    df = pd.DataFrame({
        "Название": ["Kingston SSD", "Logitech Mouse"],
        "Поставщик": ["A", "B"],
        "Категория": ["SSD", "Мышь"],
        "Цена": [100, 50],
        "РРЦ": [120, ""],
        "OnlinerID": ["111", ""],
    })

    payload = svc.build_category_preview_items_payload(
        df,
        {"categories": ["SSD", "Мышь"], "with_market": True, "limit": 10},
        overrides={},
        row_category=lambda row, overrides=None: row.get("Категория", ""),
        build_item_category_key=lambda row: f"name:{row.get('Название', '')}",
        normalize_onliner_id=lambda value: str(value or "").strip(),
        load_market_cache=lambda: {"cache": True},
        get_market_stats_from_cache_only=lambda oid, cache=None, allow_stale=True: {
            "min": 90,
            "avg": 100,
            "max": 110,
            "offers": 3,
            "min_competitors": 1,
            "avg_competitors": 2,
        },
    )

    assert payload["preview_row_count"] == 2
    assert payload["market_rows_with_onliner_id"] == 1
    assert payload["market_unique_onliner_ids"] == 1
    assert payload["no_onliner_id"] == 1
    assert payload["items"][0]["market_min"] == 90.0
    assert payload["items"][0]["market_offers"] == 3
