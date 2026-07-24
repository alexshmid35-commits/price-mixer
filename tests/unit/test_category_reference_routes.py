"""Unit tests for category and supplier reference API blueprint."""

from flask import Flask

from price_mixer.api.category_reference_routes import create_category_reference_bp


def _make_app(
    *,
    get_categories=None,
    get_category_catalog=None,
    get_suppliers=None,
    get_supplier_categories=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_category_reference_bp(
        get_categories=get_categories or (lambda: {"categories": [{"name": "CPU", "count": 2}]}),
        get_category_catalog=get_category_catalog or (lambda: {"categories": ["CPU"]}),
        get_suppliers=get_suppliers or (lambda: {"suppliers": ["N-Tech"]}),
        get_supplier_categories=get_supplier_categories or (lambda supplier: {"status": "ok", "supplier": supplier}),
    ))
    return app


def test_categories_returns_callback_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/categories")

    assert resp.status_code == 200
    assert resp.get_json() == {"categories": [{"name": "CPU", "count": 2}]}


def test_category_catalog_returns_callback_payload():
    app = _make_app(get_category_catalog=lambda: {"categories": ["CPU", "SSD"]})

    with app.test_client() as client:
        resp = client.get("/api/category-catalog")

    assert resp.status_code == 200
    assert resp.get_json() == {"categories": ["CPU", "SSD"]}


def test_suppliers_returns_callback_payload():
    app = _make_app(get_suppliers=lambda: {"suppliers": ["IVEN", "N-Tech"]})

    with app.test_client() as client:
        resp = client.get("/api/suppliers")

    assert resp.status_code == 200
    assert resp.get_json() == {"suppliers": ["IVEN", "N-Tech"]}


def test_supplier_categories_passes_supplier_query():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/supplier-categories?supplier=N-Tech")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "supplier": "N-Tech"}


def test_supplier_categories_propagates_callback_status():
    app = _make_app(get_supplier_categories=lambda supplier: ({"status": "error"}, 400))

    with app.test_client() as client:
        resp = client.get("/api/supplier-categories")

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}
