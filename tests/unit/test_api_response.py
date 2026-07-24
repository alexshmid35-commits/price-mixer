"""Unit tests for shared API response normalization."""

from flask import Flask, jsonify, redirect

from price_mixer.api.response import as_response


def test_as_response_jsonifies_dict_with_default_status():
    app = Flask(__name__)

    with app.app_context():
        response, status = as_response({"status": "ok"})

    assert status == 200
    assert response.get_json() == {"status": "ok"}


def test_as_response_jsonifies_list_with_tuple_status():
    app = Flask(__name__)

    with app.app_context():
        response, status = as_response(([{"id": 1}], 202))

    assert status == 202
    assert response.get_json() == [{"id": 1}]


def test_as_response_preserves_ready_response():
    app = Flask(__name__)

    with app.app_context():
        ready = jsonify({"items": []})
        ready.headers["Cache-Control"] = "no-store"
        response = as_response(ready)

    assert response is ready
    assert response.headers["Cache-Control"] == "no-store"


def test_as_response_can_pair_ready_response_with_override_status():
    app = Flask(__name__)

    with app.app_context():
        ready = redirect("/")
        response, status = as_response((ready, 303))

    assert response is ready
    assert status == 303
