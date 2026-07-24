"""Lifecycle and queue orchestration for the category parser service."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import requests  # type: ignore[import-untyped]

from price_mixer.product_schema import ProductWireIndex


class SortingReparseRuntime:
    def __init__(
        self,
        *,
        base_url: str,
        project_root: Path,
        get_active_session_dir: Callable,
        correct_rows: Callable,
        normalize_onliner_id: Callable,
        is_sorting_review_category: Callable,
        sorting_review_prefix: str,
        get_categories_by_ids: Callable,
        native_catalog_category_for_product: Callable,
        update_categories: Callable,
        clear_corrected_rows_cache: Callable,
        response_json_payload: Callable,
        parser_error_message: Callable,
        logger,
        http=requests,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.project_root = Path(project_root)
        self.get_active_session_dir = get_active_session_dir
        self.correct_rows = correct_rows
        self.normalize_onliner_id = normalize_onliner_id
        self.is_sorting_review_category = is_sorting_review_category
        self.sorting_review_prefix = sorting_review_prefix
        self.get_categories_by_ids = get_categories_by_ids
        self.native_catalog_category_for_product = native_catalog_category_for_product
        self.update_categories = update_categories
        self.clear_corrected_rows_cache = clear_corrected_rows_cache
        self.response_json_payload = response_json_payload
        self.parser_error_message = parser_error_message
        self.logger = logger
        self.http = http
        self._monitor_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._monitor_running = False

    def service_healthy(self, timeout=1.0):
        try:
            response = self.http.get(
                f"{self.base_url}/status",
                timeout=timeout,
            )
            return bool(response.ok)
        except requests.RequestException:
            return False

    def launch_spec(self):
        configured_dir = os.getenv("ONLINER_PARSER_DIR", "").strip()
        candidate_dirs = []
        if configured_dir:
            candidate_dirs.append(Path(configured_dir).expanduser())
        candidate_dirs.extend(
            [
                self.project_root.parent / "onliner-parser",
                Path("/opt/onliner-parser"),
            ]
        )
        for parser_dir in candidate_dirs:
            script_path = parser_dir / "ui_server.py"
            if not script_path.is_file():
                continue
            configured_python = os.getenv(
                "ONLINER_PARSER_PYTHON",
                "",
            ).strip()
            python_candidates = [
                (Path(configured_python).expanduser() if configured_python else None),
                parser_dir / ".venv" / "bin" / "python",
                parser_dir / ".venv" / "bin" / "python3",
                Path(sys.executable),
            ]
            python_path = next(
                (path for path in python_candidates if path and path.is_file()),
                None,
            )
            if python_path:
                return (
                    [str(python_path), str(script_path)],
                    parser_dir,
                    parser_dir / "parser_stdout.log",
                )
        raise RuntimeError("не найден onliner-parser/ui_server.py; укажи ONLINER_PARSER_DIR в .env")

    def ensure_service(self, start_timeout=8.0):
        if self.service_healthy():
            return
        with self._start_lock:
            if self.service_healthy():
                return
            command, parser_dir, log_path = self.launch_spec()
            with log_path.open("a", encoding="utf-8") as log_file:
                subprocess.Popen(
                    command,
                    cwd=str(parser_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            deadline = time.monotonic() + max(float(start_timeout), 1.0)
            while time.monotonic() < deadline:
                if self.service_healthy(timeout=0.8):
                    return
                time.sleep(0.2)
        raise RuntimeError("парсер не запустился за отведённое время; проверь parser_stdout.log")

    def sorting_items(self):
        session_dir = self.get_active_session_dir()
        rows = self.correct_rows(session_dir) if session_dir else None
        items = []
        seen = set()
        for row in rows or []:
            onliner_id = self.normalize_onliner_id(row[ProductWireIndex.ONLINER_ID])
            category = str(row[ProductWireIndex.CATEGORY] or "").strip()
            if not onliner_id or onliner_id in seen or not self.is_sorting_review_category(category):
                continue
            seen.add(onliner_id)
            items.append(
                {
                    "onliner_id": onliner_id,
                    "name": str(row[ProductWireIndex.NAME] or "").strip(),
                    "parent_category": category[len(self.sorting_review_prefix) :].strip(),
                }
            )
        return items

    def all_items(self):
        session_dir = self.get_active_session_dir()
        rows = self.correct_rows(session_dir, apply_visibility=False) if session_dir else None
        known = self.get_categories_by_ids([row[ProductWireIndex.ONLINER_ID] for row in rows or []])
        items = []
        seen = set()
        for row in rows or []:
            onliner_id = self.normalize_onliner_id(row[ProductWireIndex.ONLINER_ID])
            if not onliner_id or onliner_id in seen:
                continue
            category = str(row[ProductWireIndex.CATEGORY] or "").strip()
            known_category = self.native_catalog_category_for_product(
                known.get(onliner_id, ""),
                row[ProductWireIndex.NAME],
            )
            if known_category and not self.is_sorting_review_category(category):
                seen.add(onliner_id)
                continue
            seen.add(onliner_id)
            items.append(
                {
                    "onliner_id": onliner_id,
                    "name": str(row[ProductWireIndex.NAME] or "").strip(),
                    "parent_category": category,
                    "strict_api": True,
                }
            )
        return items

    def write_results(self, results):
        written = self.update_categories(results) if results else 0
        if written:
            self.clear_corrected_rows_cache()
        return written

    def start_monitor(self):
        with self._monitor_lock:
            if self._monitor_running:
                return
            self._monitor_running = True

        def worker():
            try:
                while True:
                    try:
                        response = self.http.get(
                            f"{self.base_url}/status",
                            timeout=15,
                        )
                        payload = self.response_json_payload(response)
                        self.write_results(payload.get("results") or [])
                        if not payload.get("is_running"):
                            break
                    except Exception as exc:
                        self.logger.warning(
                            "sorting reparse monitor failed: %s",
                            exc,
                        )
                    time.sleep(2)
            finally:
                with self._monitor_lock:
                    self._monitor_running = False

        threading.Thread(target=worker, daemon=True).start()

    def run(self, *, all_items=False):
        items = self.all_items() if all_items else self.sorting_items()
        if not items:
            message = (
                "В текущем прайсе нет товаров с OnlinerID." if all_items else "Очередь «Требует сортировки» пуста."
            )
            return {"ok": False, "error": message}, 400
        try:
            self.ensure_service()
            response = self.http.post(
                f"{self.base_url}/run",
                json={"items": items},
                timeout=15,
            )
            payload = self.response_json_payload(response)
            if response.ok and payload.get("ok"):
                self.start_monitor()
            return payload, response.status_code
        except Exception as exc:
            return {
                "ok": False,
                "error": self.parser_error_message(exc),
            }, 502

    def status(self):
        try:
            response = self.http.get(
                f"{self.base_url}/status",
                timeout=15,
            )
            payload = self.response_json_payload(response)
        except Exception as exc:
            return {
                "ok": False,
                "error": self.parser_error_message(exc),
            }, 502
        payload["written_to_db"] = self.write_results(payload.get("results") or [])
        payload["ok"] = True
        return payload, response.status_code
