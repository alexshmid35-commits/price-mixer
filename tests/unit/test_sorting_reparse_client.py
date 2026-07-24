import requests

from price_mixer.services.sorting_reparse_client import parser_error_message, response_json_payload


class FakeResponse:
    def __init__(self, payload_marker, *, text="", status_code=200, content_type=""):
        self.payload_marker = payload_marker
        self.text = text
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type else {}

    def json(self):
        if self.payload_marker == "raise":
            raise ValueError("Expecting value")
        return self.payload_marker


def test_response_json_payload_accepts_dict_payload():
    assert response_json_payload(FakeResponse({"ok": True})) == {"ok": True}


def test_response_json_payload_reports_non_json_response():
    response = FakeResponse(
        "raise",
        text="<html>Server error</html>",
        status_code=500,
        content_type="text/html",
    )

    try:
        response_json_payload(response)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ValueError")

    assert "вернул не JSON" in message
    assert "HTTP 500" in message
    assert "text/html" in message
    assert "Server error" in message


def test_response_json_payload_rejects_non_dict_payload():
    try:
        response_json_payload(FakeResponse([{"ok": True}]))
    except ValueError as exc:
        assert "неожиданный формат" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_parser_error_message_for_connection_error_is_human_readable():
    message = parser_error_message(requests.exceptions.ConnectionError("connection refused"))

    assert "не запущен" in message
    assert "onliner-parser" in message
