from contextlib import contextmanager
import re

from price_mixer.services import review_candidates as svc


def compact(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def raw_paren_tokens(text):
    return [match.group(1) for match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,80})\)", str(text or ""))]


def test_cpu_brand_model_key_extracts_common_models():
    assert svc.cpu_brand_model_key("Процессор Intel Core i5-12400F BOX", compact) == ("intel", "i512400f")
    assert svc.cpu_brand_model_key("AMD Ryzen 5 PRO 5655G OEM", compact) == ("amd", "ryzen5pro5655g")
    assert svc.cpu_brand_model_key("EPYC Series Model 7282", compact) == ("", "epyc7282")
    assert svc.cpu_brand_model_key("No CPU here", compact) == ("", "")


def test_cpu_article_package_and_looks_like_helpers():
    assert svc.cpu_article_code("Intel CPU (BX8071512400F) BOX", compact) == "bx8071512400f"
    assert svc.cpu_article_code("Intel CPU (BOX)", compact) == ""
    assert svc.cpu_package_type("Ryzen 5 5600 OEM") == "oem"
    assert svc.cpu_package_type("Core i5 boxed") == "box"
    assert svc.looks_like_cpu_name("Процессор AMD Ryzen 5 5600") is True
    assert svc.looks_like_cpu_name("TGPC Action компьютер Ryzen 5") is False


def test_find_cpu_review_candidates_uses_db_seeds_and_package_sorting():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                ("1", "AMD Ryzen 5 5600 OEM", "https://cpu-oem.test"),
                ("2", "AMD Ryzen 5 5600 BOX", "https://cpu-box.test"),
                ("3", "AMD Ryzen 7 5700X OEM", "https://wrong-model.test"),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_cpu_review_candidates(
        "AMD Ryzen 5 5600 OEM",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {"id": "2", "name": "AMD Ryzen 5 5600 BOX", "url": "https://dup.test", "score": 0.5},
            {"id": "4", "name": "Intel Core i5-12400F OEM", "url": "https://intel.test", "score": 0.99},
        ],
        db_find_exact_id_for_name=lambda name: {
            "id": "5",
            "name": "AMD Ryzen 5 5600 OEM",
            "url": "https://exact.test",
            "score": 0.97,
            "source": "exact",
        },
        normalize_compact_name=compact,
        infer_category=lambda name: "Процессор" if "Ryzen" in name or "Core" in name else "Без категории",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["5", "1", "2"]
    assert result[0]["package"] == "oem"
    assert result[0]["score"] == 0.999
    assert result[1]["source"] == "cpu_db_seed"
    assert result[2]["package"] == "box"


def test_find_cpu_review_candidates_returns_empty_without_model():
    assert svc.find_cpu_review_candidates(
        "Generic processor",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        normalize_compact_name=compact,
        infer_category=lambda name: "",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_board_brand_model_key_extracts_model_features_and_specs():
    key = svc.board_brand_model_key("MB Gigabyte B760M AORUS ELITE AX DDR5 Socket-1700 (B760)")

    assert key["brand"] == "gigabyte"
    assert key["model"] == "b760maoruseliteaxddr5"
    assert key["model_text"] == "B760M AORUS ELITE AX DDR5"
    assert key["chipset"] == "b760"
    assert key["socket"] == "1700"
    assert key["ddr"] == "ddr5"
    assert key["wifi"] is True
    assert {"aorus", "elite", "ax"}.issubset(key["features"])


def test_find_board_review_candidates_scores_and_filters_candidates():
    pool = [
        {
            "id": "1",
            "name": "Gigabyte B760M AORUS ELITE AX DDR5 Socket-1700 (B760)",
            "url": "https://board-exact.test",
            "score": 0.5,
        },
        {
            "id": "2",
            "name": "Gigabyte B760M AORUS ELITE DDR5 Socket-1700 (B760)",
            "url": "https://board-no-wifi.test",
            "score": 0.99,
        },
        {
            "id": "3",
            "name": "Gigabyte B760M DS3H AX DDR5 Socket-1700 (B760)",
            "url": "https://board-close.test",
            "score": 0.91,
        },
        {
            "id": "4",
            "name": "ASUS B760M AORUS ELITE AX DDR5 Socket-1700 (B760)",
            "url": "https://wrong-brand.test",
            "score": 0.99,
        },
    ]

    result = svc.find_board_review_candidates(
        "Gigabyte B760M AORUS ELITE AX DDR5 Socket-1700 (B760)",
        top_n=5,
        db_find_top_candidates=lambda *args, **kwargs: pool,
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Материнская плата",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["chipset"] == "b760"
    assert result[0]["socket"] == "1700"
    assert result[0]["ddr"] == "ddr5"
    assert result[0]["wifi"] is True
    assert {"aorus", "elite", "ax"}.issubset(set(result[0]["features"]))


def test_find_board_review_candidates_returns_empty_without_brand_or_model():
    assert svc.find_board_review_candidates(
        "Unknown motherboard",
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Материнская плата",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_monitor_brand_model_key_extracts_specs_and_code():
    key = svc.monitor_brand_model_key('27" LG UltraGear 27GP850-B (27GP850-B) 2560x1440 165Hz White')

    assert key == {
        "brand": "lg",
        "model": "ultragear27gp850b",
        "model_text": "ULTRAGEAR 27GP850-B",
        "code": "27gp850b",
        "size": "27",
        "resolution": "2560x1440",
        "hz": "165",
        "white": True,
    }


def test_find_monitor_review_candidates_uses_db_seed_and_scores_specs():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                ("1", '27" LG UltraGear 27GP850-B (27GP850-B) 2560x1440 165Hz', "https://monitor-exact.test"),
                ("2", '24" LG UltraGear 24GP850-B (24GP850-B) 1920x1080 144Hz', "https://monitor-small.test"),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_monitor_review_candidates(
        '27" LG UltraGear 27GP850-B (27GP850-B) 2560x1440 165Hz',
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {"id": "3", "name": '27" ASUS UltraGear 27GP850-B 2560x1440 165Hz', "url": "https://wrong-brand.test", "score": 0.99},
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Монитор",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "mon_db_exact"
    assert result[0]["code"] == "27gp850b"
    assert result[0]["size"] == "27"
    assert result[0]["resolution"] == "2560x1440"
    assert result[0]["hz"] == "165"


def test_find_monitor_review_candidates_returns_empty_without_brand_or_model():
    assert svc.find_monitor_review_candidates(
        "Generic display",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Монитор",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_gpu_brand_model_key_extracts_vendor_model_sku_and_series():
    key = svc.gpu_brand_model_key("Gigabyte GeForce RTX 4070 Ti AERO OC 12GB White (GV-N407TAERO OC-12GD)")

    assert key == {
        "gpu_brand": "nvidia",
        "vendor": "gigabyte",
        "gpu_model": "rtx4070ti",
        "series": "aero",
        "sku": "gvn407taerooc12gd",
        "memory_gb": "12",
        "white": True,
        "oc": True,
    }


def test_find_gpu_review_candidates_uses_db_seed_and_filters_gigabyte_sku_mismatch():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "Gigabyte GeForce RTX 4070 Ti AERO OC 12GB White (GV-N407TAERO OC-12GD)",
                    "https://gpu-exact.test",
                ),
                (
                    "2",
                    "Gigabyte GeForce RTX 4070 Ti GAMING OC 12GB (GV-N407TGAMING OC-12GD)",
                    "https://gpu-wrong-sku.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_gpu_review_candidates(
        "Gigabyte GeForce RTX 4070 Ti AERO OC 12GB White (GV-N407TAERO OC-12GD)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "ASUS GeForce RTX 4070 Ti AERO OC 12GB White",
                "url": "https://wrong-vendor.test",
                "score": 0.99,
            }
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Видеокарта",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "gpu_db_exact"
    assert result[0]["series"] == "aero"
    assert result[0]["sku"] == "gvn407taerooc12gd"
    assert result[0]["memory_gb"] == "12"
    assert result[0]["white"] is True


def test_find_gpu_review_candidates_returns_empty_without_vendor_or_model():
    assert svc.find_gpu_review_candidates(
        "Generic graphics card",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Видеокарта",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_ram_brand_model_key_extracts_sku_specs_and_flags():
    key = svc.ram_brand_model_key("Kingston Fury Beast RGB DDR5 2x16GB 6000MHz CL36 White (KF560C36BWEAK2-32)")

    assert key == {
        "ddr": "ddr5",
        "brand": "kingston",
        "sku": "kf560c36bweak232",
        "capacity_gb": "16",
        "kit_modules": "2",
        "mhz": "6000",
        "cl": "36",
        "series": "furybeastrgb",
        "white": True,
        "rgb": True,
        "ecc": False,
        "reg": False,
    }


def test_find_ram_review_candidates_keeps_exact_sku_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "Kingston Fury Beast RGB DDR5 2x16GB 6000MHz CL36 White (KF560C36BWEAK2-32)",
                    "https://ram-exact.test",
                ),
                (
                    "2",
                    "Kingston Fury Beast RGB DDR4 2x16GB 3600MHz CL18 (KF436C18BBAK2-32)",
                    "https://ram-ddr4.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_ram_review_candidates(
        "Kingston Fury Beast RGB DDR5 2x16GB 6000MHz CL36 White (KF560C36BWEAK2-32)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "Kingston Fury Beast RGB DDR5 2x16GB 6000MHz CL36",
                "url": "https://ram-no-sku.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Оперативная память",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "ram_db_exact"
    assert result[0]["sku"] == "kf560c36bweak232"
    assert result[0]["mhz"] == "6000"
    assert result[0]["capacity_gb"] == "16"


def test_find_ram_review_candidates_returns_empty_without_brand_or_ddr():
    assert svc.find_ram_review_candidates(
        "Generic memory module",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Оперативная память",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_ssd_brand_model_key_extracts_code_model_capacity_external():
    key = svc.ssd_brand_model_key(
        "ADATA SU800 SSD 512GB (ASU800SS-512GT-C)",
        normalize_compact_name=compact,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )

    assert key == {
        "brand": "adata",
        "code": "asu800ss512gtc",
        "model": "su800",
        "capacity": "512gb",
        "external": False,
    }

    external_key = svc.ssd_brand_model_key(
        "Внешний Samsung Portable SSD 1TB (MU-PC1T0T)",
        normalize_compact_name=compact,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )
    assert external_key["brand"] == "samsung"
    assert external_key["code"] == "mupc1t0t"
    assert external_key["capacity"] == "1tb"
    assert external_key["external"] is True


def test_find_ssd_review_candidates_prefers_exact_code_and_filters_different_code():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "ADATA SU800 SSD 512GB (ASU800SS-512GT-C)",
                    "https://ssd-exact.test",
                ),
                (
                    "2",
                    "ADATA SU800 SSD 256GB (ASU800SS-256GT-C)",
                    "https://ssd-wrong-code.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_ssd_review_candidates(
        "ADATA SU800 SSD 512GB (ASU800SS-512GT-C)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "ADATA SU800 SSD 512GB",
                "url": "https://ssd-soft.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "Samsung SU800 SSD 512GB (ASU800SS-512GT-C)",
                "url": "https://wrong-brand.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        normalize_compact_name=compact,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "ssd_db_seed"
    assert result[0]["code"] == "asu800ss512gtc"
    assert result[0]["model"] == "su800"
    assert result[0]["capacity"] == "512gb"


def test_find_ssd_review_candidates_fallback_requires_model_or_capacity():
    result = svc.find_ssd_review_candidates(
        "Crucial BX500 SSD 1TB",
        top_n=5,
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "1",
                "name": "Crucial BX500 SSD 1TB",
                "url": "https://ssd-match.test",
                "score": 0.4,
            },
            {
                "id": "2",
                "name": "Crucial SSD",
                "url": "https://ssd-no-anchor.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        normalize_compact_name=compact,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["model"] == "bx500"
    assert result[0]["capacity"] == "1tb"


def test_find_ssd_review_candidates_returns_empty_without_brand_or_code():
    assert svc.find_ssd_review_candidates(
        "Generic solid state drive 1TB",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        normalize_compact_name=compact,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    ) == []


def test_psu_brand_model_key_extracts_specs_and_code():
    key = svc.psu_brand_model_key(
        "DeepCool PN750M 750W 80 Plus Gold Full Modular ATX 3.1 White (R-PN750M-FC0W-EU)"
    )

    assert key == {
        "brand": "deepcool",
        "watt": "750",
        "eff": "gold",
        "modular": "full",
        "code": "rpn750mfc0weu",
        "series": "",
        "form_factor": "atx",
        "atx": "3.1",
        "white": True,
    }


def test_psu_code_match_allows_common_suffix_variants():
    assert svc.psu_code_match("R-PN750M-FC0W-EU", "R-PN750M-FC0W") is True
    assert svc.psu_code_match("ZM750-GV", "ZM750-GV-BK") is True
    assert svc.psu_code_match("R-PN750M-FC0W-EU", "R-PN850M-FC0W-EU") is False


def test_find_psu_review_candidates_keeps_exact_code_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "DeepCool PN750M 750W 80 Plus Gold Full Modular ATX 3.1 White (R-PN750M-FC0W-EU)",
                    "https://psu-exact.test",
                ),
                (
                    "2",
                    "DeepCool PN850M 850W 80 Plus Gold Full Modular ATX 3.1 White (R-PN850M-FC0W-EU)",
                    "https://psu-wrong-watt.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_psu_review_candidates(
        "DeepCool PN750M 750W 80 Plus Gold Full Modular ATX 3.1 White (R-PN750M-FC0W-EU)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "DeepCool PN750M 750W 80 Plus Bronze Full Modular ATX 3.1 White",
                "url": "https://wrong-eff.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "Zalman PN750M 750W 80 Plus Gold Full Modular ATX 3.1 White",
                "url": "https://wrong-brand.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Блок питания",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "psu_db_exact"
    assert result[0]["watt"] == "750"
    assert result[0]["eff"] == "gold"
    assert result[0]["modular"] == "full"
    assert result[0]["code"] == "rpn750mfc0weu"


def test_find_psu_review_candidates_returns_empty_without_brand_or_watt():
    assert svc.find_psu_review_candidates(
        "Generic power supply",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Блок питания",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_case_brand_model_key_extracts_code_series_form_factor_psu_and_colors():
    key = svc.case_brand_model_key("DeepCool CH360 Micro-ATX White с Б/П 500W (R-CH360-WH)")

    assert key == {
        "brand": "deepcool",
        "code": "rch360wh",
        "series": "ch360",
        "form_factor": "matx",
        "with_psu": True,
        "watt": "500",
        "white": True,
        "colors": {"white"},
    }


def test_case_code_match_handles_leading_r_sku_variants():
    assert svc.case_code_match("R-CH360-WH", "CH360-WH") is True
    assert svc.case_code_match("DP-ATX-MATREXX30", "DPATXMATREXX30") is True
    assert svc.case_code_match("R-CH360-WH", "R-CH160-WH") is False


def test_looks_like_case_name_uses_prefix_markers_and_short_model_lines():
    assert svc.looks_like_case_name("Корпус DeepCool CH360 White") is True
    assert svc.looks_like_case_name("DeepCool CH360 Micro-ATX White") is True
    assert svc.looks_like_case_name("Montech Air 1000 tempered glass") is True
    assert svc.looks_like_case_name("DeepCool AG400 CPU Cooler") is False


def test_find_case_review_candidates_keeps_exact_code_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "DeepCool CH360 Micro-ATX White с Б/П 500W (R-CH360-WH)",
                    "https://case-exact.test",
                ),
                (
                    "2",
                    "DeepCool CH360 Micro-ATX Black с Б/П 500W (R-CH360-BK)",
                    "https://case-wrong-color.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_case_review_candidates(
        "DeepCool CH360 Micro-ATX White с Б/П 500W (R-CH360-WH)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "DeepCool CH360 Micro-ATX White без блока питания (R-CH360-WH)",
                "url": "https://case-no-psu.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "Zalman CH360 Micro-ATX White с Б/П 500W (R-CH360-WH)",
                "url": "https://case-wrong-brand.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Корпус",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "case_db_exact"
    assert result[0]["code"] == "rch360wh"
    assert result[0]["series"] == "ch360"
    assert result[0]["form_factor"] == "matx"
    assert result[0]["colors"] == ["white"]


def test_find_case_review_candidates_returns_empty_without_brand():
    assert svc.find_case_review_candidates(
        "Generic computer case",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Корпус",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_hdd_brand_model_key_extracts_code_capacity_external_and_form():
    key = svc.hdd_brand_model_key(
        'Seagate BarraCuda HDD 2TB 3.5" (ST2000DM008)',
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )

    assert key == {
        "brand": "seagate",
        "code": "st2000dm008",
        "capacity": "2tb",
        "external": False,
        "form": "35",
    }

    external_key = svc.hdd_brand_model_key(
        'ADATA HV320 Portable HDD 1TB 2.5" (AHV320-1TU31-CBK)',
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )
    assert external_key["brand"] == "adata"
    assert external_key["code"] == "ahv3201tu31cbk"
    assert external_key["capacity"] == "1tb"
    assert external_key["external"] is True
    assert external_key["form"] == "25"


def test_hdd_helpers_reject_ssd_and_nvme_names():
    assert svc.looks_like_hdd_name("SSD Samsung 1TB") is False
    assert svc.looks_like_hdd_name("NVMe WD Black 1TB") is False
    assert svc.looks_like_hdd_name("Жесткий диск Seagate 2TB") is True
    assert svc.hdd_brand_model_key("WD Blue NVMe M.2 1TB") == {
        "brand": "",
        "code": "",
        "capacity": "",
        "external": False,
        "form": "",
    }


def test_find_hdd_review_candidates_keeps_exact_code_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    'Seagate BarraCuda HDD 2TB 3.5" (ST2000DM008)',
                    "https://hdd-exact.test",
                ),
                (
                    "2",
                    'Seagate BarraCuda HDD 4TB 3.5" (ST4000DM004)',
                    "https://hdd-wrong-capacity.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_hdd_review_candidates(
        'Seagate BarraCuda HDD 2TB 3.5" (ST2000DM008)',
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": 'WD BarraCuda HDD 2TB 3.5" (ST2000DM008)',
                "url": "https://wrong-brand.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": 'Seagate Portable HDD 2TB 2.5" (ST2000LM007)',
                "url": "https://wrong-external-form.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Жесткий диск",
        normalize_catalog_category_name=lambda name: name,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "hdd_db_seed"
    assert result[0]["code"] == "st2000dm008"
    assert result[0]["capacity"] == "2tb"


def test_find_hdd_review_candidates_returns_empty_without_brand_or_code():
    assert svc.find_hdd_review_candidates(
        "Generic hard drive 1TB",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Жесткий диск",
        normalize_catalog_category_name=lambda name: name,
        raw_paren_article_tokens=raw_paren_tokens,
        is_spec_code=lambda value: False,
    ) == []


def test_printer_mfp_brand_model_key_extracts_brand_article_and_model():
    key = svc.printer_mfp_brand_model_key("МФУ Canon i-SENSYS MF3010 (5252B004), лазерный")

    assert key == {
        "brand": "canon",
        "article": "5252b004",
        "model_compact": "isensysmf3010",
        "model_display": "i-SENSYS MF3010",
    }


def test_printer_mfp_category_helpers_use_text_and_fallback_category():
    assert svc.looks_like_printer_or_mfp_name("Принтер HP LaserJet") is True
    assert svc.looks_like_printer_or_mfp_name("Сканер Epson") is False
    assert svc.printer_mfp_catalog_category_ok("Canon multifunction device") is True
    assert svc.printer_mfp_catalog_category_ok(
        "Canon i-SENSYS MF3010",
        infer_category=lambda name: "Принтер и МФУ",
        normalize_catalog_category_name=lambda name: name,
    ) is True


def test_find_printer_review_candidates_keeps_exact_article_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "МФУ Canon i-SENSYS MF3010 (5252B004)",
                    "https://printer-exact.test",
                ),
                (
                    "2",
                    "МФУ Canon PIXMA G3410 (2315C025)",
                    "https://printer-wrong-model.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_printer_review_candidates(
        "МФУ Canon i-SENSYS MF3010 (5252B004)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "МФУ HP i-SENSYS MF3010 (5252B004)",
                "url": "https://wrong-brand.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "МФУ Canon i-SENSYS MF3010",
                "url": "https://model-only.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Принтер и МФУ",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "printer_db_seed"
    assert result[0]["code"] == "5252b004"


def test_find_printer_review_candidates_returns_empty_without_brand_article_or_model():
    assert svc.find_printer_review_candidates(
        "Generic device",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Принтер и МФУ",
        normalize_catalog_category_name=lambda name: name,
    ) == []


def test_cooler_brand_model_key_extracts_code_tdp_and_color():
    key = svc.cooler_brand_model_key(
        "Кулер DeepCool AG400 BK 220W TDP (R-AG400-BKNNMN-G-1)",
        raw_paren_article_tokens=raw_paren_tokens,
    )

    assert key == {
        "brand": "deepcool",
        "code": "rag400bknnmng1",
        "tdp": "220",
        "colors": {"black"},
        "white": False,
    }


def test_cooler_helpers_detect_air_and_liquid_cpu_cooling():
    assert svc.cooler_paren_looks_socket_bundle("LGA1700/AM4/AM5") is True
    assert svc.is_strong_cooler_paren_code("R-AG400-BKNNMN-G-1") is True
    assert svc.looks_like_cooler_name("Кулер DeepCool AG400") is True
    assert svc.looks_like_cooler_name("Корпус DeepCool") is False
    assert svc.looks_like_cooler_name("Вентилятор для корпуса Montech AX140 PWM") is True
    assert svc.cooler_catalog_category_ok(
        "Вентилятор для корпуса Montech AX140 PWM",
        infer_category=lambda name: "Охлаждение",
        normalize_catalog_category_name=lambda name: name,
    ) is True
    assert svc.looks_like_liquid_cpu_cooling_name("СЖО Arctic Liquid Freezer III 360") is True
    assert svc.looks_like_liquid_cpu_cooling_name("Кулер DeepCool AG400") is False


def test_cooler_brand_model_key_extracts_case_fan_and_kit_codes():
    montech = svc.cooler_brand_model_key(
        "Вентилятор 140mm Montech AX140 PWM (MNT-AX140-B) Black",
        raw_paren_article_tokens=raw_paren_tokens,
    )
    idcooling = svc.cooler_brand_model_key(
        "Вентилятор 120mm ID-Cooling AF-127-ARGB-K TRIO (НАБОР 3 в 1) BOX",
        raw_paren_article_tokens=raw_paren_tokens,
    )

    assert montech["brand"] == "montech"
    assert montech["code"] == "mntax140b"
    assert idcooling["brand"] == "idcooling"
    assert idcooling["code"] == "af127argbk"


def test_find_cooler_review_candidates_keeps_exact_code_and_filters_mismatches():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, _sql, _params):
            return FakeCursor([
                (
                    "1",
                    "Кулер DeepCool AG400 BK 220W TDP (R-AG400-BKNNMN-G-1)",
                    "https://cooler-exact.test",
                ),
                (
                    "2",
                    "Кулер DeepCool AG620 BK 260W TDP (R-AG620-BKNNMN-G-1)",
                    "https://cooler-wrong-code.test",
                ),
            ])

    @contextmanager
    def db_connection():
        yield FakeConnection()

    result = svc.find_cooler_review_candidates(
        "Кулер DeepCool AG400 BK 220W TDP (R-AG400-BKNNMN-G-1)",
        top_n=5,
        db_connection=db_connection,
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "3",
                "name": "Кулер ID-Cooling AG400 BK 220W TDP (R-AG400-BKNNMN-G-1)",
                "url": "https://wrong-brand.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "СЖО DeepCool AG400 BK 220W TDP",
                "url": "https://wrong-liquid.test",
                "score": 0.99,
            },
        ],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Кулер",
        normalize_catalog_category_name=lambda name: name,
        raw_paren_article_tokens=raw_paren_tokens,
    )

    assert [item["id"] for item in result] == ["1"]
    assert result[0]["score"] == 0.999
    assert result[0]["source"] == "cooler_db_seed"
    assert result[0]["code"] == "rag400bknnmng1"
    assert result[0]["tdp"] == "220"


def test_find_cooler_review_candidates_returns_empty_without_brand_or_code():
    assert svc.find_cooler_review_candidates(
        "Generic CPU heatsink",
        db_connection=lambda: None,
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Кулер",
        normalize_catalog_category_name=lambda name: name,
        raw_paren_article_tokens=raw_paren_tokens,
    ) == []


def test_peripheral_helpers_use_name_markers_and_catalog_categories():
    assert svc.looks_like_peripheral_name("Игровая клавиатура Logitech") is True
    assert svc.looks_like_peripheral_name("Монитор Logitech") is False
    assert svc.peripheral_catalog_category_ok(
        "Logitech MX Master",
        infer_category=lambda name: "Мышь",
        normalize_catalog_category_name=lambda name: name,
    ) is True
    assert svc.peripheral_catalog_category_ok("Bluetooth speaker") is True


def test_find_peripheral_review_candidates_filters_low_score_and_non_peripherals():
    result = svc.find_peripheral_review_candidates(
        "Logitech MX Master 3S Mouse",
        top_n=5,
        db_find_exact_id_for_name=lambda name: {
            "id": "1",
            "name": "Logitech MX Master 3S Mouse",
            "url": "https://mouse-exact.test",
            "score": 0.1,
            "source": "exact_name",
        },
        db_find_top_candidates=lambda *args, **kwargs: [
            {
                "id": "2",
                "name": "Logitech MX Anywhere Mouse",
                "url": "https://mouse-fuzzy.test",
                "score": 0.7,
            },
            {
                "id": "3",
                "name": "Logitech Monitor",
                "url": "https://not-peripheral.test",
                "score": 0.99,
            },
            {
                "id": "4",
                "name": "Logitech Mouse Pad",
                "url": "https://low-score.test",
                "score": 0.2,
            },
        ],
        infer_category=lambda name: "Мышь" if "Mouse" in name else "Монитор",
        normalize_catalog_category_name=lambda name: name,
    )

    assert [item["id"] for item in result] == ["2", "1"]
    assert result[0]["source"] == "peripheral_db"
    assert result[1]["source"] == "exact_name"


def test_find_peripheral_review_candidates_returns_empty_for_blank_name():
    assert svc.find_peripheral_review_candidates(
        "",
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        infer_category=lambda name: "Мышь",
        normalize_catalog_category_name=lambda name: name,
    ) == []
