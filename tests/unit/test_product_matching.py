"""Unit tests for product matching helpers."""

from price_mixer.services import product_matching as svc
from price_mixer.services.helpers import extract_article, extract_article_candidates


def brand_token(text):
    words = str(text or "").split()
    return words[0] if words else ""


def test_name_and_model_tokens_filter_noise_and_preserve_codes():
    assert svc.name_tokens("Клавиатура Logitech K380 White") == ["клавиатура", "logitech", "k380"]
    assert svc.normalize_compact_name("RTX 4070 Ti") == "rtx4070ti"
    assert svc.paren_chunks("GPU (GV-N4070WF3OC-12GD) white") == ["GV-N4070WF3OC-12GD"]
    assert "gvn4070wf3oc12gd" in svc.model_hint_tokens(
        "GPU (GV-N4070WF3OC-12GD)",
        extract_article_candidates=extract_article_candidates,
    )


def test_article_and_raw_search_tokens_skip_specs_and_measurements():
    assert svc.is_spec_code("USB31GEN2") is True
    raw_tokens = svc.raw_search_tokens("Кулер ID-Cooling SE-224-XTS 220W")
    assert "SE-224-XTS" in raw_tokens
    assert "220W" not in raw_tokens

    article_tokens = svc.article_like_tokens(
        "GPU Gigabyte GV-N4070WF3OC-12GD 12GB",
        extract_article_candidates=extract_article_candidates,
    )
    assert "gvn4070wf3oc12gd" in article_tokens
    assert "12gb" not in article_tokens


def test_color_capacity_and_category_helpers():
    assert svc.capacity_tokens("SSD 1TB / HDD 500GB / eMMC 1.0GB") == {"1tb", "500gb", "1gb"}
    assert svc.color_tokens("черный корпус / black case") == {"black"}
    assert svc.extract_product_category("Корпус DeepCool") == svc.extract_product_category("case DeepCool")
    assert svc.extract_product_category("Корпус DeepCool") != svc.extract_product_category("Блок питания DeepCool")


def test_calc_name_match_handles_article_category_and_tgpc_guards():
    article_match = svc.calc_name_match(
        "МФУ Canon i-SENSYS MF3010 (5252B004)",
        "МФУ Canon i-SENSYS MF3010 (5252B004)",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    assert article_match == {"score": 1.0, "match": True, "reason": "article"}

    category_mismatch = svc.calc_name_match(
        "Корпус DeepCool CH360",
        "Блок питания DeepCool 750W",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    assert category_mismatch["reason"] == "category_mismatch"
    assert category_mismatch["match"] is False

    tgpc_mismatch = svc.calc_name_match(
        "91479 I-X RTX 5070Ti 16Gb",
        "91479 I-X RTX 5060 8Gb",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    assert tgpc_mismatch == {"score": 0.35, "match": False, "reason": "tgpc_gpu_mismatch"}


def test_calc_name_match_uses_apple_base_article_before_region_suffix():
    air = svc.calc_name_match(
        "Ноутбук Apple MacBook Air 13.6 A3240 M4 Sky Blue (MC6U4LL/A)",
        "Ноутбук Apple MacBook Air 13.6 M4 Sky Blue MC6U4",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    pro_cn = svc.calc_name_match(
        "Ноутбук Apple MacBook Pro 16 A3403 M4 Pro Space Black CN (MX2Y3HN/A)",
        "Ноутбук Apple MacBook Pro 16 M4 Pro Space Black MX2Y3",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    pro_silver = svc.calc_name_match(
        "Ноутбук Apple MacBook Pro A3403 M4 Pro Silver (MX2T3HN/A)",
        "Ноутбук Apple MacBook Pro A3403 M4 Pro Silver MX2T3",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    different_sku = svc.calc_name_match(
        "Ноутбук Apple MacBook Pro 16 A3403 M4 Pro Space Black CN (MX2Y3HN/A)",
        "Ноутбук Apple MacBook Pro A3403 M4 Pro Silver MX2T3",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert svc.apple_article_base_tokens("Apple MacBook (MC6U4LL/A)") == {"mc6u4"}
    assert svc.apple_article_base_tokens("Apple MacBook CN (MX2Y3HN/A)") == {"mx2y3"}
    assert svc.apple_article_base_tokens("Apple MacBook Silver (MX2T3HN/A)") == {"mx2t3"}
    assert "a3403" not in svc.apple_article_base_tokens("Apple MacBook Pro A3403 (MX2T3HN/A)")
    assert "mc6u4" in svc.article_like_tokens(
        "Ноутбук Apple MacBook Air 13.6 A3240 M4 Sky Blue (MC6U4LL/A)",
        extract_article_candidates=extract_article_candidates,
    )
    assert "mc6u4" in svc.raw_search_tokens(
        "Ноутбук Apple MacBook Air 13.6 A3240 M4 Sky Blue (MC6U4LL/A)"
    )
    assert "mx2y3" in svc.raw_search_tokens(
        "Ноутбук Apple MacBook Pro 16 A3403 M4 Pro Space Black CN (MX2Y3HN/A)"
    )
    assert "mx2t3" in svc.raw_search_tokens(
        "Ноутбук Apple MacBook Pro A3403 M4 Pro Silver (MX2T3HN/A)"
    )
    assert air == {"score": 1.0, "match": True, "reason": "apple_article"}
    assert pro_cn == {"score": 1.0, "match": True, "reason": "apple_article"}
    assert pro_silver == {"score": 1.0, "match": True, "reason": "apple_article"}
    assert different_sku == {"score": 0.18, "match": False, "reason": "apple_article_conflict"}


def test_calc_name_match_uses_brand_model_tokens_for_soft_match():
    result = svc.calc_name_match(
        "Logitech MX Master 3S Mouse Graphite",
        "Мышь Logitech MX Master 3S graphite",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert result["match"] is True
    assert result["score"] >= 0.72


def test_calc_name_match_prefers_exact_case_fan_article():
    local = (
        "Вентилятор 140mm ID-Cooling AS-140-ARGB-W "
        "(60шт./кор, 4Pin PWM, 140x140x25mm, белый)"
    )
    exact = svc.calc_name_match(
        local,
        "Вентилятор для корпуса ID-Cooling AS-140-ARGB-W",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    sibling = svc.calc_name_match(
        local,
        "Вентилятор для корпуса ID-Cooling AS-140-K",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert exact["match"] is True
    assert exact["score"] > sibling["score"]


def test_calc_name_match_prefers_case_fan_sets_over_single_fans():
    local = "Вентилятор 120mm ID-Cooling AF-127-ARGB-K TRIO (НАБОР 3 в 1)"
    pack = svc.calc_name_match(
        local,
        "Комплект вентиляторов для корпуса ID-Cooling AF-127-ARGB-K TRIO",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    single = svc.calc_name_match(
        local,
        "Вентилятор для корпуса ID-Cooling AF-127-ARGB-K",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert pack["score"] > single["score"]


def test_calc_name_match_keeps_fan_set_series_and_color_priority():
    local = "Вентилятор ADATA XPG VENTO R 120 ARGB PWM (НАБОР 3 в 1) White"
    adata_brand = lambda _text: "ADATA"
    exact = svc.calc_name_match(
        local,
        "Комплект вентиляторов для корпуса ADATA XPG Vento R 120x3 ARGB PWM (белый)",
        extract_article=extract_article,
        preferred_brand_token=adata_brand,
        extract_article_candidates=extract_article_candidates,
    )
    no_r = svc.calc_name_match(
        local,
        "Комплект вентиляторов для корпуса ADATA XPG Vento 120x3 ARGB PWM (белый)",
        extract_article=extract_article,
        preferred_brand_token=adata_brand,
        extract_article_candidates=extract_article_candidates,
    )
    black = svc.calc_name_match(
        local,
        "Комплект вентиляторов для корпуса ADATA XPG Vento R 120x3 ARGB PWM (черный)",
        extract_article=extract_article,
        preferred_brand_token=adata_brand,
        extract_article_candidates=extract_article_candidates,
    )

    assert exact["score"] > no_r["score"]
    assert exact["score"] > black["score"]


def test_fan_series_tokens_cover_crystal_and_icefan():
    crystal = "Вентилятор ID-Cooling CRYSTAL 120 WHITE ARGB"
    icefan = "Вентилятор ID-Cooling ICEFAN 240 ARGB SNOW (НАБОР 2 в 1)"

    assert "CRYSTAL 120" in svc.raw_search_tokens(crystal)
    assert "CRYSTAL 120 WHITE" in svc.raw_search_tokens(crystal)
    assert "ICEFAN 240" in svc.raw_search_tokens(icefan)
    assert "ICEFAN 240 SNOW" in svc.raw_search_tokens(icefan)


def test_calc_name_match_prefers_exact_fan_series():
    crystal = svc.calc_name_match(
        "Вентилятор ID-Cooling CRYSTAL 120 WHITE ARGB",
        "Вентилятор для корпуса ID-Cooling Crystal 120 White ARGB",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    icefan_snow = svc.calc_name_match(
        "Вентилятор ID-Cooling ICEFAN 240 ARGB SNOW (НАБОР 2 в 1)",
        "Комплект вентиляторов для корпуса ID-Cooling IceFan 240 ARGB Snow",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    icefan_plain = svc.calc_name_match(
        "Вентилятор ID-Cooling ICEFAN 240 ARGB SNOW (НАБОР 2 в 1)",
        "Комплект вентиляторов для корпуса ID-Cooling IceFan 240 ARGB",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert crystal["reason"] == "fan_series"
    assert crystal["score"] >= 0.99
    assert icefan_snow["score"] > icefan_plain["score"]


def test_calc_name_match_uses_numeric_model_for_bags():
    exact = svc.calc_name_match(
        'Сумка для ноутбука 15,6" MIRU Elegance Red (1030)',
        "Сумка Miru Elegance 15.6 1030",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    sibling = svc.calc_name_match(
        'Сумка для ноутбука 15,6" MIRU Elegance Red (1030)',
        "Сумка Miru Elegance 15.6 1031",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert exact["reason"] == "numeric_model"
    assert exact["score"] > sibling["score"]


def test_calc_name_match_trusts_cable_article_across_adapter_names():
    result = svc.calc_name_match(
        "Кабель USB-A male - USB-C male VCOM (CU480MC-1.8M) USB3.2",
        "Адаптер VCOM CU480MC-1.8M DisplayPort - USB 3.2 Gen1 Type-C",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert result == {"score": 1.0, "match": True, "reason": "article"}


def test_calc_name_match_uses_monoblock_strict_articles():
    acer = svc.calc_name_match(
        'Моноблок Acer Aspire C27B, 27" IPS, Core Ultra 5 115U/ 16Gb/ 512SSD/ Black (DQ.BT7CD.001)',
        "Моноблок Acer Aspire C27B-GMTL DQ.BT7CD.001",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    msi_exact = svc.calc_name_match(
        'Моноблок MSI Pro AP272P 14M-685XRU, 27" IPS, Core i5 14400/ 8Gb/ 512SSD/ Black (9S6-AE0621-847)',
        "Моноблок MSI Pro AP272P 14M-685XRU",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    msi_wrong = svc.calc_name_match(
        'Моноблок MSI Pro AP272P 14M-685XRU, 27" IPS, Core i5 14400/ 8Gb/ 512SSD/ Black (9S6-AE0621-847)',
        "Моноблок MSI Pro AP272P 14M-627XRU 9S6-AF8321-800",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )
    msi_modern_uncertain = svc.calc_name_match(
        'Моноблок MSI Modern AM272P 1M, 27" IPS, Core 3 100U/ 8Gb/ 256SSD/ Black (9S6-AF8231-1035)',
        "Моноблок MSI Modern AM272P 1M-674RU",
        extract_article=extract_article,
        preferred_brand_token=brand_token,
        extract_article_candidates=extract_article_candidates,
    )

    assert "DQ.BT7CD.001" in svc.raw_search_tokens("Моноблок Acer (DQ.BT7CD.001)")
    assert "14M-685XRU" in svc.raw_search_tokens("Моноблок MSI Pro AP272P 14M-685XRU")
    assert "1UM-088XRU" in svc.raw_search_tokens("Моноблок MSI Modern 1UM-088XRU")
    assert "9S6-AF8231-1035" in svc.raw_search_tokens("Моноблок MSI Modern (9S6-AF8231-1035)")
    assert acer == {"score": 1.0, "match": True, "reason": "strict_article"}
    assert msi_exact == {"score": 1.0, "match": True, "reason": "strict_article"}
    assert msi_wrong == {"score": 0.16, "match": False, "reason": "strict_article_conflict"}
    assert msi_modern_uncertain == {"score": 0.72, "match": False, "reason": "article_like"}


def test_harden_base_verify_result_keeps_non_match_and_strong_match():
    non_match = {"status": "missing", "score": 0.0}
    assert svc.harden_base_verify_result("Local", non_match) == non_match

    result = svc.harden_base_verify_result(
        "МФУ Canon i-SENSYS MF3010 (5252B004)",
        {"status": "match", "catalog_name": "МФУ Canon i-SENSYS MF3010 (5252B004)", "score": 0.2},
        calc_match=lambda left, right: {"score": 0.91, "match": True, "reason": "article"},
        article_tokens=lambda value: {"5252b004"},
    )

    assert result["status"] == "match"
    assert result["score"] == 0.91


def test_calc_name_match_rejects_same_series_with_different_gpu_memory_variant():
    local = "Видеокарта Gigabyte RTX 5060 Ti Eagle OC 8G GV-N506TEAGLE OC-8GD"
    wrong = "Видеокарта Gigabyte RTX 5060 Ti Eagle OC 16G GV-N506TEAGLE OC-16GD"

    assert svc.calc_name_match(local, wrong) == {
        "score": 0.14,
        "match": False,
        "reason": "model_variant_conflict",
    }


def test_capacity_tokens_treat_memory_kit_as_total_capacity():
    assert svc.capacity_tokens("Оперативная память 2x16GB DDR4") == {"32gb"}
    assert svc.capacity_tokens("Оперативная память 2x32GB DDR4") == {"64gb"}


def test_calc_name_match_prefers_full_laptop_sku_over_shared_series():
    local = "Ноутбук ASUS ExpertBook P1 P1503CVA-i5H16512G0D"
    exact = "Ноутбук ASUS ExpertBook P1 P1503CVA-i5H16512G0D"
    sibling = "Ноутбук ASUS ExpertBook P1 P1503CVA-S72510X"

    exact_score = svc.calc_name_match(local, exact, preferred_brand_token=brand_token)["score"]
    sibling_score = svc.calc_name_match(local, sibling, preferred_brand_token=brand_token)["score"]

    assert exact_score > sibling_score


def test_calc_name_match_rejects_conflicting_numeric_manufacturer_article():
    local = "Web-cam Logitech C270 (960-000999)"
    wrong = "Веб-камера Logitech C270 Black (960-000635)"

    assert svc.calc_name_match(local, wrong) == {
        "score": 0.12,
        "match": False,
        "reason": "numeric_article_conflict",
    }


def test_calc_name_match_prefers_exact_mount_model_phrase():
    local = "Кронштейн для монитора ErgoSmart Heavy-Duty Spark DBL (черный)"
    exact = "Кронштейн для монитора ErgoSmart Heavy-Duty Spark DBL"
    sibling = "Кронштейн для монитора ErgoSmart Heavy-Duty DBL"

    exact_score = svc.calc_name_match(local, exact, preferred_brand_token=brand_token)["score"]
    sibling_score = svc.calc_name_match(local, sibling, preferred_brand_token=brand_token)["score"]

    assert exact_score > sibling_score


def test_harden_base_verify_result_marks_uncertain_matches_unverified():
    result = svc.harden_base_verify_result(
        "Logitech MX Master 3S",
        {"status": "match", "catalog_name": "Logitech MX Master", "score": 0.9},
        calc_match=lambda left, right: {"score": 0.55, "match": False, "reason": "tokens"},
        article_tokens=lambda value: set(),
    )

    assert result == {"status": "unverified", "catalog_name": "Logitech MX Master", "score": 0.55}


def test_harden_base_verify_result_marks_article_conflicts_mismatch_with_guess():
    result = svc.harden_base_verify_result(
        "GPU Gigabyte (GV-N4070WF3OC-12GD)",
        {
            "status": "match",
            "catalog_id": "old",
            "catalog_name": "GPU Gigabyte (GV-N4060WF2OC-8GD)",
            "url": "https://old.test",
            "score": 0.9,
        },
        lookup_catalog_match_details=lambda name: {
            "id": "new",
            "model": "GPU Gigabyte (GV-N4070WF3OC-12GD)",
            "url": "https://new.test",
        },
        calc_match=lambda left, right: {"score": 0.81, "match": True, "reason": "tokens"},
        article_tokens=lambda value: {"gvn4070wf3oc12gd"} if "4070" in value else {"gvn4060wf2oc8gd"},
    )

    assert result == {
        "status": "mismatch",
        "catalog_id": "new",
        "catalog_name": "GPU Gigabyte (GV-N4070WF3OC-12GD)",
        "url": "https://new.test",
        "score": 0.49,
    }
