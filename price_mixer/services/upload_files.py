"""Helpers for turning uploaded files into supplier processing entries."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote
import uuid


ALLOWED_UPLOAD_EXTENSIONS = {".xls", ".xlsx", ".xlsb", ".xlsm", ".csv"}


def supplier_mapping_from_form(form) -> dict[str, str]:
    mapping = {}
    for key in form:
        if not str(key).startswith("supplier_"):
            continue
        fname = str(key).replace("supplier_", "", 1)
        try:
            supplier = str(form[key]).strip()
        except Exception:
            supplier = ""
        mapping[fname] = supplier
    return mapping


def supplier_for_uploaded_filename(filename, supplier_mapping, app_settings, infer_supplier):
    filename = str(filename or "")
    for enc_fname, supplier_name in (supplier_mapping or {}).items():
        if unquote(str(enc_fname)) == filename or str(enc_fname) == filename:
            return str(supplier_name or "").strip()
    return (infer_supplier(filename, app_settings) if callable(infer_supplier) else "") or ""


def upload_extension(filename):
    ext = Path(str(filename or "")).suffix.lower()
    return ext if ext in ALLOWED_UPLOAD_EXTENSIONS else ""


def make_uploaded_filename(filename, token_factory=None):
    token_factory = token_factory or (lambda: str(uuid.uuid4())[:8])
    extension = upload_extension(filename)
    if not extension:
        raise ValueError(f"Неподдерживаемый формат файла: {filename}")
    return str(token_factory())[:8] + extension


def build_upload_file_entries(files, form, session_dir, app_settings, infer_supplier, token_factory=None):
    supplier_mapping = supplier_mapping_from_form(form)
    entries = []
    for file in files or []:
        filename = str(getattr(file, "filename", "") or "")
        if not filename:
            continue
        supplier_name = supplier_for_uploaded_filename(filename, supplier_mapping, app_settings, infer_supplier)
        if not supplier_name:
            raise ValueError(f"Не удалось определить поставщика для файла: {filename}")
        safe_fname = make_uploaded_filename(filename, token_factory=token_factory)
        filepath = Path(session_dir) / safe_fname
        file.save(str(filepath))
        entries.append({
            "filepath": filepath,
            "display_name": filename,
            "supplier_name": supplier_name,
        })
    return entries
