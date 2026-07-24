"""API source runtime, download, and fetch worker helpers."""

from collections.abc import Callable, Mapping
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import requests

from price_mixer.logging_config import get_logger, log_context, new_job_id
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.state_store import load_dict, save_dict


LOGGER = get_logger("price_mixer.jobs.api_source")
source_fetch_statuses = {}
SOURCE_FETCH_LOCK = threading.RLock()
IVEN_SOURCE_KEYS = {"iven", "iven_zakaz"}
IVEN_DOWNLOAD_LOCK = threading.RLock()
SOURCE_RUNTIME_DIR = get_runtime_paths().cache_dir / "source_runtime"


def get_api_source_status_key(session_obj):
    key = str(session_obj.get("api_fetch_key", "") or "").strip()
    if not key:
        key = str(uuid.uuid4())[:12]
        session_obj["api_fetch_key"] = key
    return key


def get_source_runtime(source_key, client_key):
    client_key = str(client_key or "").strip()
    if not client_key:
        raise ValueError("client_key is required")
    default = _empty_source_runtime(source_key)
    if _external_status_enabled():
        path = _source_runtime_path(source_key, client_key)
        stored = load_dict(path)
        default.update(stored)
        return default
    with SOURCE_FETCH_LOCK:
        client_state = source_fetch_statuses.setdefault(client_key, {})
        return client_state.setdefault(source_key, default)


def _empty_source_runtime(source_key):
    return {
            "running": False,
            "progress": 0,
            "downloaded": 0,
            "total_bytes": 0,
            "status": "idle",
            "message": "",
            "ready": False,
            "source_key": source_key,
            "label": source_key.upper(),
            "supplier": "",
            "file_path": "",
            "file_name": "",
            "started_at": 0,
            "finished_at": 0,
            "job_id": "",
        }


def update_source_runtime(source_key, client_key, **kwargs):
    with SOURCE_FETCH_LOCK:
        if _external_status_enabled():
            state = get_source_runtime(source_key, client_key=client_key)
            state.update(kwargs)
            save_dict(_source_runtime_path(source_key, client_key), state)
            return dict(state)
        state = get_source_runtime(source_key, client_key=client_key)
        state.update(kwargs)
        return dict(state)


def serialize_source_runtime(state):
    data = dict(state or {})
    for key in ("started_at", "finished_at", "progress", "downloaded", "total_bytes"):
        if key in data:
            try:
                data[key] = int(data[key])
            except Exception:
                pass
    return data


def iter_api_sources_for_ui(settings=None):
    sources = ((settings or {}).get("api_sources") or {})
    items = []
    for key, cfg in sources.items():
        if not isinstance(cfg, dict):
            continue
        item = {
            "key": key,
            "label": str(cfg.get("label", key.upper()) or key.upper()),
            "supplier": str(cfg.get("supplier", key.upper()) or key.upper()),
            "enabled": bool(cfg.get("enabled")),
            "configured": False,
            "mode": str(cfg.get("mode", "direct_file") or "direct_file"),
        }
        if item["mode"] == "ntech_json":
            item["configured"] = bool(
                str(cfg.get("auth_url", "")).strip()
                and str(cfg.get("price_url", "")).strip()
                and str(cfg.get("username", "")).strip()
                and str(cfg.get("password", ""))
            )
        else:
            item["configured"] = bool(str(cfg.get("file_url", "")).strip())
        items.append(item)
    return items


def get_client_source_state(client_key):
    if _external_status_enabled():
        client_dir = _source_client_dir(client_key)
        result = {}
        if client_dir.is_dir():
            for path in client_dir.glob("*.json"):
                source_key = path.stem
                result[source_key] = get_source_runtime(source_key, client_key)
        return result
    with SOURCE_FETCH_LOCK:
        return dict(source_fetch_statuses.get(str(client_key or "").strip(), {}) or {})


def _external_status_enabled():
    return str(
        os.getenv("PRICE_MIXER_JOB_MODE", "inline") or "inline"
    ).strip().lower() == "external"


def _source_client_dir(client_key):
    client_key = str(client_key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", client_key):
        raise ValueError("invalid API source client key")
    return SOURCE_RUNTIME_DIR / client_key


def _source_runtime_path(source_key, client_key):
    source_key = normalize_source_key(source_key)
    if not re.fullmatch(r"[a-z0-9._-]{1,64}", source_key):
        raise ValueError("invalid API source key")
    return _source_client_dir(client_key) / f"{source_key}.json"


def normalize_source_key(value):
    return str(value or "").strip().lower()


def is_iven_source(source_key):
    return normalize_source_key(source_key) in IVEN_SOURCE_KEYS


def source_fetch_start_payload(payload, *, client_key, settings, start_worker, now=None):
    payload = payload if isinstance(payload, Mapping) else {}
    settings = settings or {}
    source_key = normalize_source_key(payload.get("source"))
    cfg = (((settings.get("api_sources") or {}).get(source_key)) or {})
    if not cfg:
        return {"status": "error", "message": "Неизвестный источник"}, 200

    runtime = get_source_runtime(source_key, client_key=client_key)
    if runtime.get("running"):
        return {"status": "ok", "state": serialize_source_runtime(runtime)}, 200

    now_fn = now or time.time
    update_source_runtime(
        source_key,
        client_key=client_key,
        running=True,
        ready=False,
        progress=0,
        downloaded=0,
        total_bytes=0,
        status="starting",
        message="Подготавливаю выгрузку...",
        started_at=now_fn(),
        finished_at=0,
        job_id=new_job_id(),
    )
    start_worker(source_key, client_key)
    return {
        "status": "ok",
        "state": serialize_source_runtime(get_source_runtime(source_key, client_key=client_key)),
    }, 200


def source_fetch_status_payload(source_key, *, client_key, settings, history):
    source_key = normalize_source_key(source_key)
    history = list(history or [])
    if source_key:
        state = serialize_source_runtime(get_source_runtime(source_key, client_key=client_key))
        return {"status": "ok", "state": state, "history": history}, 200

    items = []
    for src in iter_api_sources_for_ui(settings or {}):
        runtime = serialize_source_runtime(get_source_runtime(src["key"], client_key=client_key))
        runtime.update({
            "label": src["label"],
            "supplier": src["supplier"],
            "enabled": src["enabled"],
            "configured": src["configured"],
            "mode": src["mode"],
        })
        items.append(runtime)
    return {"status": "ok", "items": items, "history": history}, 200


def _source_file_path(runtime):
    raw = str((runtime or {}).get("file_path", "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _source_meta(source_key, runtime, file_path):
    supplier = str((runtime or {}).get("supplier", "") or source_key.upper()).strip() or source_key.upper()
    label = str((runtime or {}).get("label", source_key.upper()) or source_key.upper())
    return {
        "source_key": source_key,
        "supplier": supplier,
        "label": label,
        "file_name": file_path.name,
        "file_size": int(file_path.stat().st_size if file_path.exists() else 0),
    }


def _history_record(meta, *, started_at, finished_at, status, message, stats=None, session_id=""):
    stats = stats or {}
    record = {
        "source_key": meta["source_key"],
        "label": meta["label"],
        "supplier": meta["supplier"],
        "event_type": "process",
        "status": status,
        "message": message,
        "file_name": meta["file_name"],
        "file_size": meta["file_size"],
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": max(0, finished_at - started_at),
    }
    if status == "ok":
        record.update({
            "items_count": int(stats.get("consolidated", 0) or 0),
            "without_id_count": int(stats.get("without_id", 0) or 0),
            "session_id": str(session_id or ""),
        })
    return record


def _source_file_entry(file_path, runtime, supplier):
    return {
        "filepath": file_path,
        "display_name": (runtime or {}).get("file_name", file_path.name),
        "supplier_name": supplier,
    }


def process_source_payload(
    payload,
    *,
    client_key,
    process_supplier_files: Callable[[list[dict]], dict],
    finalize_processed_session: Callable[[str, str, str], None],
    append_history: Callable[[dict], None],
    redirect_for_session: Callable[[str], str],
    now=None,
):
    payload = payload if isinstance(payload, Mapping) else {}
    source_key = normalize_source_key(payload.get("source"))
    runtime = get_source_runtime(source_key, client_key=client_key)
    file_path = _source_file_path(runtime)
    if file_path is None:
        return {"status": "error", "message": "Сначала выгрузи прайс"}, 400

    now_fn = now or time.time
    started_at = int(now_fn())
    meta = _source_meta(source_key, runtime, file_path)
    file_entries = [_source_file_entry(file_path, runtime, meta["supplier"])]
    try:
        result = process_supplier_files(file_entries)
    except Exception as exc:
        finished_at = int(now_fn())
        message = str(exc) or "Не удалось обработать прайс"
        append_history(_history_record(
            meta,
            started_at=started_at,
            finished_at=finished_at,
            status="error",
            message=message,
        ))
        return {"status": "error", "message": message}, 500

    finalize_processed_session(result["session_id"], result["session_dir"], result["output_path"])
    finished_at = int(now_fn())
    append_history(_history_record(
        meta,
        started_at=started_at,
        finished_at=finished_at,
        status="ok",
        message="Прайс обработан",
        stats=result.get("stats") or {},
        session_id=result.get("session_id", ""),
    ))
    return {"status": "ok", "redirect_url": redirect_for_session(result["session_id"])}, 200


def _requested_source_keys(requested_sources, client_state):
    if isinstance(requested_sources, list):
        source_keys = [normalize_source_key(item) for item in requested_sources if normalize_source_key(item)]
    else:
        source_keys = []
    if not source_keys:
        source_keys = [
            normalize_source_key(key)
            for key, value in (client_state or {}).items()
            if isinstance(value, dict) and value.get("ready")
        ]

    deduped = []
    seen = set()
    for key in source_keys:
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def process_source_batch_payload(
    payload,
    *,
    client_key,
    client_state,
    process_supplier_files: Callable[[list[dict]], dict],
    finalize_processed_session: Callable[[str, str, str], None],
    append_history: Callable[[dict], None],
    redirect_for_session: Callable[[str], str],
    now=None,
):
    payload = payload if isinstance(payload, Mapping) else {}
    source_keys = _requested_source_keys(payload.get("sources"), client_state)
    if not source_keys:
        return {"status": "error", "message": "Нет готовых API-прайсов для обработки."}, 400

    file_entries = []
    per_source_meta = []
    for source_key in source_keys:
        runtime = get_source_runtime(source_key, client_key=client_key)
        file_path = _source_file_path(runtime)
        if file_path is None:
            continue
        meta = _source_meta(source_key, runtime, file_path)
        file_entries.append(_source_file_entry(file_path, runtime, meta["supplier"]))
        per_source_meta.append(meta)

    if not file_entries:
        return {"status": "error", "message": "Готовые файлы не найдены. Сначала нажми «Выгрузить»."}, 400

    now_fn = now or time.time
    started_at = int(now_fn())
    try:
        result = process_supplier_files(file_entries)
    except Exception as exc:
        finished_at = int(now_fn())
        message = str(exc) or "Не удалось обработать API-прайсы"
        for meta in per_source_meta:
            append_history(_history_record(
                meta,
                started_at=started_at,
                finished_at=finished_at,
                status="error",
                message="Пакетная обработка: " + message,
            ))
        return {"status": "error", "message": message}, 500

    finalize_processed_session(result["session_id"], result["session_dir"], result["output_path"])
    finished_at = int(now_fn())
    stats = result.get("stats") or {}
    for meta in per_source_meta:
        append_history(_history_record(
            meta,
            started_at=started_at,
            finished_at=finished_at,
            status="ok",
            message="Пакетная обработка API-источников",
            stats=stats,
            session_id=result.get("session_id", ""),
        ))
    return {
        "status": "ok",
        "processed_sources": source_keys,
        "redirect_url": redirect_for_session(result["session_id"]),
    }, 200


def source_temp_dir(upload_dir, client_key):
    client_key = str(client_key or "").strip()
    if not client_key:
        raise ValueError("client_key is required")
    path = Path(upload_dir) / f"_api_fetch_{client_key}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_source_headers(_source_key):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
    }


def resolve_curl_cmd():
    cmd = shutil.which("curl") or shutil.which("curl.exe")
    if cmd:
        return cmd
    raise RuntimeError("Системный curl не найден. Установите curl и перезапустите приложение.")


def head_content_length_via_curl(url, verify_ssl, headers=None):
    headers = headers or {}
    cmd = [resolve_curl_cmd(), "-I", "-L", "--silent", "--show-error"]
    if not verify_ssl:
        cmd.append("-k")
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            return 0
        match = re.search(r"(?im)^Content-Length:\s*(\d+)\s*$", result.stdout or "")
        return int(match.group(1)) if match else 0
    except Exception:
        return 0


def curl_download_to_path(url, target_path, verify_ssl, source_key, client_key, headers=None):
    headers = headers or {}
    target_path = Path(target_path)
    is_iven = is_iven_source(source_key)
    total = 0 if is_iven else head_content_length_via_curl(url, verify_ssl, headers=headers)
    download_message = "IVEN отвечает медленно, это нормально. Идет скачивание через системный клиент." if is_iven else "Скачиваю прайс через системный клиент..."
    update_source_runtime(source_key, client_key=client_key, total_bytes=total, status="downloading", message=download_message, progress=5)
    cmd = [resolve_curl_cmd(), "-L", "--silent", "--show-error", "--output", str(target_path)]
    if not verify_ssl:
        cmd.append("-k")
    if is_iven:
        cmd.append("--http1.1")
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    completed_early = False
    last_size = -1
    stable_count = 0
    try:
        while proc.poll() is None:
            size = target_path.stat().st_size if target_path.exists() else 0
            if total > 0:
                progress = min(95, int((size / total) * 100))
            else:
                progress = min(95, max(5, int(size / 65536))) if size else 5
            update_source_runtime(source_key, client_key=client_key, downloaded=size, progress=progress)
            if is_iven:
                if size == last_size and size > 0:
                    stable_count += 1
                else:
                    stable_count = 0
                last_size = size
                if stable_count >= 6:
                    try:
                        if zipfile.is_zipfile(target_path):
                            completed_early = True
                            proc.terminate()
                            break
                    except Exception:
                        pass
            time.sleep(0.35)
        _stdout, stderr = proc.communicate(timeout=10)
    except Exception:
        proc.kill()
        raise
    if proc.returncode != 0 and not completed_early:
        err = (stderr or b"").decode("utf-8", errors="ignore").strip()
        raise RuntimeError(err or f"curl exited with code {proc.returncode}")
    size = target_path.stat().st_size if target_path.exists() else 0
    update_source_runtime(source_key, client_key=client_key, downloaded=size, total_bytes=total or size, progress=100)


def curl_download_to_path_with_retries(
    url,
    target_path,
    verify_ssl,
    source_key,
    client_key,
    headers=None,
    *,
    attempts=3,
    retry_delay_sec=4,
):
    target_path = Path(target_path)
    attempts = max(1, int(attempts or 1))
    last_error = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            update_source_runtime(
                source_key,
                client_key=client_key,
                status="downloading",
                message=f"Повтор скачивания IVEN {attempt}/{attempts} после сетевого сброса...",
                progress=5,
                ready=False,
            )
        try:
            curl_download_to_path(url, target_path, verify_ssl, source_key, client_key, headers=headers)
            return
        except Exception as exc:
            last_error = exc
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt >= attempts:
                break
            wait_sec = max(1, int(retry_delay_sec or 1)) * attempt
            update_source_runtime(
                source_key,
                client_key=client_key,
                status="waiting",
                message=f"IVEN сбросил соединение. Повтор через {wait_sec} сек. ({attempt}/{attempts})",
                progress=5,
                ready=False,
            )
            time.sleep(wait_sec)
    raise last_error or RuntimeError("Не удалось скачать IVEN-прайс")


def stream_download_to_path(url, target_path, verify_ssl, source_key, client_key, headers=None):
    headers = headers or {}
    target_path = Path(target_path)
    downloaded = 0
    with requests.get(url, stream=True, verify=verify_ssl, timeout=120, headers=headers) as resp:
        resp.raise_for_status()
        try:
            total = int(resp.headers.get("Content-Length", "0") or 0)
        except Exception:
            total = 0
        update_source_runtime(source_key, client_key=client_key, total_bytes=total, status="downloading", message="Скачиваю прайс...")
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=262144):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                progress = int((downloaded / total) * 100) if total > 0 else min(95, max(5, int(downloaded / 65536)))
                update_source_runtime(source_key, client_key=client_key, downloaded=downloaded, progress=progress)
    update_source_runtime(
        source_key,
        client_key=client_key,
        downloaded=downloaded,
        total_bytes=downloaded or get_source_runtime(source_key, client_key=client_key).get("total_bytes", 0),
    )


def _read_downloaded_json(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size > 1024 * 1024:
        return None
    try:
        raw = path.read_bytes().lstrip()
    except Exception:
        return None
    if not raw.startswith((b"{", b"[")):
        return None
    try:
        parsed = json.loads(raw.decode("utf-8-sig", errors="ignore"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _download_retry_after(payload):
    if not isinstance(payload, Mapping):
        return 0
    raw = payload.get("retry_after")
    try:
        return max(0, int(float(raw)))
    except Exception:
        return 0


def _download_error_message(payload, label):
    detail = str((payload or {}).get("detail") or (payload or {}).get("message") or "").strip()
    if detail:
        return detail
    return f"{label}: источник вернул JSON вместо файла прайса"


def _download_direct_source_with_retries(
    *,
    file_url,
    target_path,
    verify_ssl,
    source_key,
    client_key,
    headers,
    label,
    attempts=6,
):
    last_payload = None
    last_message = ""
    for attempt in range(max(1, int(attempts or 1))):
        try:
            stream_download_to_path(file_url, target_path, verify_ssl, source_key, client_key=client_key, headers=headers)
        except requests.exceptions.RequestException:
            curl_download_to_path(file_url, target_path, verify_ssl, source_key, client_key=client_key, headers=headers)

        payload = _read_downloaded_json(target_path)
        if not payload:
            return

        last_payload = payload
        last_message = _download_error_message(payload, label)
        retry_after = _download_retry_after(payload)
        if retry_after <= 0 or attempt >= attempts - 1:
            break
        wait_sec = min(30, retry_after)
        update_source_runtime(
            source_key,
            client_key=client_key,
            status="waiting",
            message=f"{last_message}. Повтор через {wait_sec} сек.",
            progress=min(95, int(get_source_runtime(source_key, client_key=client_key).get("progress", 0) or 0)),
            ready=False,
        )
        time.sleep(wait_sec)

    retry_after = _download_retry_after(last_payload)
    suffix = f" Повтори выгрузку через {retry_after} сек." if retry_after else ""
    raise ValueError(f"{last_message or 'Источник вернул JSON вместо файла прайса'}.{suffix}")


def ntech_reserve_url_from_price_url(price_url):
    raw = str(price_url or "").strip()
    if not raw:
        return ""
    if raw.endswith("/price"):
        return raw[:-len("/price")] + "/list"
    return raw.rstrip("/") + "/list"


def ntech_api_json(method, url, token, verify_ssl=False, json_body=None, timeout=120):
    headers = {"Authorization": f"Bearer {token}"}
    method = str(method or "get").strip().lower() or "get"
    if method == "post":
        resp = requests.post(url, headers=headers, json=json_body, verify=verify_ssl, timeout=timeout)
    else:
        resp = requests.get(url, headers=headers, verify=verify_ssl, timeout=timeout)
    if resp.status_code == 401:
        raise PermissionError("unauthorized")
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def load_ntech_orders(token, reserve_url, verify_ssl=False):
    if not str(reserve_url or "").strip():
        return {"orders": [], "warning": None}
    try:
        payload = ntech_api_json("get", reserve_url, token, verify_ssl=verify_ssl, timeout=120)
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        if response is not None and response.status_code == 404:
            return {"orders": [], "warning": "API резервов N-Tech временно недоступно (HTTP 404). Продолжаю без резервов."}
        raise
    orders = payload.get("orders") or []
    return {"orders": orders if isinstance(orders, list) else [], "warning": None}


def build_ntech_dataframe(payload, reserve_orders=None):
    _ = reserve_orders
    products = []
    if isinstance(payload, dict):
        products = payload.get("products") or []
    rows = []
    last_category = ""
    for item in products:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or item.get("group") or "").strip()
        if category and category != last_category:
            rows.append({
                "код": "",
                "": category,
                "Наименование": "",
                "Гарантия": "",
                "Рекомендуемая\n розничная\n цена": "",
                "Цена без НДС": "",
                "Цена с НДС": "",
            })
            last_category = category
        rows.append({
            "код": item.get("id", ""),
            "": "",
            "Наименование": item.get("name", ""),
            "Гарантия": item.get("warranty", ""),
            "Рекомендуемая\n розничная\n цена": item.get("recommended_price") or item.get("retail_price") or "",
            "Цена без НДС": item.get("price", ""),
            "Цена с НДС": item.get("price_with_vat", ""),
        })
    return pd.DataFrame(rows)


def fetch_api_source_worker(
    source_key,
    client_key,
    *,
    upload_dir,
    load_settings,
    append_history,
):
    runtime = get_source_runtime(source_key, client_key=client_key)
    job_id = str(runtime.get("job_id", "") or "").strip() or new_job_id()
    update_source_runtime(source_key, client_key=client_key, job_id=job_id)
    with log_context(job_id=job_id):
        LOGGER.info("API source fetch started source=%s", source_key)
        _fetch_api_source_worker(
            source_key,
            client_key,
            upload_dir=upload_dir,
            load_settings=load_settings,
            append_history=append_history,
        )
        final_state = get_source_runtime(source_key, client_key=client_key)
        LOGGER.info(
            "API source fetch finished source=%s status=%s",
            source_key,
            final_state.get("status", "unknown"),
        )


def _fetch_api_source_worker(
    source_key,
    client_key,
    *,
    upload_dir,
    load_settings,
    append_history,
):
    settings = load_settings()
    cfg = (((settings or {}).get("api_sources") or {}).get(source_key) or {})
    label = str(cfg.get("label", source_key.upper()) or source_key.upper())
    supplier = str(cfg.get("supplier", label) or label)
    mode = str(cfg.get("mode", "direct_file") or "direct_file")
    verify_ssl = bool(cfg.get("verify_ssl"))
    temp_dir = source_temp_dir(upload_dir, client_key=client_key)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_key).strip("_") or source_key
    target_path = temp_dir / f"{safe_name}.xlsx"
    update_source_runtime(
        source_key,
        client_key=client_key,
        running=True,
        progress=0,
        downloaded=0,
        total_bytes=0,
        ready=False,
        status="starting",
        message="IVEN отвечает медленно, это нормально. Подготовка может занять до 2 минут." if is_iven_source(source_key) else "Подготавливаю выгрузку...",
        label=label,
        supplier=supplier,
        file_path="",
        file_name=target_path.name,
        started_at=time.time(),
        finished_at=0,
    )
    started_at = int(time.time())
    try:
        if mode == "ntech_json":
            auth_url = str(cfg.get("auth_url", "")).strip()
            price_url = str(cfg.get("price_url", "")).strip()
            username = str(cfg.get("username", "")).strip()
            password = str(cfg.get("password", ""))
            if not (auth_url and price_url and username and password):
                raise ValueError("Источник не настроен")
            update_source_runtime(source_key, client_key=client_key, progress=10, status="auth", message="Авторизация...")
            auth_resp = requests.post(auth_url, json={"username": username, "password": password}, verify=verify_ssl, timeout=60)
            auth_resp.raise_for_status()
            token = (auth_resp.json() or {}).get("token")
            if not token:
                raise ValueError("Токен не получен")
            update_source_runtime(source_key, client_key=client_key, progress=45, status="fetching", message="Получаю прайс N-Tech...")
            price_resp = None
            last_err = None
            for method in ("post", "get"):
                try:
                    req_fn = requests.post if method == "post" else requests.get
                    resp = req_fn(
                        price_url,
                        headers={"Authorization": f"Bearer {token}"},
                        verify=verify_ssl,
                        timeout=120,
                    )
                    if resp.status_code == 401:
                        update_source_runtime(source_key, client_key=client_key, progress=20, status="auth", message="Обновляю токен...")
                        auth_resp = requests.post(auth_url, json={"username": username, "password": password}, verify=verify_ssl, timeout=60)
                        auth_resp.raise_for_status()
                        token = (auth_resp.json() or {}).get("token")
                        if not token:
                            raise ValueError("Токен не получен")
                        update_source_runtime(source_key, client_key=client_key, progress=45, status="fetching", message="Повторно получаю прайс...")
                        resp = req_fn(
                            price_url,
                            headers={"Authorization": f"Bearer {token}"},
                            verify=verify_ssl,
                            timeout=120,
                        )
                    resp.raise_for_status()
                    price_resp = resp
                    break
                except Exception as exc:
                    last_err = exc
            if price_resp is None:
                raise last_err or RuntimeError("Не удалось получить прайс N-Tech")

            content_type = str(price_resp.headers.get("Content-Type", "") or "").lower()
            content_disp = str(price_resp.headers.get("Content-Disposition", "") or "").lower()
            body = price_resp.content or b""
            looks_like_file = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in content_type
                or "application/vnd.ms-excel" in content_type
                or "text/csv" in content_type
                or "application/octet-stream" in content_type
                or "attachment" in content_disp
                or body.startswith(b"PK\x03\x04")
            )
            if looks_like_file:
                update_source_runtime(source_key, client_key=client_key, progress=75, status="building", message="Сохраняю файл прайса N-Tech...")
                with open(target_path, "wb") as f:
                    f.write(body)
            else:
                payload = price_resp.json() or {}
                update_source_runtime(source_key, client_key=client_key, progress=75, status="building", message="Собираю Excel...")
                df = build_ntech_dataframe(payload)
                df.to_excel(target_path, index=False, sheet_name="Прайс N-Tech")
        else:
            file_url = str(cfg.get("file_url", "")).strip()
            if not file_url:
                raise ValueError("Источник не настроен")
            headers = default_source_headers(source_key)
            if is_iven_source(source_key):
                update_source_runtime(
                    source_key,
                    client_key=client_key,
                    status="waiting",
                    message="Жду очередь IVEN, чтобы сервер не сбросил параллельные скачивания...",
                    progress=3,
                    ready=False,
                )
                with IVEN_DOWNLOAD_LOCK:
                    curl_download_to_path_with_retries(
                        file_url,
                        target_path,
                        verify_ssl,
                        source_key,
                        client_key=client_key,
                        headers=headers,
                    )
            else:
                _download_direct_source_with_retries(
                    file_url=file_url,
                    target_path=target_path,
                    verify_ssl=verify_ssl,
                    source_key=source_key,
                    client_key=client_key,
                    headers=headers,
                    label=label,
                )
        update_source_runtime(
            source_key,
            client_key=client_key,
            running=False,
            progress=100,
            status="ready",
            message="Прайс получен. Можно обрабатывать.",
            ready=True,
            file_path=str(target_path),
            file_name=target_path.name,
            finished_at=time.time(),
        )
        final_state = get_source_runtime(source_key, client_key=client_key)
        file_size = target_path.stat().st_size if target_path.exists() else int(final_state.get("downloaded", 0) or 0)
        finished_at = int(final_state.get("finished_at", time.time()) or time.time())
        append_history({
            "source_key": source_key,
            "label": label,
            "supplier": supplier,
            "event_type": "fetch",
            "status": "ok",
            "message": "Прайс получен",
            "file_name": target_path.name,
            "file_size": int(file_size or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
        })
    except Exception as exc:
        LOGGER.exception(
            "API source fetch failed source=%s mode=%s",
            source_key,
            mode,
        )
        error_message = str(exc)[:240] or "Ошибка выгрузки"
        update_source_runtime(
            source_key,
            client_key=client_key,
            running=False,
            ready=False,
            status="error",
            message=error_message,
            finished_at=time.time(),
        )
        finished_at = int(time.time())
        file_size = target_path.stat().st_size if target_path.exists() else 0
        append_history({
            "source_key": source_key,
            "label": label,
            "supplier": supplier,
            "event_type": "fetch",
            "status": "error",
            "message": error_message,
            "file_name": target_path.name,
            "file_size": int(file_size or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
        })
