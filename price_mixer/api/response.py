"""Shared helpers for blueprint response normalization."""

from flask import jsonify


def as_response(result, default_status: int = 200):
    status = default_status
    payload = result
    if isinstance(result, tuple) and len(result) == 2:
        payload, status = result
    if hasattr(payload, "status_code"):
        if status == default_status:
            return payload
        return payload, int(status)
    if isinstance(payload, (dict, list)):
        return jsonify(payload), int(status)
    return payload, int(status)
