"""Public category matching API and default plugin registry."""

from price_mixer.services.review_matching.board import (
    board_brand_model_key,
    find_board_review_candidates,
)
from price_mixer.services.review_matching.case import (
    case_brand_model_key,
    case_code_match,
    find_case_review_candidates,
    looks_like_case_name,
)
from price_mixer.services.review_matching.cooler import (
    cooler_brand_model_key,
    cooler_catalog_category_ok,
    cooler_paren_looks_socket_bundle,
    find_cooler_review_candidates,
    is_strong_cooler_paren_code,
    looks_like_cooler_name,
    looks_like_liquid_cpu_cooling_name,
)
from price_mixer.services.review_matching.cpu import (
    cpu_article_code,
    cpu_brand_model_key,
    cpu_package_type,
    find_cpu_review_candidates,
    looks_like_cpu_name,
)
from price_mixer.services.review_matching.engine import (
    ReviewMatchingEngine,
    ReviewMatchingPlugin,
)
from price_mixer.services.review_matching.gpu import (
    find_gpu_review_candidates,
    gpu_brand_model_key,
)
from price_mixer.services.review_matching.hdd import (
    find_hdd_review_candidates,
    hdd_brand_model_key,
    looks_like_hdd_name,
)
from price_mixer.services.review_matching.monitor import (
    find_monitor_review_candidates,
    monitor_brand_model_key,
)
from price_mixer.services.review_matching.peripheral import (
    find_peripheral_review_candidates,
    looks_like_peripheral_name,
    peripheral_catalog_category_ok,
)
from price_mixer.services.review_matching.printer import (
    find_printer_review_candidates,
    looks_like_printer_or_mfp_name,
    printer_mfp_brand_model_key,
    printer_mfp_catalog_category_ok,
)
from price_mixer.services.review_matching.psu import (
    find_psu_review_candidates,
    psu_brand_model_key,
    psu_code_match,
)
from price_mixer.services.review_matching.ram import (
    find_ram_review_candidates,
    ram_brand_model_key,
)
from price_mixer.services.review_matching.ssd import (
    find_ssd_review_candidates,
    ssd_brand_model_key,
)

DEFAULT_REVIEW_MATCHING_ENGINE = ReviewMatchingEngine(
    (
        ReviewMatchingPlugin(
            "cpu", ("процессор", "процессоры"), find_cpu_review_candidates, cpu_brand_model_key, looks_like_cpu_name
        ),
        ReviewMatchingPlugin(
            "board", ("материнская плата", "материнские платы"), find_board_review_candidates, board_brand_model_key
        ),
        ReviewMatchingPlugin(
            "monitor", ("монитор", "мониторы"), find_monitor_review_candidates, monitor_brand_model_key
        ),
        ReviewMatchingPlugin("gpu", ("видеокарта", "видеокарты"), find_gpu_review_candidates, gpu_brand_model_key),
        ReviewMatchingPlugin("ram", ("оперативная память",), find_ram_review_candidates, ram_brand_model_key),
        ReviewMatchingPlugin("ssd", ("накопители ssd",), find_ssd_review_candidates, ssd_brand_model_key),
        ReviewMatchingPlugin("psu", ("блок питания", "блоки питания"), find_psu_review_candidates, psu_brand_model_key),
        ReviewMatchingPlugin(
            "case", ("корпус", "корпусы"), find_case_review_candidates, case_brand_model_key, looks_like_case_name
        ),
        ReviewMatchingPlugin(
            "hdd",
            ("жесткий диск", "жесткие диски"),
            find_hdd_review_candidates,
            hdd_brand_model_key,
            looks_like_hdd_name,
        ),
        ReviewMatchingPlugin(
            "printer",
            ("принтер", "принтеры", "мфу"),
            find_printer_review_candidates,
            printer_mfp_brand_model_key,
            looks_like_printer_or_mfp_name,
        ),
        ReviewMatchingPlugin(
            "cooler",
            ("кулер", "охлаждение"),
            find_cooler_review_candidates,
            cooler_brand_model_key,
            looks_like_cooler_name,
        ),
        ReviewMatchingPlugin(
            "peripheral", ("периферия",), find_peripheral_review_candidates, detector=looks_like_peripheral_name
        ),
    )
)


__all__ = [
    "DEFAULT_REVIEW_MATCHING_ENGINE",
    "ReviewMatchingEngine",
    "ReviewMatchingPlugin",
    "board_brand_model_key",
    "case_brand_model_key",
    "case_code_match",
    "cooler_brand_model_key",
    "cooler_catalog_category_ok",
    "cooler_paren_looks_socket_bundle",
    "cpu_article_code",
    "cpu_brand_model_key",
    "cpu_package_type",
    "find_board_review_candidates",
    "find_case_review_candidates",
    "find_cooler_review_candidates",
    "find_cpu_review_candidates",
    "find_gpu_review_candidates",
    "find_hdd_review_candidates",
    "find_monitor_review_candidates",
    "find_peripheral_review_candidates",
    "find_printer_review_candidates",
    "find_psu_review_candidates",
    "find_ram_review_candidates",
    "find_ssd_review_candidates",
    "gpu_brand_model_key",
    "hdd_brand_model_key",
    "is_strong_cooler_paren_code",
    "looks_like_case_name",
    "looks_like_cooler_name",
    "looks_like_cpu_name",
    "looks_like_hdd_name",
    "looks_like_liquid_cpu_cooling_name",
    "looks_like_peripheral_name",
    "looks_like_printer_or_mfp_name",
    "monitor_brand_model_key",
    "peripheral_catalog_category_ok",
    "printer_mfp_brand_model_key",
    "printer_mfp_catalog_category_ok",
    "psu_brand_model_key",
    "psu_code_match",
    "ram_brand_model_key",
    "ssd_brand_model_key",
]
