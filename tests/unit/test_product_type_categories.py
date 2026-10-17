import pandas as pd
import pytest

from price_mixer.services.category_pipeline import apply_visibility_filter, row_category
from price_mixer.services.product_normalization import infer_category, normalize_catalog_category_name
from price_mixer.services.product_type_categories import specific_product_category


CASES = [
    ("Чайник электрический Bosch TWK3P420 1.7л. (корпус: нержавеющая сталь)", "Электрочайники и термопоты"),
    ("Термопот Starwind корпус металл USB", "Электрочайники и термопоты"),
    ("Сплит-система Centek CT-65K07 WiFi белый", "Кондиционеры"),
    ("Кондиционер LG Wi-Fi", "Кондиционеры"),
    ("Кулер AEL L-AEL-016 напольный белый", "Диспенсеры"),
    ("Кулер Aqua Work 0.7-TDR настольный электронный белый", "Диспенсеры"),
    ("Кулер Hotfrost V118E напольный белый", "Диспенсеры"),
    ("Кулер Vatten D27WE настольный электронный белый", "Диспенсеры"),
    ("Кулер для воды с Wi-Fi", "Диспенсеры"),
    ("Картридж Аквафор В510-08 для проточных фильтров", "Фильтры и системы для очистки воды"),
    ("Картридж Гейзер PP 5-10BB", "Фильтры и системы для очистки воды"),
    ("Водонагреватель Thermex Auga 100 V Wi-Fi", "Водонагреватели"),
    ("Холодильник с дисплеем WiFi", "Холодильники"),
    ("Морозильная камера 200л корпус белый", "Морозильники"),
    ("Стиральная машина LG Wi-Fi", "Стиральные машины"),
    ("Сушильная машина Bosch Wi-Fi", "Сушильные машины"),
    ("Посудомоечная машина Wi-Fi", "Посудомоечные машины"),
    ("Микроволновая печь корпус сталь", "Микроволновые печи"),
    ("Духовой шкаф Wi-Fi", "Духовые шкафы"),
    ("Варочная панель USB", "Варочные панели"),
    ("Плита кухонная", "Кухонные плиты"),
    ("Кухонная плита", "Кухонные плиты"),
    ("Кофемашина Wi-Fi", "Кофеварки и кофемашины"),
    ("Кофемолка корпус металл", "Кофемолки, ростеры для кофе"),
    ("Блендер корпус металл", "Блендеры"),
    ("Мясорубка корпус металл", "Мясорубки"),
    ("Мультиварка Wi-Fi", "Мультиварки"),
    ("Соковыжималка корпус металл", "Соковыжималки"),
    ("Аэрогриль Wi-Fi", "Аэрогрили и аэрофритюрницы"),
    ("Электрогриль Wi-Fi", "Электрогрили"),
    ("Тостер корпус металл", "Тостеры"),
    ("Вафельница корпус металл", "Сэндвичницы, вафельницы"),
    ("Планетарный миксер Wi-Fi", "Кухонные комбайны, машины и планетарные миксеры"),
    ("Миксер ручной корпус металл", "Ручные миксеры"),
    ("Пылесос Wi-Fi", "Пылесосы"),
    ("Утюг корпус металл", "Утюги"),
    ("Отпариватель Wi-Fi", "Пароочистители и отпариватели"),
    ("Фен корпус пластик", "Фены"),
    ("Увлажнитель воздуха Wi-Fi", "Увлажнители воздуха"),
    ("Очиститель воздуха Wi-Fi", "Очистители воздуха"),
    ("Обогреватель Wi-Fi", "Обогреватели"),
    ("Вентилятор напольный USB", "Вентиляторы"),
    ("Весы напольные Wi-Fi", "Напольные весы"),
    ("Весы кухонные USB", "Кухонные весы"),
    ("Радиоприемник Hyundai H-SRS200 USB SD/microSD", "Радиоприемники"),
    ("Набор инструментов Deko DKMT82 (жесткий кейс)", "Наборы инструментов"),
    ("Набор отверток Sturm! жесткий кейс", "Наборы инструментов"),
    ("[LMP-100105CSR] Настенный экран Lumien Master Picture (белый корпус)", "Проекционные экраны"),
    ("Умная лампа Gauss E27 Wi-Fi", "Умный дом"),
    ("Чехол (клип-кейс) Samsung Galaxy Card Slot Case", "Чехлы для смартфонов"),
    ("Плеер Hi-Fi Flash Digma B5 8Gb USB microSD", "Плееры"),
    ("Диск CD-R Verbatim 700Mb Slim case", "Оптические диски"),
    ("Автомагнитола ACV AD-9002 WiFi", "Автомагнитолы"),
    ("Колонки автомобильные JBL Stage USB", "Автомобильная акустика"),
    ("Автомобильный FM-модулятор ACV MicroSD BT USB", "FM-модуляторы"),
    ('Панель LG 55" 55VSH7J-H HDMI FHD USB', "Информационные панели"),
    ("IP-камера iFlow F-AC-1121", "IP-камеры"),
    ("Картридер Ginzzu GR-867UB USB Type-C", "Картридеры"),
    ("Кресло Бюрократ CH-300/BLACK", "Офисные кресла"),
]


@pytest.mark.parametrize("name,category", CASES)
def test_product_type_precedes_incidental_pc_attributes(name, category):
    assert infer_category(name) == category
    assert specific_product_category(name) == category
    assert normalize_catalog_category_name(category) == category
    assert row_category({"Название": name, "Категория": "Корпус"}) == category


@pytest.mark.parametrize("name", [
    "Корпус Chieftec ATX с вентиляторами", "Кулер ID-Cooling SE-224 для процессора",
    "Водяное охлаждение Arctic Liquid Freezer III 360", "Картридж HP LaserJet 106A",
    "Кулер Cooler Master Hyper 212", "Вентилятор 12x12 Jonsbo SL-120B",
    "Wi-Fi роутер TP-Link", "Материнская плата ASUS Wi-Fi",
    "Жесткий диск Seagate NAS IronWolf ST8000VN002", "Кабель D-Link ANT24 антенный",
    "Мобильный аккумулятор Xiaomi 10000mAh", "Кронштейн для телевизора с крепежом",
    "Строительный миксер Bosch", "Промышленный фен Bosch", "Кондиционер для белья",
    "Набор инструментов для СЖО Thermaltake Pacific",
])
def test_specific_rules_do_not_confuse_pc_hardware_and_accessories(name):
    assert specific_product_category(name) == ""


@pytest.mark.parametrize("supplier", ["IVEN", "IVEN_zakaz", "Tradex", "N-Tech", "Techlab"])
def test_blocked_product_type_cannot_bypass_visibility_with_a_stale_pc_category(supplier):
    name = CASES[0][0]
    source = pd.DataFrame([
        {"Название": name, "Категория": "Корпус", "Поставщик": supplier},
        {"Название": "Корпус Chieftec ATX", "Категория": "Корпус", "Поставщик": supplier},
    ])
    def visible(hidden):
        return apply_visibility_filter(
            source, "session", load_visibility_map_func=lambda _: {"__global__": hidden},
            infer_category=infer_category,
        )
    assert visible(["Электрочайники и термопоты"])["Название"].tolist() == ["Корпус Chieftec ATX"]
    assert len(visible([])) == 2
    assert source["Категория"].tolist() == ["Корпус", "Корпус"]
