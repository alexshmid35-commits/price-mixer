"""Unit tests for product normalization service helpers."""

import math

import pandas as pd

from price_mixer.services.product_normalization import (
    build_item_category_keys,
    count_rows_with_duplicate_onliner_id,
    count_rows_without_onliner_id,
    infer_category,
    normalize_catalog_category_name,
    normalize_consolidated_columns,
    normalize_internal_category_name,
    normalize_name_key,
    normalize_onliner_id,
    round_price_to_90,
)


def test_normalize_onliner_id_handles_empty_and_excel_float_ids():
    assert normalize_onliner_id(None) == ""
    assert normalize_onliner_id("nan") == ""
    assert normalize_onliner_id("12345.0") == "12345"
    assert normalize_onliner_id("  abc-1  ") == "abc-1"


def test_count_rows_without_and_duplicate_onliner_ids():
    df = pd.DataFrame({
        "OnlinerID": ["100", "100.0", "", None, "200"],
        "Название": ["a", "b", "c", "d", "e"],
    })

    assert count_rows_without_onliner_id(df) == 2
    assert count_rows_with_duplicate_onliner_id(df) == 2


def test_name_and_category_keys_are_stable():
    row = {"Поставщик": "BN", "Название": "[old]  RTX   4060  "}

    assert normalize_name_key(row["Название"]) == "rtx 4060"
    assert build_item_category_keys(row) == [
        "sname:bn:rtx 4060",
        "name:rtx 4060",
    ]


def test_infer_category_priority_rules():
    assert infer_category("Корпус ATX без БП") == "Корпус"
    assert infer_category("Блок питания 750W PSU") == "Блок питания"
    assert infer_category("SSD M.2 NVMe 1TB") == "SSD"
    assert infer_category("Оперативная память DDR5 для ноутбука") == "Оперативная память"
    assert infer_category("Бумага Cactus CS-LFP80-841175 A0") == "Бумага и материалы для печати"
    assert infer_category("Аксессуары для серверов Gooxi ZA-1104") == "Аксессуары для серверов"
    assert infer_category("Анкер забивной Fischer EA М16 25шт (90163)") == "Крепеж"
    assert infer_category("Блендер Scarlett SC-HB42F82 Orange Mood") == "Блендеры"
    assert infer_category("Варочная панель Gefest СГ СН 2120") == "Варочные панели"
    assert infer_category("Кухонная плита Gefest ПГ 1200-С6") == "Кухонные плиты"
    assert infer_category("Зарядное устройство для инструмента Ставр SBC 18-6A2-01") == (
        "Зарядные устройства для инструмента"
    )
    assert infer_category("Монитор видеодомофона Optimus VMH-7.1 черный") == "Видеодомофоны"
    assert infer_category("Чехол для смартфона Magssory Aramid Case для Samsung Galaxy Z Fold 7") == (
        "Чехлы для смартфонов"
    )
    assert infer_category('Сумка для ноутбука 15.6" Defender Geek') == "Сумки и чехлы для ноутбуков"
    assert infer_category("Laptop bag Miru 17.3") == "Сумки и чехлы для ноутбуков"


def test_infer_category_repairs_raw_supplier_titles_without_false_component_hits():
    assert infer_category("Умные часы Apple Watch SE 3 GPS 44mm Midnight Al Case") == "Умные часы"
    assert infer_category("Неттоп Beelink SER5 Ryzen 5 5500U/16Gb/512SSD") == "Системный блок"
    assert infer_category("IP-камера Dahua DH-IPC-C2KP-P-0360B") == "IP-камеры"
    assert infer_category("CCTV-камера AceCop ACV 100AFZT") == "Камеры CCTV"
    assert infer_category("IP-видеорегистратор Dahua DHI-NVR2104HS") == "Видеорегистраторы"
    assert infer_category("Сетевая карта Cudy UE10A USB3.0 1xRJ-45") == "Сетевые адаптеры"
    assert infer_category("Wi-Fi Сетевой USB-адаптер TP-Link Archer T2U") == "Беспроводные адаптеры"
    assert infer_category("Коммутатор TP-Link TL-SG108") == "Коммутаторы"
    assert infer_category("Сетевой накопитель Synology DS224+") == "Сетевые накопители (NAS)"
    assert infer_category("12V / 12Ah, аккумулятор для UPS, B.B.Battery BP 12-12") == "Аккумуляторы для ИБП"
    assert infer_category("Сетевое зарядное устройство Samsung EP-TA800") == "Зарядные устройства"
    assert infer_category("Шредер Rexel Momentum X308") == "Шредеры"
    assert infer_category("Стойка для микрофона FIFINE BM66") == "Акустика"
    assert infer_category("Микрофон Fifine AM8") == "Микрофоны"


def test_infer_category_handles_supplier_price_edge_cases():
    assert infer_category('[Видеокарта] Компьютер IVEN BY Gaming White Ryzen 5/RTX 3050') == "Системный блок"
    assert infer_category('Моноблок Digma Pro Vision, 23.8" IPS, Core i5/16Gb/512SSD') == "Системный блок"
    assert infer_category("[SSD] ПЭВМ TGPC Office.Slim 96064 I-X Celeron G5905/8Gb/256SSD") == "Системный блок"
    assert infer_category("[SSD] Системный блок Iven Gaming 179730 AMD Ryzen/16Gb/1Tb SSD") == "Системный блок"
    assert infer_category("SSD M.2 2280 Patriot 1TB (ТОЛЬКО В СОСТАВЕ ПЭВМ)") == "SSD"
    assert infer_category("Кабель компьютер - сеть 220V, 1.8м, Gembird") == "Кабели и переходники"
    assert infer_category('27" LG 27U411A-B (16:9, 1920x1080, IPS, 120 Гц, HDMI+VGA)') == "Монитор"
    assert infer_category("[Монитор] Система водяного охлаждения ID-Cooling SL360") == "Охлаждение"
    assert infer_category("[SSD] Радиатор для SSD M.2 2280 Thermalright") == "Охлаждение"
    assert infer_category("[Накопители USB] WEB камера Logitech C922 Pro Stream") == "Периферия"
    assert infer_category("[Накопители USB] Разветвитель USB2.0 Ugreen US158 30345, черный") == "Кабели и переходники"
    assert infer_category("[Накопители USB] USB-хаб TP-Link UH720") == "USB-хабы"
    assert infer_category("[Накопители USB] Разветвитель USB TP-Link UH720") == "USB-хабы"
    assert infer_category("[Периферия] Разветвитель USB Ugreen CM219 35574, 4xUSB3.0 черный") == "USB-хабы"
    assert infer_category("[Накопители USB] DVDRW Asus SDRW-08D2S-U LITE, USB") == "Периферия"
    assert infer_category("[НАБОР] Набор Logitech Desktop MK120, USB, черный") == "Комплекты периферии"
    assert infer_category("[Кабели и переходники] Web-cam A4Tech PK-935HL, кабель 1.5 м") == "Периферия"
    assert infer_category("[Кабели и переходники] Wi-Fi Сетевой USB-адаптер TP-Link Archer") == "Беспроводные адаптеры"
    assert infer_category("[Кабели и переходники] Адаптер bluetooth 5.0 TP-Link UB500") == "Сеть"
    assert infer_category("[Кабели и переходники] Клавиатура A4Tech Fstyler FK25") == "Клавиатура"
    assert infer_category("[Кабели и переходники] Наушники с микрофоном Logitech") == "Наушники"
    assert infer_category("[Кабели и переходники] Система охлаждения ID-Cooling FS-04 (FS-04 PWM)") == "Охлаждение"
    assert infer_category("[Кабели и переходники] Смещенная насадка Milwaukee TRB-1 (4932471946)") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Кабели и переходники] Стойка для дрели TEH TCD8160-STD") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Кабели и переходники] Стойка для углошлифовальных машин P.I.T. P0010003") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Кабели и переходники] Переходник Milwaukee SDS Max на SDS+ (4932359490)") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Кабели и переходники] Угловой переходник Milwaukee 48062871 для дрели US") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Кабели и переходники] Удлинитель кабеля Milwaukee 49122775") == (
        "Строительный, слесарный, монтажный инструмент"
    )
    assert infer_category("[Периферия] Монитор 27\" Philips 27E1N5600HE") == "Монитор"
    assert infer_category('[Периферия] Монитор 27" Philips 27E1N5600HE, 2560x1440, IPS, Webcam') == "Монитор"
    assert infer_category('27" LG 27U631A-B (16:9, 2560x1440, IPS, 100 Гц, VESA Adapter)') == "Монитор"
    assert infer_category("[Монитор] Кронштейн для монитора ErgoSmart Double Decker") == "Кронштейны"
    assert infer_category("[Периферия] Мышь беспроводная Logitech M190") == "Мышь"
    assert infer_category("[Наушники] Колонки 2.0 Defender SPK-225, выход на наушники") == "Акустика"
    assert infer_category("[Системный блок] DDR5 16Gb KiTof2 PC-48000 6000MHz") == "Оперативная память"
    assert infer_category("[Системный блок] Компьютер IVEN BY Gaming Black Core i5/16Gb DDR5/SSD") == "Системный блок"
    assert infer_category("[Накопители USB] 64Gb Netac UM2 USB Flash") == "Накопители USB"
    assert infer_category("USB3.0 128Gb Netac U182 USB 3.0 Type-A") == "Накопители USB"
    assert infer_category("Micro SD 32 Gb Netac P500 Extreme Pro microSDHC (NT02P500PRO-032G-R) с адаптером") == "Накопители USB"
    assert infer_category("Карта памяти ADATA Premier Pro AUSDX256GUI3V30SA2-RA1 microSDXC 256GB (с адаптером)") == "Накопители USB"
    assert infer_category("[Накопители USB] 2Tb SSD A-Data SD620 Blue") == "SSD"
    assert infer_category("[Накопители USB] Внешний HDD 2Tb WD Elements Portable") == "Жесткий диск"
    assert infer_category("MB ASRock B650 Steel Legend WiFi 4xDDR5") == "Материнская плата"
    assert infer_category("MB Gigabyte H610I DDR4 PCI-Ex16 M.2") == "Материнская плата"


def test_normalize_internal_category_name_collapses_legacy_labels():
    assert normalize_internal_category_name("Компьютер") == "Системный блок"
    assert normalize_internal_category_name("USB3.2") == "Накопители USB"
    assert normalize_internal_category_name("USB2") == "Накопители USB"
    assert normalize_internal_category_name("SSD") == "SSD"


def test_normalize_catalog_category_name_uses_available_category_spelling():
    assert normalize_catalog_category_name("процессоры", ["CPU", "Процессор"]) == "Процессор"
    assert normalize_catalog_category_name("ssd", ["SSD накопители"]) == "SSD"
    assert normalize_catalog_category_name("Монитор игровой", ["Монитор"]) == "Монитор"
    assert normalize_catalog_category_name("кронштейн") == "Кронштейны"
    assert normalize_catalog_category_name("") == ""


def test_normalize_catalog_category_name_preserves_unknown_native_catalog_titles():
    assert normalize_catalog_category_name("Бумага и материалы для печати") == "Бумага и материалы для печати"
    assert normalize_catalog_category_name("Офисные кресла и стулья") == "Офисные кресла и стулья"
    assert normalize_catalog_category_name("Игровые контроллеры и аксессуары") == (
        "Игровые контроллеры и аксессуары"
    )
    assert normalize_catalog_category_name("Сетевые накопители (NAS)") == "Сетевые накопители (NAS)"
    assert normalize_catalog_category_name("Расходные материалы и аксессуары для 3D-печати") == (
        "Расходные материалы и аксессуары для 3D-печати"
    )


def test_normalize_catalog_category_name_collapses_known_onliner_synonyms():
    assert normalize_catalog_category_name("Мыши") == "Мышь"
    assert normalize_catalog_category_name("Наушники и гарнитуры") == "Наушники"
    assert normalize_catalog_category_name("Источники бесперебойного питания") == "ИБП"
    assert normalize_catalog_category_name("Сетевые адаптеры и сетевые карты") == "Сетевые адаптеры"
    assert normalize_catalog_category_name("Экосистемы умного дома, датчики, центры управления") == "Умный дом"


def test_normalize_catalog_category_name_translates_onliner_slugs_to_russian():
    assert normalize_catalog_category_name("Drillbits") == "Сверла и буры"
    assert normalize_catalog_category_name("Videodoorphone") == "Видеодомофоны"
    assert normalize_catalog_category_name("Rotaryhammers") == "Перфораторы"
    assert normalize_catalog_category_name("Laserlevel") == "Лазерные уровни"
    assert normalize_catalog_category_name("Powerstations") == "Портативные электростанции"
    assert normalize_catalog_category_name("Tools Accum") == "Аккумуляторы для инструмента"
    assert normalize_catalog_category_name("Xmaslights") == "Новогоднее освещение"
    assert normalize_catalog_category_name("Projectors") == "Проекторы"
    assert normalize_catalog_category_name("powertool_chucks") == "Строительный, слесарный, монтажный инструмент"
    assert normalize_catalog_category_name("smart_home") == "Умный дом"
    assert normalize_catalog_category_name("Angle Grinder") == "Углошлифмашины"
    assert normalize_catalog_category_name("Угловые шлифмашины (болгарки)") == "Углошлифмашины"
    assert normalize_catalog_category_name("Benchgrinder") == "Точильные станки"
    assert normalize_catalog_category_name("Body Care") == "Уход за телом"
    assert normalize_catalog_category_name("Household Tools") == "Хозяйственные инструменты"
    assert normalize_catalog_category_name("Outdoor Light") == "Уличное освещение"
    assert normalize_catalog_category_name("Уличное освещение и прожекторы") == "Уличное освещение"
    assert normalize_catalog_category_name("Powertools Sp") == "Специнструмент"
    assert normalize_catalog_category_name("Woodrouter") == "Фрезеры"
    assert normalize_catalog_category_name("Chainsaw") == "Цепные электро- и бензопилы"
    assert normalize_catalog_category_name("Electric Saw") == "Цепные электро- и бензопилы"
    assert normalize_catalog_category_name("Grinder") == "Шлифмашины"
    assert normalize_catalog_category_name("Screwdriver") == "Шуруповерты, гайковерты, электроотвертки"
    assert normalize_catalog_category_name("Watch") == "Часы"
    assert normalize_catalog_category_name("Wardrobes") == "Шкафы"
    assert normalize_catalog_category_name("Chair") == "Стулья"
    assert normalize_catalog_category_name("Art Goods") == "Товары для творчества"
    assert normalize_catalog_category_name("Table") == "Столы"
    assert normalize_catalog_category_name("Flowerpot") == "Цветочные горшки"
    assert normalize_catalog_category_name("Toolbox") == "Ящики для инструментов"
    assert normalize_catalog_category_name("Electric Panel") == "Электрические щиты"
    assert normalize_catalog_category_name("Wantenna") == "Антенны беспроводной связи"
    assert normalize_catalog_category_name("ВИДЕОДОМОФОН") == "Видеодомофоны"


def test_normalize_consolidated_columns_repairs_mojibake_headers():
    df = pd.DataFrame({"РќР°Р·РІР°РЅРёРµ": ["item"], "Р¦РµРЅР°": [10], "Р\xa0Р\xa0Р¦": [20]})

    normalized = normalize_consolidated_columns(df)

    assert list(normalized.columns) == ["Название", "Цена", "РРЦ"]


def test_round_price_to_90_preserves_legacy_rounding():
    assert round_price_to_90(302) == 300.0
    assert round_price_to_90(441) == 440.0
    assert round_price_to_90(583) == 580.0
    assert round_price_to_90(1315) == 1320.0
    assert math.isnan(round_price_to_90("not-a-number"))
