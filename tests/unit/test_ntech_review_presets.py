"""Tests for N-Tech review endpoint presets."""

from price_mixer.services.ntech_review_presets import (
    NTECH_CATEGORY_REVIEW_CONFIG,
    build_core_review_start_kwargs,
    build_generic_review_start_kwargs,
    build_laptop_review_start_kwargs,
)


def _scan(**overrides):
    payload = {
        "scanned": 10,
        "queued": 7,
        "no_model": 1,
        "no_candidates": 2,
    }
    payload.update(overrides)
    return payload


def test_core_cpu_preset_preserves_counts_and_text():
    kwargs = build_core_review_start_kwargs("cpu")

    assert kwargs["report_mode"] == "cpu"
    assert kwargs["handler_mode"] == "cpu"
    assert kwargs["include_no_model"] is True
    assert kwargs["success_message"](_scan()) == (
        "Процессоры N-Tech: в ручную очередь добавлено 7. "
        "Без модели: 1. Без кандидатов: 2."
    )
    assert kwargs["report_subtitle"](_scan()) == (
        "Обработано CPU: 10. "
        "В очереди: 7, без модели: 1, без кандидатов: 2."
    )


def test_peripheral_preset_omits_no_model_metric():
    kwargs = build_core_review_start_kwargs("peripheral")

    assert kwargs["include_no_model"] is False
    assert "Без модели" not in kwargs["success_message"](_scan())
    assert "без модели" not in kwargs["report_subtitle"](_scan())


def test_generic_and_laptop_presets_keep_scope():
    generic = build_generic_review_start_kwargs(
        "ups",
        NTECH_CATEGORY_REVIEW_CONFIG["ups"],
        lambda **_kwargs: True,
        lambda **_kwargs: {},
    )
    laptop = build_laptop_review_start_kwargs(
        "IVEN_zakaz",
        "iven_zakaz_laptop",
        lambda **_kwargs: True,
        lambda **_kwargs: {},
    )

    assert generic["report_mode"] == "ntech_ups"
    assert generic["include_no_model"] is False
    assert laptop["supplier_names"] == ["IVEN_zakaz"]
    assert laptop["report_mode"] == "iven_zakaz_laptop"
