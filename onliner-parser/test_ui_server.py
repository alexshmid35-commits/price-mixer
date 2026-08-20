import ui_server


def product(product_id, category, name):
    return {
        "id": product_id,
        "schema": {"name": category},
        "full_name": name,
        "html_url": f"https://catalog.onliner.by/example/{product_id}",
    }


def test_items_count_uses_sheet_metadata_instead_of_loading_column(monkeypatch):
    class FakeSheet:
        row_count = 583410

        def col_values(self, _column):
            raise AssertionError("The full column must not be loaded for the status counter")

    ui_server.sheet_count_cache.clear()
    monkeypatch.setattr(ui_server, "load_progress_state_for_sheet", lambda _tab: None)
    monkeypatch.setattr(ui_server.parser, "authorize_google_sheets", lambda sheet_tab: FakeSheet())

    assert ui_server.get_items_count("All_Catalog") == 583409


def test_builtin_profiles_partition_every_category_once():
    presets = ui_server.build_presets()
    category_sets = [set(item["categories"]) for item in presets.values()]

    assert set(presets) == {"computer_tech", "home_appliances", "other_categories"}
    assert set.union(*category_sets) == set(ui_server.parser.CATEGORIES)
    assert not (category_sets[0] & category_sets[1])
    assert not (category_sets[0] & category_sets[2])
    assert not (category_sets[1] & category_sets[2])


def test_interrupted_job_is_reported_as_stopped():
    assert ui_server.classify_job_result(-2) == (
        "stopped",
        "Остановлено. Прогресс сохранён, можно продолжить позже.",
    )
    assert ui_server.classify_job_result(1) == (
        "failed",
        "Задача завершилась с ошибкой.",
    )


def test_resolve_target_item_prefers_exact_id(monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_fetch_target_products",
        lambda query: [product("123", "Мониторы", "Acer V176LB")],
    )

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "123",
        "name": 'Монитор 17" Acer V176LB',
        "parent_category": "Монитор",
    })

    assert result["category"] == "Мониторы"
    assert result["source"] == "catalog_api_id"


def test_resolve_target_item_uses_checked_name_match_for_stale_id(monkeypatch):
    def fetch(query):
        if query == "50533":
            return [product("3310397", "Фильтры для воды", "Гейзер 10SL")]
        return [product("3206993", "Офисные кресла и стулья", "Бюрократ CH-599AXSN/TW-11 (черный)")]

    monkeypatch.setattr(ui_server, "_fetch_target_products", fetch)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "50533",
        "name": "Бюрократ CH-599AXSN/TW-11, черный",
        "parent_category": "БЮРОКРАТ",
    })

    assert result["onliner_id"] == "50533"
    assert result["category"] == "Офисные кресла и стулья"
    assert result["source"] == "catalog_api_name"


def test_resolve_target_item_accepts_exact_id_found_by_name(monkeypatch):
    def fetch(query):
        if query == "95777":
            return [product("5068159", "Компьютеры", "TGPC Osprey 95077 A-X")]
        return [product("95777", "Игровые контроллеры и аксессуары", "Logitech Wireless Gamepad F710")]

    monkeypatch.setattr(ui_server, "_fetch_target_products", fetch)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "95777",
        "name": "Геймпад Logitech F710 белый/черный (940-000172)",
        "parent_category": "ГЕЙМПАД",
    })

    assert result["category"] == "Игровые контроллеры и аксессуары"
    assert result["source"] == "catalog_api_id"


def test_resolve_target_item_strict_api_accepts_exact_id_found_by_name(monkeypatch):
    def fetch(query):
        if query == "95777":
            return []
        return [product("95777", "Игровые контроллеры и аксессуары", "Logitech Wireless Gamepad F710")]

    monkeypatch.setattr(ui_server, "_fetch_target_products", fetch)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "95777",
        "name": "Геймпад Logitech F710 белый/черный (940-000172)",
        "parent_category": "ГЕЙМПАД",
        "strict_api": True,
    })

    assert result["category"] == "Игровые контроллеры и аксессуары"
    assert result["source"] == "catalog_api_id"


def test_resolve_target_item_uses_trusted_parent_when_product_is_gone(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3771296",
        "name": "1.6Tb SSD Intel D7-P5620 SSDPF2KE016T1",
        "parent_category": "SSD",
    })

    assert result["category"] == "SSD"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_prefers_trusted_parent_over_loose_name_match(monkeypatch):
    def fetch(query):
        if query == "2031434":
            return []
        return [product("999", "Источники питания для светодиодных лент", "Maytoni PSI001 24В 250Вт IP67")]

    monkeypatch.setattr(ui_server, "_fetch_target_products", fetch)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "2031434",
        "name": "Блок питания 250Вт, ACD TF0250, 80 Plus, APFC, TFX",
        "parent_category": "Блок питания",
    })

    assert result["category"] == "Блоки питания"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_recognizes_network_card_from_product_name(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "2168078",
        "name": "Сетевая карта Asus XG-C100F, 10GBps, PCIx1",
        "parent_category": "СЕТЕВАЯ",
    })

    assert result["category"] == "Сетевые адаптеры и сетевые карты"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_recognizes_cooling_radiator_from_product_name(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3907574",
        "name": "Радиатор Alseye AS3647-P4HCAL2U-JYR81, LGA3647, 205W",
        "parent_category": "Охлаждение",
    })

    assert result["category"] == "Кулеры"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_recognizes_ip_phone_from_product_name(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "4897419",
        "name": "Телефон IP Fanvil DB20-H, черный",
        "parent_category": "ТЕЛЕФОН",
    })

    assert result["category"] == "Проводные телефоны"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_recognizes_drive_bay_mount_from_product_name(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3481361",
        "name": 'Крeпление 2.5" в отсек 3.5", Gembird MF-321',
        "parent_category": "КРEПЛЕНИЕ",
    })

    assert result["category"] == "Моддинг, аксессуары для системных блоков"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_uses_trusted_parent_when_api_is_unavailable(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: None)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3771296",
        "name": "1.6Tb SSD Intel D7-P5620 SSDPF2KE016T1",
        "parent_category": "SSD",
    })

    assert result["category"] == "SSD"
    assert result["source"] == "category_parent_hint"


def test_resolve_target_item_strict_api_does_not_use_parent_hint(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3771296",
        "name": "1.6Tb SSD Intel D7-P5620 SSDPF2KE016T1",
        "parent_category": "SSD",
        "strict_api": True,
    })

    assert result is None


def test_resolve_target_item_strict_api_marks_network_unavailable(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: None)

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "3771296",
        "name": "1.6Tb SSD Intel D7-P5620 SSDPF2KE016T1",
        "parent_category": "SSD",
        "strict_api": True,
    })

    assert result == {"onliner_id": "3771296", "_lookup_unavailable": True}


def test_resolve_target_item_leaves_unsafe_parent_for_manual_review(monkeypatch):
    monkeypatch.setattr(ui_server, "_fetch_target_products", lambda query: [])

    result = ui_server.resolve_target_item_by_id({
        "onliner_id": "1349215",
        "name": "Moxa DRP-240-48",
        "parent_category": "MOXA",
    })

    assert result is None
