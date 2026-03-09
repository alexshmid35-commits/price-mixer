#!/usr/bin/env python3
"""
Price Mixer Web — веб-интерфейс для сведения прайсов поставщиков.

Запуск: python3 app.py
Открыть: http://localhost:5001
"""

import json
import math
import os
import re
import shutil
import time
import uuid
from urllib.parse import quote
from difflib import SequenceMatcher
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
from flask import (
    Flask, render_template_string, request, redirect,
    url_for, send_file, session, jsonify,
)

import threading

from mixer import (
    load_url_cache,
    save_url_cache,
    resolve_onliner_urls,
    parse_generic_excel,
    consolidate_simple,
    find_missing_onliner_ids,
    load_id_cache,
    save_id_cache,
    build_id_fanout_map,
    is_trusted_cached_id,
    prune_negative_id_cache,
    warm_url_cache_from_id_cache,
    extract_article,
    lookup_id_from_catalog_sheet,
    lookup_catalog_match_details,
    verify_catalog_id_with_prefix,
    _load_catalog_sheet_index,
)

find_id_status = {
    "running": False,
    "checked": 0,
    "total": 0,
    "found": 0,
    "phase": "idle",
    "sheet_checked": 0,
    "sheet_total": 0,
    "sheet_found": 0,
    "api_checked": 0,
    "api_total": 0,
    "api_found": 0,
    "not_found": 0,
}

# Глобальный прогресс резолвинга
resolve_status = {"running": False, "resolved": 0, "total": 0, "cached": 0}
market_refresh_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "categories": {},
    "started_at": 0,
    "finished_at": 0,
}
MARKET_REFRESH_LOCK = threading.RLock()
AUTO_REFRESH_INTERVAL_SEC = 12 * 3600
AUTO_REFRESH_MAX_IDS = 1200

app = Flask(__name__)
app.secret_key = os.urandom(24)
CONSOLIDATED_IO_LOCK = threading.RLock()
BACKGROUND_STARTED = False

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _ensure_background_workers():
    global BACKGROUND_STARTED
    if BACKGROUND_STARTED:
        return
    BACKGROUND_STARTED = True
    threading.Thread(target=_auto_market_refresh_loop, daemon=True).start()


@app.before_request
def _startup_background_workers():
    _ensure_background_workers()

# ============================================================
# HTML ШАБЛОНЫ
# ============================================================

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #1a1a2e; }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
h1 { font-size: 28px; margin-bottom: 8px; }
h1 span { color: #6c63ff; }
.subtitle { color: #666; margin-bottom: 30px; font-size: 15px; }
a { color: #6c63ff; text-decoration: none; }
a:hover { text-decoration: underline; }
.btn { display: inline-block; padding: 12px 32px; background: #6c63ff; color: #fff; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background .2s; text-decoration: none; }
.btn:hover { background: #5a52d5; text-decoration: none; color: #fff; }
.btn-outline { background: transparent; border: 2px solid #6c63ff; color: #6c63ff; }
.btn-outline:hover { background: #6c63ff; color: #fff; }
.card { background: #fff; border-radius: 12px; padding: 28px; box-shadow: 0 2px 12px rgba(0,0,0,.06); margin-bottom: 20px; }
.idcheck-modal { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); display: none; align-items: center; justify-content: center; z-index: 1200; }
.idcheck-modal.active { display: flex; }
.idcheck-sheet { width: min(1200px, calc(100vw - 32px)); max-height: calc(100vh - 40px); overflow: auto; background: #fff; border-radius: 14px; box-shadow: 0 22px 50px rgba(0,0,0,.25); padding: 16px; }
.idcheck-top { display: grid; grid-template-columns: 1fr 260px 180px auto; gap: 10px; align-items: end; margin-top: 8px; }
.idcheck-cat-wrap { display: grid; grid-template-rows: auto auto auto; gap: 6px; }
.idcheck-cat-search { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; }
.idcheck-cat-select { width: 100%; min-height: 150px; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; }
.idcheck-table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
.idcheck-table th, .idcheck-table td { border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }
.idcheck-table th { background: #f8fafc; position: sticky; top: 0; z-index: 1; }
.idcheck-status-ok { color: #15803d; font-weight: 700; }
.idcheck-status-bad { color: #dc2626; font-weight: 700; }
.idcheck-status-warn { color: #b45309; font-weight: 700; }
.idcheck-note { margin-top: 8px; color: #64748b; font-size: 13px; }
.idreplace-box { margin-top: 10px; border: 1px solid #e5e7eb; border-radius: 10px; background: #f8fafc; padding: 8px; }
.idreplace-box summary { cursor: pointer; font-weight: 700; color: #1f2937; }
.idreplace-list { max-height: 180px; overflow: auto; margin-top: 8px; font-size: 12px; color: #334155; }
.idreplace-modal { position: fixed; inset: 0; background: rgba(15,23,42,.45); display: none; align-items: center; justify-content: center; z-index: 1300; }
.idreplace-modal.active { display: flex; }
.idreplace-sheet { width: min(820px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; background: #fff; border-radius: 12px; box-shadow: 0 20px 48px rgba(0,0,0,.25); padding: 14px; }
.idreplace-grid { display: grid; grid-template-columns: 1fr 220px; gap: 10px; align-items: end; margin-top: 10px; }
.idreplace-listbox { width: 100%; min-height: 280px; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; }
.idreplace-note { margin-top: 8px; color: #64748b; font-size: 13px; }
"""

UPLOAD_PAGE = (
    '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>Price Mixer</title><style>'
    + BASE_CSS
    + """
.drop-zone { border: 3px dashed #d0d0e0; border-radius: 16px; padding: 50px 30px; text-align: center; transition: border-color .2s, background .2s; cursor: pointer; }
.drop-zone:hover, .drop-zone.drag-over { border-color: #6c63ff; background: #f8f7ff; }
.drop-zone.has-files { border-color: #4caf50; background: #f0faf0; }
.drop-zone input[type=file] { display: none; }
.drop-zone .icon { font-size: 48px; margin-bottom: 12px; }
.drop-zone .main-text { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.drop-zone .sub-text { font-size: 14px; color: #888; }
.file-list { margin-top: 20px; text-align: left; }
.file-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: #f8f7ff; border-radius: 8px; margin-bottom: 6px; font-size: 14px; }
.file-item .fname { font-weight: 500; flex: 1; }
.file-item input[type="text"] { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; width: 150px; font-size: 13px; }
.file-item input[type="text"]:focus { border-color: #6c63ff; outline: none; }
.file-item .remove { color: #e74c3c; cursor: pointer; font-size: 18px; padding: 0 4px; }
.actions { text-align: center; margin-top: 20px; }
.error { background: #fff0f0; color: #c0392b; padding: 14px 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #c0392b; }
.spinner { display: none; text-align: center; padding: 40px; }
.spinner.active { display: block; }
.spinner .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #6c63ff; margin: 0 4px; animation: bounce .6s infinite alternate; }
.spinner .dot:nth-child(2) { animation-delay: .2s; }
.spinner .dot:nth-child(3) { animation-delay: .4s; }
@keyframes bounce { to { transform: translateY(-10px); opacity: .5; } }
.hint { margin-top: 16px; font-size: 13px; color: #888; }
</style></head><body>
<div class="container">
<h1>Price <span>Mixer</span></h1>
<p class="subtitle">Загрузите прайсы и укажите имя поставщика для каждого файла</p>

{% if error %}<div class="error">{{ error }}</div>{% endif %}

<form method="POST" action="/upload" enctype="multipart/form-data" id="upload-form">
<div class="card">
    <div class="drop-zone" id="drop-zone">
        <div class="icon">&#128193;</div>
        <div class="main-text">Перетащите файлы сюда или нажмите для выбора</div>
        <div class="sub-text">Поддерживаются .xls и .xlsx</div>
        <input type="file" name="files" id="file-input" multiple accept=".xls,.xlsx">
    </div>
    <div class="file-list" id="file-list"></div>
    <div class="hint">Для каждого файла укажите имя поставщика (например: BN, Tradex, TGPC)</div>
</div>
<div class="actions" id="actions-area" style="display:none;">
    <button type="submit" class="btn" id="submit-btn">Обработать прайсы</button>
</div>
<div class="spinner" id="spinner">
    <div class="dot"></div><div class="dot"></div><div class="dot"></div>
    <p style="margin-top:16px; color:#666;">Обработка прайсов... Это может занять до минуты.</p>
</div>
</form>
</div>
<script>
var dt = new DataTransfer();
var fileInput = document.getElementById('file-input');
var dropZone = document.getElementById('drop-zone');
var fileList = document.getElementById('file-list');
var actionsArea = document.getElementById('actions-area');

function detectSupplier(fname) {
    var fl = fname.toLowerCase();
    if (fl.indexOf('tradex') >= 0) return 'Tradex';
    if (fl.indexOf('1030z') >= 0) return 'BN-1030Z';
    if (fl.indexOf('1030') >= 0) return 'BN-1030';
    if (fl.indexOf('1374') >= 0) return 'BN-1374';
    if (fl.indexOf('price_bn') >= 0) return 'TGPC';
    return '';
}

function updateFileList() {
    fileList.innerHTML = '';
    if (dt.files.length === 0) {
        dropZone.classList.remove('has-files');
        actionsArea.style.display = 'none';
        fileInput.value = '';
        return;
    }
    dropZone.classList.add('has-files');
    actionsArea.style.display = 'block';
    
    var fileNames = [];
    for (var i = 0; i < dt.files.length; i++) {
        var f = dt.files[i];
        var detected = detectSupplier(f.name);
        var div = document.createElement('div');
        div.className = 'file-item';
        div.innerHTML = '<span class="fname" data-fname="' + f.name + '">' + f.name + '</span>' +
            '<input type="text" class="supplier-input" data-fname="' + f.name + '" value="' + detected + '" placeholder="Имя поставщика">' +
            '<span class="remove" data-fname="'+f.name+'">&times;</span>';
        fileList.appendChild(div);
        fileNames.push(f.name);
    }
    
    document.querySelectorAll('.remove').forEach(function(el){
        el.addEventListener('click', function(e){
            e.stopPropagation();
            var fname = this.dataset.fname;
            var newDt = new DataTransfer();
            for(var j=0; j<dt.files.length; j++){
                if(dt.files[j].name !== fname) newDt.items.add(dt.files[j]);
            }
            dt = newDt;
            updateFileList();
        });
    });
}

fileInput.addEventListener('change', function(){
    for(var i=0; i<this.files.length; i++) dt.items.add(this.files[i]);
    updateFileList();
});

dropZone.addEventListener('click', function(){ fileInput.click(); });
dropZone.addEventListener('dragover', function(e){ e.preventDefault(); this.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', function(e){ this.classList.remove('drag-over'); });
dropZone.addEventListener('drop', function(e){
    e.preventDefault(); this.classList.remove('drag-over');
    for(var i=0; i<e.dataTransfer.files.length; i++) dt.items.add(e.dataTransfer.files[i]);
    updateFileList();
});

document.getElementById('upload-form').addEventListener('submit', function(e){
    var inputs = document.querySelectorAll('.supplier-input');
    for(var i=0; i<inputs.length; i++){
        var inp = inputs[i];
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'supplier_' + encodeURIComponent(inp.dataset.fname);
        hidden.value = inp.value;
        this.appendChild(hidden);
    }
    
    fileInput.files = dt.files;
    
    document.getElementById('submit-btn').disabled = true;
    document.getElementById('spinner').classList.add('active');
});
</script>
</body></html>"""
)

RESULT_PAGE = (
    '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>Price Mixer — Результат</title>'
    '<link rel="stylesheet" href="https://cdn.datatables.net/1.13.7/css/jquery.dataTables.min.css">'
    '<style>'
    + BASE_CSS
    + """
	.table-card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,.06); margin-bottom: 20px; overflow-x: auto; }
	table.dataTable { width: 100% !important; font-size: 13px; }
	table.dataTable thead th { background: #f8f7ff; color: #333; font-weight: 600; white-space: nowrap; }
	table.dataTable tbody td { vertical-align: middle; }
	.top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
	.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
	.stat-card { background: #f8f7ff; border-radius: 8px; padding: 16px; text-align: center; }
	.stat-card .num { font-size: 28px; font-weight: 700; color: #6c63ff; }
	.stat-card .label { font-size: 13px; color: #666; margin-top: 4px; }
	.stat-card.highlight { background: #fff3e0; }
	.stat-card.highlight .num { color: #e65100; }
	.markup-card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 2px 12px rgba(0,0,0,.06); margin-bottom: 16px; }
	.markup-title { font-size: 16px; font-weight: 700; color: #111827; margin-bottom: 10px; }
	.markup-top { margin-bottom: 10px; }
	.markup-split { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: start; }
	.markup-left, .markup-right { min-width: 0; }
	.markup-row { display: grid; grid-template-columns: 1fr; gap: 10px; align-items: start; }
	.markup-row select, .markup-row input { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; }
	.markup-row select { min-height: 200px; }
	.markup-controls { display: grid; grid-template-columns: 180px auto; gap: 8px; align-items: end; justify-content: start; }
	.apply-markup-btn-small { background: #ecfdf3; color: #166534; border: 2px solid #22c55e; font-size: 13px; padding: 8px 12px; }
	.apply-markup-btn-small:hover { background: #dcfce7; }
	.visibility-row { display: grid; grid-template-columns: 180px 1fr; gap: 10px; align-items: start; }
	.visibility-row select { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; min-height: 140px; }
	.preview-card { border: 1px solid #e5e7eb; border-radius: 10px; background: #f8fafc; padding: 10px; margin-top: 10px; }
	.preview-title { font-size: 13px; font-weight: 700; color: #1f2937; margin-bottom: 8px; }
	.preview-table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.preview-table th, .preview-table td { border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }
	.preview-table th { color: #475569; background: #f1f5f9; }
	.preview-transfer { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; align-items: start; }
	.preview-transfer select, .preview-transfer input { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; }
	.preview-transfer select { min-height: 250px; }
	.select-search { width: 100%; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; margin-bottom: 6px; }
	.transfer-action { display: flex; justify-content: flex-end; margin-top: 8px; }
	.transfer-action .btn { width: auto !important; min-width: 150px; padding: 8px 14px !important; font-size: 13px; }
	.markup-map { margin-top: 10px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; overflow: hidden; }
	.markup-map table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.markup-map th, .markup-map td { border-bottom: 1px solid #eef2f7; padding: 6px 8px; text-align: left; }
	.markup-map th { background: #f8fafc; color: #475569; }
	.full-list-modal { position: fixed; inset: 0; background: rgba(2,8,23,.55); display: none; align-items: center; justify-content: center; z-index: 1300; }
	.full-list-modal.active { display: flex; }
	.full-list-sheet { width: min(1460px, calc(100vw - 20px)); max-height: calc(100vh - 20px); overflow: auto; background: #fff; border-radius: 14px; padding: 14px; box-shadow: 0 24px 60px rgba(0,0,0,.35); border: 1px solid #dbeafe; }
	.full-list-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
	.full-list-table th, .full-list-table td { border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }
	.full-list-table th { position: sticky; top: 0; background: #f8fafc; z-index: 1; }
	.markup-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
	.markup-note { font-size: 12px; color: #6b7280; margin-top: 8px; }
	.pricing-modal { position: fixed; inset: 0; background: rgba(15,23,42,.55); display: none; align-items: center; justify-content: center; z-index: 1200; backdrop-filter: blur(3px); }
	.pricing-modal.active { display: flex; }
	.pricing-sheet { width: min(1380px, calc(100vw - 20px)); max-height: calc(100vh - 20px); overflow: auto; background: linear-gradient(180deg, #ffffff, #f7fbff); border-radius: 16px; padding: 16px; box-shadow: 0 24px 64px rgba(2,8,23,.35); border: 1px solid #dbeafe; animation: riseIn .22s ease-out; }
	.preview-modal { position: fixed; inset: 0; background: rgba(2,8,23,.55); display: none; align-items: center; justify-content: center; z-index: 1350; }
	.preview-modal.active { display: flex; }
	.preview-sheet { width: min(1460px, calc(100vw - 20px)); max-height: calc(100vh - 20px); overflow: auto; background: #fff; border-radius: 14px; padding: 14px; box-shadow: 0 24px 60px rgba(0,0,0,.35); border: 1px solid #dbeafe; animation: riseIn .2s ease-out; }
	.preview-grid { display: grid; grid-template-columns: 180px 220px 1fr 240px; gap: 10px; align-items: end; margin-bottom: 8px; }
	.preview-grid input { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; }
	.preview-grid .btn { padding: 10px 12px; }
	.preview-full-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
	.preview-full-table th, .preview-full-table td { border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }
	.preview-full-table th { position: sticky; top: 0; background: #f8fafc; z-index: 1; }
	.preview-full-table th:nth-child(n+5), .preview-full-table td:nth-child(n+5) { text-align: center; }
	.preview-full-table th:nth-child(n+5), .preview-full-table td:nth-child(n+5) { border-left: 1px solid #cbd5e1; }
	.preview-full-table th:nth-child(11), .preview-full-table td:nth-child(11) { border-right: 1px solid #cbd5e1; }
	.market-trend { display: inline-block; margin-left: 4px; font-size: 11px; font-weight: 700; }
	.market-trend-up { color: #dc2626; }
	.market-trend-down { color: #16a34a; }
	.market-trend-flat { color: #64748b; }
	.pricing-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; position: sticky; top: 0; background: #f7fbff; z-index: 2; padding-bottom: 6px; }
	.pricing-close { border: none; background: #e2e8f0; color: #0f172a; border-radius: 8px; padding: 8px 12px; cursor: pointer; font-weight: 700; }
	.pulse { animation: pulse .9s ease; }
	@keyframes riseIn { from { transform: translateY(16px) scale(0.98); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
	@keyframes pulse { 0%{ box-shadow: 0 0 0 0 rgba(99,102,241,.35);} 70%{ box-shadow:0 0 0 12px rgba(99,102,241,0);} 100%{ box-shadow:0 0 0 0 rgba(99,102,241,0);} }
	.progress-modal { position: fixed; inset: 0; background: rgba(17, 24, 39, 0.55); display: none; align-items: center; justify-content: center; z-index: 1000; backdrop-filter: blur(2px); }
	.progress-modal.active { display: flex; }
	.progress-card { width: min(640px, calc(100vw - 32px)); background: linear-gradient(140deg, #ffffff, #f7fbff); border-radius: 18px; box-shadow: 0 24px 60px rgba(15, 23, 42, .28); padding: 22px; border: 1px solid #e8eefc; }
	.progress-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
	.progress-title { font-size: 18px; font-weight: 700; color: #1f2937; }
	.progress-subtitle { font-size: 13px; color: #64748b; }
	.progress-spinner { width: 22px; height: 22px; border-radius: 50%; border: 3px solid #dbe7ff; border-top-color: #1e88e5; animation: spin 0.8s linear infinite; }
	.progress-spinner.done { border-color: #d1fae5; border-top-color: #2e7d32; animation: none; }
	@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
	.phase-grid { display: grid; gap: 10px; margin-bottom: 14px; }
	.phase-item { border: 1px solid #e8eaf0; border-radius: 12px; padding: 11px 12px; background: #fff; }
	.phase-item .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
	.phase-item .name { font-size: 14px; font-weight: 600; color: #111827; }
	.phase-item .meta { font-size: 12px; color: #6b7280; margin-top: 3px; }
	.phase-pill { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; border-radius: 999px; padding: 5px 9px; background: #eef2ff; color: #475569; }
	.phase-pill.active { background: #dbeafe; color: #1d4ed8; }
	.phase-pill.done { background: #dcfce7; color: #166534; }
	.progress-line-wrap { margin-bottom: 10px; }
	.progress-line { height: 10px; border-radius: 999px; background: #e5e7eb; overflow: hidden; }
	.progress-line > div { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #06b6d4); transition: width .25s ease; }
	.progress-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
	.mini-stat { background: #fff; border: 1px solid #edf2f7; border-radius: 10px; padding: 8px 10px; text-align: center; }
	.mini-stat .v { font-size: 18px; font-weight: 700; color: #0f172a; }
	.mini-stat .t { font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: .03em; }
	.progress-actions { margin-top: 14px; display: flex; justify-content: flex-end; }
	.progress-close { display: none; padding: 8px 14px; border-radius: 9px; border: none; background: #2e7d32; color: #fff; font-weight: 600; cursor: pointer; }
	@media (max-width: 1100px){
		.markup-split { grid-template-columns: 1fr; }
		.preview-transfer { grid-template-columns: 1fr; }
		.markup-controls { grid-template-columns: 1fr; }
		.preview-grid { grid-template-columns: 1fr; }
	}
	</style></head><body>
<div class="container">

<div class="top-bar">
    <div>
        <h1>Price <span>Mixer</span> — Результат</h1>
        <p class="subtitle">Сводный прайс: {{ stats.consolidated }} товаров от {{ stats.suppliers }} поставщиков</p>
    </div>
    <div style="display:flex; gap:10px;">
        <button class="btn" id="open-pricing-btn" style="background:#1d4ed8;">Управление Ценами</button>
        <a href="/download" class="btn">Скачать Excel</a>
        <a href="/" class="btn btn-outline">Загрузить заново</a>
    </div>
</div>

<div class="stats-grid">
    <div class="stat-card"><div class="num">{{ stats.consolidated }}</div><div class="label">Всего товаров</div></div>
    <div class="stat-card"><div class="num">{{ stats.suppliers }}</div><div class="label">Поставщиков</div></div>
    <div class="stat-card highlight"><div class="num">{{ stats.without_id }}</div><div class="label">Без OnlinerID</div></div>
    <div class="stat-card">
        <div class="num">-</div>
        <div style="display:flex; gap:8px; justify-content:center; flex-wrap:wrap;">
            <button class="btn" onclick="findIds()" id="find-btn" style="background:#43a047;padding:8px 16px;font-size:13px;">Найти ID</button>
            <button class="btn btn-outline" id="open-idcheck-btn" style="padding:8px 16px;font-size:13px;">Проверить ID</button>
        </div>
    </div>
</div>

<div class="table-card">
<table id="tbl-main" class="display" style="width:100%">
<thead><tr>
    <th>OnlinerID</th><th>Название</th><th>Лучшая цена</th><th>Поставщик</th><th>Гарантия</th><th>Под заказ</th><th>РРЦ</th>
</tr></thead>
<tbody id="tbl-main-body"></tbody>
</table>
</div>

</div>

<div id="idcheck-modal" class="idcheck-modal">
  <div class="idcheck-sheet">
    <div class="pricing-head">
      <div class="markup-title" style="margin:0;">Проверка OnlinerID По Категории (по вашему каталогу)</div>
      <button class="pricing-close" id="close-idcheck-btn">Закрыть</button>
    </div>
    <div class="idcheck-top">
      <div class="idcheck-cat-wrap">
        <label style="font-size:13px;color:#4b5563;">Категория</label>
        <input id="idcheck-category-search" class="idcheck-cat-search" type="text" placeholder="Поиск категории...">
        <select id="idcheck-category" class="idcheck-cat-select" size="8"></select>
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">Действие</label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <button class="btn btn-outline" id="idcheck-run-base-btn" style="padding:6px 8px;font-size:12px;">Проверить база</button>
          <button class="btn btn-outline" id="idcheck-run-api-btn" style="padding:6px 8px;font-size:12px;">Проверить API</button>
        </div>
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">Фильтр</label>
        <select id="idcheck-filter" style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;">
          <option value="issues">Только проблемы</option>
          <option value="noid">Только без ID</option>
          <option value="all">Все строки</option>
        </select>
      </div>
      <div class="idcheck-note" id="idcheck-summary">Выберите категорию и нажмите Проверить.</div>
    </div>
    <table class="idcheck-table">
      <thead><tr><th>Статус</th><th>OnlinerID</th><th>Название</th><th id="idcheck-col4">Каталог ID</th><th>Совпадение</th><th>Действие</th></tr></thead>
      <tbody id="idcheck-body"></tbody>
    </table>
    <details class="idreplace-box" open>
      <summary>К замене ID: <span id="idreplace-count">0</span></summary>
      <div id="idreplace-list" class="idreplace-list">Сначала запустите проверку категории.</div>
    </details>
  </div>
</div>

<div id="idreplace-modal" class="idreplace-modal">
  <div class="idreplace-sheet">
    <div class="pricing-head">
      <div class="markup-title" style="margin:0;">Заменить OnlinerID</div>
      <button class="pricing-close" id="idreplace-close-btn">Закрыть</button>
    </div>
    <div class="idreplace-note" id="idreplace-current">Товар: —</div>
    <div class="idreplace-grid">
      <div>
        <label style="font-size:13px;color:#4b5563;">Поиск в категории/API</label>
        <input id="idreplace-search" type="text" placeholder="Поиск товара..." style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:13px;">
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">Действие</label>
        <div style="width:100%;padding:8px 10px;border:1px dashed #cbd5e1;border-radius:8px;color:#64748b;font-size:12px;">Автопоиск через 2 секунды</div>
      </div>
    </div>
    <div style="margin-top:10px;">
      <select id="idreplace-candidates" class="idreplace-listbox" size="12"></select>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:10px;">
      <button class="btn btn-outline" id="idreplace-cancel-btn" style="padding:8px 12px;">Отмена</button>
      <button class="btn" id="idreplace-apply-btn" style="padding:8px 12px;background:#16a34a;">Подставить ID</button>
    </div>
    <div class="idreplace-note" id="idreplace-note">Выберите подходящий товар из списка.</div>
  </div>
</div>

<div id="pricing-modal" class="pricing-modal">
  <div class="pricing-sheet">
    <div class="pricing-head">
      <div class="markup-title" style="margin:0;">Управление Ценами И Категориями</div>
      <button class="pricing-close" id="close-pricing-btn">Закрыть</button>
    </div>

    <div class="markup-card">
        <div class="markup-title">Наценка РРЦ По Категориям</div>
        <div class="markup-top">
            <div class="markup-row">
                <div>
                    <label style="font-size:13px;color:#4b5563;">Категории (можно выбрать несколько)</label>
                    <select id="markup-categories" multiple></select>
                </div>
            </div>
            <div class="markup-actions">
                <button class="btn btn-outline" id="select-all-cats" style="padding:8px 12px;font-size:13px;">Выбрать Все</button>
                <button class="btn btn-outline" id="clear-all-cats" style="padding:8px 12px;font-size:13px;">Очистить Выбор</button>
                <button class="btn btn-outline" id="open-preview-modal-btn" style="padding:8px 12px;font-size:13px;">Предпросмотр</button>
                <button class="btn btn-outline" id="open-full-list-btn" style="padding:8px 12px;font-size:13px;">Смотреть Все</button>
            </div>
            <div class="markup-note" id="markup-note">Категории загружаются…</div>
        </div>
        <div class="markup-split">
            <div class="markup-left">
                <div class="preview-card" style="margin-top:0;">
                    <div class="preview-title">Наценка</div>
                    <div class="markup-controls">
                        <div>
                            <label style="font-size:13px;color:#4b5563;">Наценка, %</label>
                            <input type="number" id="markup-percent" min="0" step="0.1" value="10">
                        </div>
                        <div>
                            <button class="btn btn-outline apply-markup-btn-small" id="apply-markup-btn">Применить Наценку</button>
                        </div>
                    </div>
                </div>
                <div class="markup-map">
                    <table id="category-markup-table">
                        <thead><tr><th>Категория</th><th>Текущая Наценка (%)</th></tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
            <div class="markup-right">
                <div class="preview-card" style="margin-top:0;">
                    <div class="preview-title">Перенос Товаров</div>
                    <div class="preview-transfer">
                        <div>
                            <label style="font-size:13px;color:#4b5563;">Товары выбранных категорий (Shift/Ctrl)</label>
                            <select id="preview-items" multiple></select>
                        </div>
                        <div>
                            <label style="font-size:13px;color:#4b5563;">Перенести в категорию</label>
                            <input id="target-category-search" class="select-search" type="text" placeholder="Поиск категории...">
                            <select id="preview-target-category" size="8"></select>
                        </div>
                    </div>
                    <div class="transfer-action">
                        <button class="btn" id="preview-move-btn">Перенести</button>
                    </div>
                    <div class="markup-note" id="preview-items-note">Выберите категорию слева, затем переносите товары справа.</div>
                </div>
                <div class="preview-card">
                    <div class="preview-title">Скрыть/Показать Категории Поставщика</div>
                    <div class="visibility-row">
                        <div>
                            <label style="font-size:13px;color:#4b5563;">Поставщик</label>
                            <select id="supplier-select" size="8"></select>
                        </div>
                        <div>
                            <label style="font-size:13px;color:#4b5563;">Категории поставщика</label>
                            <select id="supplier-categories" multiple></select>
                        </div>
                    </div>
                    <div class="markup-actions">
                        <button class="btn" id="hide-cats-btn" style="padding:8px 12px;font-size:13px;">Скрыть Выбранные</button>
                        <button class="btn btn-outline" id="show-cats-btn" style="padding:8px 12px;font-size:13px;">Показать Выбранные</button>
                    </div>
                    <div class="markup-note" id="visibility-note">Выберите поставщика и категории.</div>
                </div>
            </div>
        </div>
    </div>

  </div>
</div>

<div id="full-list-modal" class="full-list-modal">
  <div class="full-list-sheet">
    <div class="pricing-head">
      <div class="markup-title" style="margin:0;">Все Товары Выбранных Категорий</div>
      <button class="pricing-close" id="close-full-list-btn">Закрыть</button>
    </div>
    <div class="preview-transfer" style="margin-top:0;">
      <div>
        <label style="font-size:13px;color:#4b5563;">Товары (Shift/Ctrl для мультивыбора)</label>
        <select id="full-list-items" multiple></select>
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">Перенести в категорию</label>
        <input id="full-target-category-search" class="select-search" type="text" placeholder="Поиск категории...">
        <select id="full-list-target-category" size="8"></select>
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">Действие</label>
        <button class="btn" id="full-list-move-btn" style="width:100%;padding:10px 12px;">Перенести Выбранные</button>
      </div>
    </div>
    <div class="markup-note" id="full-list-note">Список загружается…</div>
    <table id="full-list-table" class="full-list-table">
      <thead><tr><th>Категория</th><th>Товар</th><th>Поставщик</th><th>Цена</th><th>РРЦ</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div id="preview-modal" class="preview-modal">
  <div class="preview-sheet">
    <div class="pricing-head">
      <div class="markup-title" style="margin:0;">Предпросмотр Наценки По Выбранным Категориям</div>
      <button class="pricing-close" id="close-preview-btn">Закрыть</button>
    </div>
    <div class="preview-grid">
      <div>
        <label style="font-size:13px;color:#4b5563;">Наценка, %</label>
        <input type="number" id="preview-percent" min="0" step="0.1" value="10">
      </div>
      <div>
        <label style="font-size:13px;color:#4b5563;">База расчета</label>
        <select id="preview-base-mode" style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;">
          <option value="wholesale">От оптовой (Лучшая цена)</option>
          <option value="onliner_min">От Onliner Минимальной</option>
          <option value="onliner_avg">От Onliner Средней</option>
        </select>
      </div>
      <div>
        <button class="btn" id="preview-apply-btn" style="width:100%;">Сохранить И Применить</button>
      </div>
      <div>
        <button class="btn btn-outline" id="refresh-market-btn" style="width:100%;">Обновить Цены Onliner</button>
      </div>
    </div>
    <div class="markup-note" id="preview-modal-note">Показаны все товары выбранных категорий. При изменении процента таблица пересчитывается сразу.</div>
    <div class="markup-note" id="market-refresh-note" style="margin-top:4px;">Кэш Onliner: используется мгновенно. Обновление запускается вручную.</div>
    <div style="margin-top:8px;">
      <label style="font-size:13px;color:#4b5563;">Категории в этом окне (можно выбрать несколько)</label>
      <select id="preview-modal-categories" multiple style="width:100%;min-height:96px;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:13px;"></select>
    </div>
    <table id="preview-full-table" class="preview-full-table">
      <thead><tr><th>OnlinerID</th><th>Категория</th><th>Товар</th><th>Поставщик</th><th>Опт</th><th>Onliner Мин</th><th>Onliner Ср</th><th>Onliner Макс</th><th>Текущая РРЦ</th><th>Новая РРЦ</th><th>Маржа, %</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div id="find-progress-modal" class="progress-modal">
  <div class="progress-card">
    <div class="progress-head">
      <div>
        <div class="progress-title">Поиск OnlinerID</div>
        <div class="progress-subtitle" id="progress-subtitle">Запускаем процесс сопоставления…</div>
      </div>
      <div id="progress-spinner" class="progress-spinner"></div>
    </div>

    <div class="phase-grid">
      <div class="phase-item">
        <div class="row">
          <div class="name">Этап 1: Google Sheets (All_Catalog)</div>
          <span class="phase-pill" id="sheet-pill">Ожидание</span>
        </div>
        <div class="meta" id="sheet-meta">0 / 0 проверено, найдено: 0</div>
      </div>
      <div class="phase-item">
        <div class="row">
          <div class="name">Этап 2: Onliner API (отключен)</div>
          <span class="phase-pill" id="api-pill">Ожидание</span>
        </div>
        <div class="meta" id="api-meta">Пропущен</div>
      </div>
    </div>

    <div class="progress-line-wrap">
      <div class="progress-line"><div id="progress-fill"></div></div>
    </div>

    <div class="progress-stats">
      <div class="mini-stat"><div class="v" id="stat-found">0</div><div class="t">Найдено</div></div>
      <div class="mini-stat"><div class="v" id="stat-not-found">0</div><div class="t">Не найдено</div></div>
      <div class="mini-stat"><div class="v" id="stat-total">0</div><div class="t">Всего в работе</div></div>
    </div>

    <div class="progress-actions">
      <button id="progress-close" class="progress-close" onclick="closeProgressModal()">Закрыть</button>
    </div>
  </div>
</div>

<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js"></script>
<script>
var dtLang = {url:'//cdn.datatables.net/plug-ins/1.13.7/i18n/ru.json'};
var tblMain = null;
var mainTableRows = [];
var previewTimer = null;
var UI_STATE_KEY = 'price_mixer_ui_state_v1';
var categoryMarkups = {};
var categoryCatalog = [];
var previewModalItems = [];
var previewModalRequestSeq = 0;
var marketRefreshPollTimer = null;
var idCheckRows = [];
var idCheckMap = {};
var idCheckCategories = [];
var idCheckMode = 'base';
var idCheckCurrentCategory = '';
var idCheckResultCache = {};
var idCheckAutoClearDone = {};
var idCheckRunId = 0;
var idReplaceRowIdx = -1;
var idReplaceCandidates = [];
var idReplaceSearchTimer = null;
var CATEGORY_PRIORITY_JS = [
    'Процессор',
    'Кулер',
    'Охлаждение',
    'Материнская плата',
    'Оперативная память',
    'SSD',
    'Жесткий диск',
    'Видеокарта',
    'Блок питания',
    'Корпус',
    'Монитор'
];

$(document).ready(function(){
    if(window.jQuery && $.fn && $.fn.DataTable){
        tblMain = $('#tbl-main').DataTable({
            ajax: '/api/consolidated',
            deferRender: true,
            pageLength: 100,
            order: [[1, 'asc']],
            language: dtLang,
            columns: [
                {data: 0, render: function(d){return d ? '<b style="color:#2e7d32">'+d+'</b>' : '<span style="color:#e65100">нет</span>';}}, 
                {data: 1},
                {data: 2, render: function(d){return d ? '<b style="color:#2e7d32">'+parseFloat(d).toFixed(2)+'</b>' : '';}}, 
                {data: 3},
                {data: 4},
                {data: 5},
                {data: 6, render: function(d){ return (d || d===0) ? parseFloat(d).toFixed(2) : ''; }}
            ]
        });
    } else {
        initMainTableFallback();
    }
    initIdCheckUI();
    initMarkupUI();
});

function initMainTableFallback(){
    var tbody = document.getElementById('tbl-main-body');
    if(!tbody){ return; }
    fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
        mainTableRows = (d && d.data) ? d.data : [];
        renderMainTableFallback();
    }).catch(function(){
        tbody.innerHTML = '<tr><td colspan="7" style="padding:14px;color:#b91c1c;">Ошибка загрузки данных</td></tr>';
    });
    tblMain = {
        ajax: {
            reload: function(cb){
                fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
                    mainTableRows = (d && d.data) ? d.data : [];
                    renderMainTableFallback();
                    if(typeof cb === 'function'){ cb(); }
                }).catch(function(){
                    if(typeof cb === 'function'){ cb(); }
                });
            }
        }
    };
}

function renderMainTableFallback(){
    var tbody = document.getElementById('tbl-main-body');
    if(!tbody){ return; }
    var rows = (mainTableRows || []).slice().sort(function(a,b){
        return String(a[1] || '').localeCompare(String(b[1] || ''), 'ru');
    });
    if(!rows.length){
        tbody.innerHTML = '<tr><td colspan="7" style="padding:14px;color:#64748b;">Нет данных</td></tr>';
        return;
    }
    var html = '';
    rows.forEach(function(r){
        var oid = String(r[0] || '').trim();
        var name = escapeHtml(r[1] || '');
        var price = (r[2] || r[2]===0) ? ('<b style="color:#2e7d32">' + Number(r[2]).toFixed(2) + '</b>') : '';
        var supplier = escapeHtml(r[3] || '');
        var warranty = escapeHtml(r[4] || '');
        var lead = escapeHtml(r[5] || '');
        var rrc = (r[6] || r[6]===0) ? Number(r[6]).toFixed(2) : '';
        html += '<tr>'
            + '<td>' + (oid ? ('<b style="color:#2e7d32">' + escapeHtml(oid) + '</b>') : '<span style="color:#e65100">нет</span>') + '</td>'
            + '<td>' + name + '</td>'
            + '<td>' + price + '</td>'
            + '<td>' + supplier + '</td>'
            + '<td>' + warranty + '</td>'
            + '<td>' + lead + '</td>'
            + '<td>' + rrc + '</td>'
            + '</tr>';
    });
    tbody.innerHTML = html;
}

function escapeHtml(text){
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function initIdCheckUI(){
    var openBtn = document.getElementById('open-idcheck-btn');
    var closeBtn = document.getElementById('close-idcheck-btn');
    var modal = document.getElementById('idcheck-modal');
    var runBaseBtn = document.getElementById('idcheck-run-base-btn');
    var runApiBtn = document.getElementById('idcheck-run-api-btn');
    var filterSel = document.getElementById('idcheck-filter');
    var catSearch = document.getElementById('idcheck-category-search');
    var replaceModal = document.getElementById('idreplace-modal');
    var replaceCloseBtn = document.getElementById('idreplace-close-btn');
    var replaceCancelBtn = document.getElementById('idreplace-cancel-btn');
    var replaceApplyBtn = document.getElementById('idreplace-apply-btn');
    var replaceSearch = document.getElementById('idreplace-search');
    if(!openBtn || !closeBtn || !modal || !runBaseBtn || !runApiBtn || !filterSel || !catSearch || !replaceModal){ return; }

    openBtn.addEventListener('click', function(){
        modal.classList.add('active');
        loadIdCheckCategories();
    });
    closeBtn.addEventListener('click', function(){ modal.classList.remove('active'); });
    modal.addEventListener('click', function(e){ if(e.target.id === 'idcheck-modal'){ modal.classList.remove('active'); } });
    runBaseBtn.addEventListener('click', function(){ runIdCheckForSelectedCategory('base', true); });
    runApiBtn.addEventListener('click', function(){ runIdCheckForSelectedCategory('api', true); });
    filterSel.addEventListener('change', renderIdCheckRows);
    catSearch.addEventListener('input', function(){
        renderIdCheckCategories(this.value || '');
    });
    if(replaceCloseBtn){ replaceCloseBtn.addEventListener('click', closeIdReplaceModal); }
    if(replaceCancelBtn){ replaceCancelBtn.addEventListener('click', closeIdReplaceModal); }
    if(replaceApplyBtn){ replaceApplyBtn.addEventListener('click', applyIdReplaceSelection); }
    if(replaceSearch){
        replaceSearch.addEventListener('keydown', function(e){
            if(e.key === 'Enter'){
                e.preventDefault();
                loadIdReplaceCandidates(false);
            }
        });
        replaceSearch.addEventListener('input', function(){
            if(idReplaceSearchTimer){ clearTimeout(idReplaceSearchTimer); }
            idReplaceSearchTimer = setTimeout(function(){
                loadIdReplaceCandidates(false);
            }, 2000);
        });
    }
    replaceModal.addEventListener('click', function(e){
        if(e.target && e.target.id === 'idreplace-modal'){ closeIdReplaceModal(); }
    });
    document.getElementById('idcheck-body').addEventListener('click', function(e){
        var btn = e.target.closest('.idcheck-bind-btn');
        if(btn){
            var idx = parseInt(btn.getAttribute('data-idx') || '-1', 10);
            if(idx < 0 || idx >= idCheckRows.length){ return; }
            openIdReplaceModal(idx);
            return;
        }
    });
}

function getIdCheckCacheKey(mode, category){
    return String(mode || 'base') + '|' + String(category || '');
}

function getIdCheckRowsSignature(rows){
    var list = Array.isArray(rows) ? rows : [];
    var keys = list.map(function(r){
        return String(r.key || '') + '::' + String(r.onliner_id || '');
    }).sort();
    return keys.join('|');
}

function loadIdCheckCategories(){
    fetch('/api/category-catalog').then(function(r){ return r.json(); }).then(function(d){
        var cats = (d.categories || []).map(function(x){
            return (typeof x === 'string') ? x : x.name;
        }).filter(function(x){ return !!x; });
        if(!cats.length){
            return fetch('/api/categories').then(function(r){ return r.json(); }).then(function(fb){
                cats = (fb.categories || []).map(function(x){ return x.name; }).filter(function(x){ return !!x; });
                idCheckCategories = cats;
                renderIdCheckCategories('');
            });
        }
        idCheckCategories = cats;
        renderIdCheckCategories('');
    }).catch(function(){
        var summary = document.getElementById('idcheck-summary');
        if(summary){ summary.textContent = 'Не удалось загрузить категории'; }
    });
}

function renderIdCheckCategories(query){
    var sel = document.getElementById('idcheck-category');
    var summary = document.getElementById('idcheck-summary');
    if(!sel){ return; }
    var q = String(query || '').trim().toLowerCase();
    var filtered = idCheckCategories.filter(function(c){
        return !q || String(c).toLowerCase().indexOf(q) !== -1;
    });
    var prev = sel.value;
    sel.innerHTML = '';
    filtered.forEach(function(c){
        var opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        sel.appendChild(opt);
    });
    if(filtered.length){
        sel.value = filtered.indexOf(prev) >= 0 ? prev : filtered[0];
    }
    if(summary){
        summary.textContent = 'Категорий загружено: ' + idCheckCategories.length + '. Отфильтровано: ' + filtered.length + '.';
    }
}

function runIdCheckForSelectedCategory(mode, forceRefresh){
    idCheckMode = mode || 'base';
    idCheckRunId += 1;
    var currentRunId = idCheckRunId;
    var h4 = document.getElementById('idcheck-col4');
    if(h4){
        h4.textContent = (idCheckMode === 'api') ? 'API товар' : 'Каталог ID';
    }
    var sel = document.getElementById('idcheck-category');
    if(!sel || !sel.value){ return; }
    var category = sel.value;
    idCheckCurrentCategory = category;
    var summary = document.getElementById('idcheck-summary');
    if(summary){ summary.textContent = 'Загрузка категории ' + category + '...'; }
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({categories:[category], limit:6000, with_market:false, for_idcheck:true})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(currentRunId !== idCheckRunId){ return; }
        idCheckRows = Array.isArray(d.items) ? d.items : [];
        idCheckMap = {};
        var cacheKey = getIdCheckCacheKey(idCheckMode, category);
        if(forceRefresh){
            delete idCheckResultCache[cacheKey];
        }
        var signature = getIdCheckRowsSignature(idCheckRows);
        var cached = idCheckResultCache[cacheKey];
        if(cached && cached.signature === signature && cached.map){
            idCheckMap = Object.assign({}, cached.map);
        }
        // Для API-проверки не гоняем повторно уже подтвержденные базой строки.
        if(idCheckMode === 'api'){
            var baseCached = idCheckResultCache[getIdCheckCacheKey('base', category)];
            if(baseCached && baseCached.signature === signature && baseCached.map){
                Object.keys(baseCached.map).forEach(function(k){
                    var bi = baseCached.map[k] || {};
                    var st = String(bi.status || '');
                    if(st === 'match' || st === 'no_id'){
                        idCheckMap[k] = {
                            status: st,
                            score: Number(bi.score || 0),
                            api_id: '',
                            api_name: '',
                            url: '',
                        };
                    }
                });
            }
        }
        // Instant fallback rendering to avoid empty table even if detailed render fails.
        var tbody = document.getElementById('idcheck-body');
        if(tbody){
            var quick = '';
            idCheckRows.forEach(function(r){
                quick += '<tr>'
                    + '<td class=\"idcheck-status-warn\">Ожидание</td>'
                    + '<td>' + escapeHtml(r.onliner_id || '') + '</td>'
                    + '<td>' + escapeHtml(r.name || '') + '</td>'
                    + '<td></td><td>0.00</td><td></td>'
                    + '</tr>';
            });
            tbody.innerHTML = quick || '<tr><td colspan=\"6\" style=\"color:#64748b;\">Нет строк для отображения</td></tr>';
        }
        renderIdCheckRows();
        if(!idCheckRows.length){
            if(summary){ summary.textContent = 'В категории нет товаров.'; }
            return;
        }
        if(cached && cached.signature === signature && cached.map){
            var checkedFromCache = idCheckRows.reduce(function(acc, r){
                return acc + (idCheckMap[r.key] ? 1 : 0);
            }, 0);
            if(summary){ summary.textContent = 'Проверка загружена из кэша: ' + checkedFromCache + '/' + idCheckRows.length; }
            return;
        }
        if(idCheckMode === 'base'){
            if(summary){ summary.textContent = 'Проверка базы...'; }
            var baseCtl = new AbortController();
            var baseTimer = setTimeout(function(){ baseCtl.abort(); }, 90000);
            fetch('/api/id-verify-category-base', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({category: category, limit: 6000}),
                signal: baseCtl.signal
            }).then(function(r){ return r.json(); }).then(function(v){
                clearTimeout(baseTimer);
                if(currentRunId !== idCheckRunId){ return; }
                var arr = Array.isArray((v || {}).items) ? v.items : [];
                idCheckMap = {};
                arr.forEach(function(it){ idCheckMap[it.key] = it; });
                var ck = getIdCheckCacheKey(idCheckMode, category);
                idCheckResultCache[ck] = {
                    signature: getIdCheckRowsSignature(idCheckRows),
                    map: Object.assign({}, idCheckMap),
                    ts: Date.now(),
                };
                renderIdCheckRows();
            }).catch(function(err){
                clearTimeout(baseTimer);
                if(currentRunId !== idCheckRunId){ return; }
                var msg = (err && err.name === 'AbortError')
                    ? 'Таймаут проверки базы. Повторите.'
                    : 'Ошибка проверки базы. Повторите.';
                if(summary){ summary.textContent = msg; }
            });
            return;
        }
        verifyIdCheckRowsInBatches(idCheckMode, currentRunId);
    }).catch(function(){
        if(currentRunId !== idCheckRunId){ return; }
        if(summary){ summary.textContent = 'Ошибка загрузки категории'; }
    });
}

function verifyIdCheckRowsInBatches(mode, runId){
    if(runId !== idCheckRunId){ return; }
    var pending = idCheckRows.filter(function(r){ return !idCheckMap[r.key]; });
    if(!pending.length){
        var ck = getIdCheckCacheKey(mode, idCheckCurrentCategory);
        idCheckResultCache[ck] = {
            signature: getIdCheckRowsSignature(idCheckRows),
            map: Object.assign({}, idCheckMap),
            ts: Date.now(),
        };
        renderIdCheckRows();
        maybeAutoClearInvalidIdsAfterApiCheck(mode, ck);
        return;
    }
    var summary = document.getElementById('idcheck-summary');
    var checked = idCheckRows.reduce(function(acc, r){
        return acc + (idCheckMap[r.key] ? 1 : 0);
    }, 0);
    if(summary){ summary.textContent = 'Проверка... ' + checked + '/' + idCheckRows.length; }
    var batchSize = (mode === 'api') ? 8 : 25;
    // Для base-проверки первый батч может долго грузить индекс All_Catalog.
    var requestTimeoutMs = (mode === 'api') ? 45000 : 70000;
    var batch = pending.slice(0, batchSize).map(function(r){
        return {key:r.key, id:r.onliner_id, name:r.name, category:r.category};
    });
    var ctl = new AbortController();
    var t = setTimeout(function(){ ctl.abort(); }, requestTimeoutMs);
    var endpoint = (mode === 'api') ? '/api/id-verify-api-batch' : '/api/id-verify-batch';
    fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({items:batch}),
        signal: ctl.signal
    }).then(function(r){ return r.json(); }).then(function(d){
        if(runId !== idCheckRunId){ return; }
        clearTimeout(t);
        (d.items || []).forEach(function(it){ idCheckMap[it.key] = it; });
        renderIdCheckRows();
        setTimeout(function(){ verifyIdCheckRowsInBatches(mode, runId); }, 60);
    }).catch(function(){
        if(runId !== idCheckRunId){ return; }
        clearTimeout(t);
        // keep UI progressing even if one batch fails
        batch.forEach(function(it){
            if(!idCheckMap[it.key]){
                idCheckMap[it.key] = {status:'unverified', score:0, catalog_id:'', catalog_name:'', url:''};
            }
        });
        renderIdCheckRows();
        setTimeout(function(){ verifyIdCheckRowsInBatches(mode, runId); }, 250);
    });
}

function maybeAutoClearInvalidIdsAfterApiCheck(mode, cacheKey){
    if(mode !== 'api'){ return; }
    if(idCheckAutoClearDone[cacheKey]){ return; }
    var badRows = [];
    (idCheckRows || []).forEach(function(r){
        var info = idCheckMap[r.key] || {};
        if(String(info.status || '') === 'mismatch'){
            badRows.push({key:r.key, onliner_id:r.onliner_id || ''});
        }
    });
    if(!badRows.length){
        idCheckAutoClearDone[cacheKey] = true;
        return;
    }
    fetch('/api/clear-invalid-onliner-ids', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({items: badRows})
    }).then(function(r){ return r.json(); }).then(function(d){
        idCheckAutoClearDone[cacheKey] = true;
        var cleared = Number((d || {}).cleared || 0);
        if(cleared > 0){
            (idCheckRows || []).forEach(function(r){
                var info = idCheckMap[r.key] || {};
                if(String(info.status || '') === 'mismatch'){
                    r.onliner_id = '';
                    idCheckMap[r.key] = {status:'no_id', score:0, api_name:'', api_id:'', url:''};
                }
            });
            var summary = document.getElementById('idcheck-summary');
            if(summary){
                summary.textContent = 'Очищено невалидных ID: ' + cleared + '. Строки без валидного ID помечены как "Нет ID".';
            }
            renderIdCheckRows();
            if(tblMain && tblMain.ajax && tblMain.ajax.reload){ tblMain.ajax.reload(null, false); }
        }
    }).catch(function(){
        // no-op: keep user flow uninterrupted
    });
}

function idCheckStatusClass(st){
    if(st === 'match'){ return 'idcheck-status-ok'; }
    if(st === 'mismatch'){ return 'idcheck-status-bad'; }
    return 'idcheck-status-warn';
}

function idCheckStatusText(st){
    if(st === 'match'){ return 'Совпало'; }
    if(st === 'mismatch'){ return 'Не совпало'; }
    if(st === 'no_id'){ return 'Нет ID'; }
    return 'Не подтверждено';
}

function renderIdCheckRows(){
    try {
        var tbody = document.getElementById('idcheck-body');
        var summary = document.getElementById('idcheck-summary');
        if(!tbody){ return; }
        var filter = (document.getElementById('idcheck-filter') || {}).value || 'issues';
        var sourceRows = Array.isArray(idCheckRows) ? idCheckRows : [];
        var rows = [];
        var replaceRows = [];
        var ok = 0, bad = 0, noid = 0, unc = 0;
        sourceRows.forEach(function(r, idx){
            var info = idCheckMap[r.key] || {status: (r.onliner_id ? 'unverified' : 'no_id'), score:0, catalog_id:'', catalog_name:'', api_name:''};
            if(info.status === 'match'){ ok += 1; }
            else if(info.status === 'mismatch'){ bad += 1; }
            else if(info.status === 'no_id'){ noid += 1; }
            else { unc += 1; }
            if(info.status !== 'match'){
                replaceRows.push({item:r, info:info});
            }
            if(filter === 'issues' && info.status === 'match'){ return; }
            if(filter === 'noid' && info.status !== 'no_id'){ return; }
            rows.push({idx:idx, item:r, info:info});
        });
        if(summary){
            var checkedNow = sourceRows.reduce(function(acc, r){
                return acc + (idCheckMap[r.key] ? 1 : 0);
            }, 0);
            summary.textContent = 'Проверено: ' + checkedNow + '/' + sourceRows.length
                + '. Совпало: ' + ok + ', не совпало: ' + bad + ', нет ID: ' + noid + ', нет в каталоге: ' + unc + '.';
        }
        renderIdReplaceList(replaceRows);
        if(!rows.length){
            tbody.innerHTML = '<tr><td colspan=\"6\" style=\"color:#64748b;\">Нет строк для отображения</td></tr>';
            return;
        }
        var html = '';
        rows.forEach(function(x){
            var st = x.info.status || 'unverified';
            var suggested = '';
            if(idCheckMode === 'api'){
                var apiName = String(x.info.api_name || '').trim();
                var apiUrl = String(x.info.url || '').trim();
                if(apiName && apiUrl){
                    suggested = '<a href=\"' + escapeHtml(apiUrl) + '\" target=\"_blank\" rel=\"noopener noreferrer\">'
                        + escapeHtml(apiName) + '</a>';
                } else if(apiName){
                    suggested = escapeHtml(apiName);
                } else {
                    suggested = '<span style=\"color:#94a3b8;\">API не вернул товар</span>';
                }
            } else {
                suggested = escapeHtml(x.info.catalog_id || '');
            }
            var action = '';
            if(st !== 'match'){
                action = '<button class=\"btn btn-outline idcheck-bind-btn\" data-idx=\"'+x.idx+'\" style=\"padding:6px 10px;font-size:12px;\">Заменить ID</button>';
            }
            html += '<tr>'
                + '<td class=\"'+idCheckStatusClass(st)+'\">'+idCheckStatusText(st)+'</td>'
                + '<td>'+escapeHtml(x.item.onliner_id || '')+'</td>'
                + '<td>'+escapeHtml(x.item.name || '')+'</td>'
                + '<td>'+suggested+'</td>'
                + '<td>'+Number(x.info.score || 0).toFixed(2)+'</td>'
                + '<td>'+action+'</td>'
                + '</tr>';
        });
        tbody.innerHTML = html;
    } catch (e) {
        var tbodyErr = document.getElementById('idcheck-body');
        if(tbodyErr){
            tbodyErr.innerHTML = '<tr><td colspan=\"6\" style=\"color:#b91c1c;\">Ошибка рендера. Повторите проверку категории.</td></tr>';
        }
    }
}

function openIdReplaceModal(idx){
    var row = idCheckRows[idx];
    var modal = document.getElementById('idreplace-modal');
    if(!row || !modal){ return; }
    idReplaceRowIdx = idx;
    idReplaceCandidates = [];
    var current = document.getElementById('idreplace-current');
    var note = document.getElementById('idreplace-note');
    var search = document.getElementById('idreplace-search');
    var select = document.getElementById('idreplace-candidates');
    var applyBtn = document.getElementById('idreplace-apply-btn');
    if(current){
        current.textContent = 'Товар: ' + (row.name || '') + ' | Текущий ID: ' + (row.onliner_id || 'нет');
    }
    if(note){ note.textContent = 'Автопоиск запустится через 2 секунды...'; }
    if(applyBtn){ applyBtn.disabled = false; }
    if(search){
        search.value = buildIdReplaceSearchSeed(String(row.name || ''), String(row.category || '')).slice(0, 120);
    }
    if(select){ select.innerHTML = ''; }
    var info = idCheckMap[row.key] || {};
    var quick = [];
    var currentId = String(row.onliner_id || '').trim();
    if(currentId){
        quick.push({id: currentId, name: 'Текущий ID', url: '', score: 0.0, source: 'current'});
    }
    var suggestedId = String((idCheckMode === 'api' ? info.api_id : info.catalog_id) || '').trim();
    var suggestedName = String((idCheckMode === 'api' ? info.api_name : info.catalog_name) || '').trim();
    var suggestedUrl = String(info.url || '').trim();
    if(suggestedId && (!currentId || suggestedId !== currentId)){
        quick.push({id: suggestedId, name: suggestedName || 'Предложенный вариант', url: suggestedUrl, score: Number(info.score || 0), source: 'suggested'});
    }
    idReplaceCandidates = quick.slice();
    if(select){
        if(idReplaceCandidates.length){
            idReplaceCandidates.forEach(function(it, i){
                var opt = document.createElement('option');
                opt.value = String(it.id || '');
                opt.textContent = (it.id || '-') + ' | ' + (it.name || '');
                select.appendChild(opt);
            });
            select.selectedIndex = 0;
        } else {
            select.innerHTML = '<option value="">Загрузка...</option>';
        }
    }
    modal.classList.add('active');
    if(idReplaceSearchTimer){ clearTimeout(idReplaceSearchTimer); }
    idReplaceSearchTimer = setTimeout(function(){
        loadIdReplaceCandidates(true);
    }, 2000);
}

function buildIdReplaceSearchSeed(name, category){
    var n = String(name || '').trim();
    var c = String(category || '').trim();
    if(!n){ return ''; }
    if(!c){ return n; }
    var spec = '^$\\\\.*+?()[]{}|';
    var esc = '';
    for(var i=0;i<c.length;i++){
        var ch = c.charAt(i);
        esc += (spec.indexOf(ch) >= 0 ? '\\\\' + ch : ch);
    }
    // Убираем категорию только в начале строки: "Процессор ...", "Видеокарта ..."
    n = n.replace(new RegExp('^\\s*' + esc + '\\s*', 'i'), '').trim();
    return n;
}

function closeIdReplaceModal(){
    var modal = document.getElementById('idreplace-modal');
    var applyBtn = document.getElementById('idreplace-apply-btn');
    if(modal){ modal.classList.remove('active'); }
    if(applyBtn){ applyBtn.disabled = false; }
    idReplaceRowIdx = -1;
    idReplaceCandidates = [];
}

function normalizeOnlinerIdJs(value){
    var text = String(value || '').trim();
    if(!text){ return ''; }
    if(text.endsWith('.0')){ text = text.slice(0, -2); }
    var m = text.match(/[0-9]+/);
    return m ? m[0] : '';
}

function loadIdReplaceCandidates(preload){
    if(idReplaceRowIdx < 0 || idReplaceRowIdx >= idCheckRows.length){ return; }
    var row = idCheckRows[idReplaceRowIdx];
    var note = document.getElementById('idreplace-note');
    var select = document.getElementById('idreplace-candidates');
    var q = (document.getElementById('idreplace-search') || {}).value || '';
    if(note){ note.textContent = 'Ищем варианты...'; }
    var ctl = new AbortController();
    var t = setTimeout(function(){ ctl.abort(); }, 20000);
    fetch('/api/id-replace-candidates', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
            name: row.name || '',
            category: row.category || '',
            supplier: row.supplier || '',
            onliner_id: row.onliner_id || '',
            query: q,
            limit: preload ? 80 : 120,
        }),
        signal: ctl.signal
    }).then(function(r){ return r.json(); }).then(function(d){
        clearTimeout(t);
        idReplaceCandidates = Array.isArray(d.items) ? d.items : [];
        if(!select){ return; }
        select.innerHTML = '';
        if(!idReplaceCandidates.length){
            select.innerHTML = '<option value="">Ничего не найдено</option>';
            if(note){ note.textContent = 'Варианты не найдены. Уточните поиск.'; }
            return;
        }
        idReplaceCandidates.forEach(function(it, i){
            var opt = document.createElement('option');
            opt.value = String(it.id || '');
            var mark = (it.score || it.score===0) ? (' | score ' + Number(it.score).toFixed(2)) : '';
            var scoreVal = Number(it.score || 0);
            var tag = '';
            if(scoreVal >= 0.72){ tag = '[MATCH] '; }
            else if(scoreVal >= 0.52){ tag = '[~] '; }
            opt.textContent = tag + (it.id || '-') + ' | ' + (it.name || '') + mark;
            if(scoreVal >= 0.72){
                opt.style.backgroundColor = '#fef3c7'; // yellow highlight
            }
            select.appendChild(opt);
        });
        select.selectedIndex = 0;
        if(note){ note.textContent = 'Найдено вариантов: ' + idReplaceCandidates.length + '. [MATCH] выделены желтым.'; }
    }).catch(function(){
        clearTimeout(t);
        if(note){ note.textContent = 'Поиск занял слишком долго. Уточните запрос (модель/артикул).'; }
        if(select && !select.options.length){
            select.innerHTML = '<option value="">Ошибка загрузки вариантов</option>';
        }
    });
}

function applyIdReplaceSelection(){
    if(idReplaceRowIdx < 0 || idReplaceRowIdx >= idCheckRows.length){ return; }
    var row = idCheckRows[idReplaceRowIdx];
    var select = document.getElementById('idreplace-candidates');
    var summary = document.getElementById('idcheck-summary');
    if(!select || select.selectedIndex < 0){
        if(summary){ summary.textContent = 'Выберите товар из списка для замены ID'; }
        return;
    }
    var raw = String((select.options[select.selectedIndex] || {}).value || '').trim();
    var oid = normalizeOnlinerIdJs(raw);
    var cand = null;
    if(oid && oid.length >= 6){
        cand = (idReplaceCandidates || []).find(function(x){
            return normalizeOnlinerIdJs((x || {}).id) === oid;
        }) || null;
    } else {
        var idx = parseInt(raw, 10);
        if(isNaN(idx) || idx < 0){
            idx = select.selectedIndex;
        }
        cand = idReplaceCandidates[idx] || null;
        oid = normalizeOnlinerIdJs((cand || {}).id);
    }
    if(!oid){
        if(summary){ summary.textContent = 'Не удалось прочитать выбранный вариант'; }
        return;
    }
    if(normalizeOnlinerIdJs(row.onliner_id) === oid){
        if(summary){ summary.textContent = 'Этот ID уже установлен'; }
        closeIdReplaceModal();
        return;
    }
    var replaceNote = document.getElementById('idreplace-note');
    if(replaceNote){ replaceNote.textContent = 'Сохраняем ID...'; }
    var applyBtn = document.getElementById('idreplace-apply-btn');
    if(applyBtn){ applyBtn.disabled = true; }
    fetch('/api/manual-id-bind', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
            name: row.name,
            supplier: row.supplier,
            item_key: row.key,
            row_idx: row.row_idx,
            onliner_id: oid,
            url: ((cand || {}).url || '')
        })
    }).then(function(r){
        return r.json().then(function(d){ return {ok:r.ok, data:d}; });
    }).then(function(resp){
        var d = resp.data || {};
        if(!resp.ok || d.status !== 'ok'){
            var msg = d.message || 'Не удалось сохранить замену ID';
            if(summary){ summary.textContent = msg; }
            if(replaceNote){ replaceNote.textContent = msg; }
            if(applyBtn){ applyBtn.disabled = false; }
            return;
        }
        if(d.status !== 'ok'){
            if(summary){ summary.textContent = d.message || 'Не удалось сохранить замену ID'; }
            if(applyBtn){ applyBtn.disabled = false; }
            return;
        }
        row.onliner_id = String(oid);
        idCheckMap[row.key] = null;
        delete idCheckResultCache[getIdCheckCacheKey(idCheckMode, idCheckCurrentCategory)];
        if(summary){ summary.textContent = 'ID сохранен. Обновлено строк: ' + String(d.updated || 0) + '. Перепроверка…'; }
        if(replaceNote){ replaceNote.textContent = 'ID сохранен. Обновлено строк: ' + String(d.updated || 0); }
        closeIdReplaceModal();
        runIdCheckForSelectedCategory(idCheckMode, true);
        if(tblMain && tblMain.ajax && tblMain.ajax.reload){ tblMain.ajax.reload(null, false); }
    }).catch(function(){
        if(summary){ summary.textContent = 'Ошибка сохранения ID'; }
        if(replaceNote){ replaceNote.textContent = 'Ошибка сохранения ID. Повторите.'; }
        if(applyBtn){ applyBtn.disabled = false; }
    });
}

function renderIdReplaceList(replaceRows){
    var cnt = document.getElementById('idreplace-count');
    var list = document.getElementById('idreplace-list');
    if(cnt){ cnt.textContent = String((replaceRows || []).length); }
    if(!list){ return; }
    if(!replaceRows || !replaceRows.length){
        list.innerHTML = 'Проблемных товаров нет.';
        return;
    }
    var html = '';
    replaceRows.forEach(function(x){
        var cur = String(x.item.onliner_id || '').trim() || 'нет ID';
        var suggested = '';
        if(idCheckMode === 'api'){
            var apiId = String(x.info.api_id || '').trim();
            var apiName = String(x.info.api_name || '').trim();
            var apiUrl = String(x.info.url || '').trim();
            if(apiName && apiUrl){
                suggested = (apiId ? ('<b>' + escapeHtml(apiId) + '</b> -> ') : '')
                    + '<a href=\"' + escapeHtml(apiUrl) + '\" target=\"_blank\" rel=\"noopener noreferrer\">'
                    + escapeHtml(apiName) + '</a>';
            } else {
                suggested = (apiId ? ('<b>' + escapeHtml(apiId) + '</b>') : escapeHtml(apiName || 'API не вернул товар'));
            }
        } else {
            suggested = escapeHtml(x.info.catalog_id || 'нет предложения');
        }
        html += '<div style=\"padding:4px 0;border-bottom:1px dashed #dbe2ea;\">'
            + '<b>' + escapeHtml(cur) + '</b>'
            + ' -> '
            + '<span>' + suggested + '</span>'
            + '<br><span style=\"color:#64748b;\">' + escapeHtml(x.item.name || '') + '</span>'
            + '</div>';
    });
    list.innerHTML = html;
}

function getSelectedValues(selectId){
    var sel = document.getElementById(selectId);
    return Array.from(sel.options).filter(function(o){ return o.selected; }).map(function(o){ return o.value; });
}

function saveUiState(){
    var state = {
        categories: getSelectedValues('markup-categories'),
        percent: document.getElementById('markup-percent').value || '10',
        previewPercent: document.getElementById('preview-percent').value || '10',
        previewBaseMode: document.getElementById('preview-base-mode').value || 'wholesale',
        supplier: document.getElementById('supplier-select').value || '',
        targetCategory: document.getElementById('preview-target-category').value || '',
        fullTargetCategory: document.getElementById('full-list-target-category').value || ''
    };
    localStorage.setItem(UI_STATE_KEY, JSON.stringify(state));
}

function loadUiState(){
    try{
        return JSON.parse(localStorage.getItem(UI_STATE_KEY) || '{}');
    }catch(e){
        return {};
    }
}

function applySelection(selectId, values){
    var valSet = new Set(values || []);
    var sel = document.getElementById(selectId);
    Array.from(sel.options).forEach(function(o){ o.selected = valSet.has(o.value); });
}

function initMarkupUI(){
    var state = loadUiState();
    if(state.percent){ document.getElementById('markup-percent').value = state.percent; }
    if(state.previewPercent){ document.getElementById('preview-percent').value = state.previewPercent; }
    if(state.previewBaseMode){ document.getElementById('preview-base-mode').value = state.previewBaseMode; }
    loadCategoryMarkups();
    loadCategories(state.categories || []);
    loadSuppliers();
    document.getElementById('open-pricing-btn').addEventListener('click', function(){
        document.getElementById('pricing-modal').classList.add('active');
    });
    document.getElementById('close-pricing-btn').addEventListener('click', function(){
        document.getElementById('pricing-modal').classList.remove('active');
    });
    document.getElementById('pricing-modal').addEventListener('click', function(e){
        if(e.target.id === 'pricing-modal'){ this.classList.remove('active'); }
    });
    document.getElementById('select-all-cats').addEventListener('click', function(){
        var sel = document.getElementById('markup-categories');
        for(var i=0;i<sel.options.length;i++) sel.options[i].selected = true;
        saveUiState();
        requestPreview();
    });
    document.getElementById('clear-all-cats').addEventListener('click', function(){
        var sel = document.getElementById('markup-categories');
        for(var i=0;i<sel.options.length;i++) sel.options[i].selected = false;
        saveUiState();
        requestPreview();
    });
    document.getElementById('apply-markup-btn').addEventListener('click', applyMarkup);
    document.getElementById('supplier-select').addEventListener('change', loadSupplierCategories);
    document.getElementById('hide-cats-btn').addEventListener('click', function(){ setCategoryVisibility(true); });
    document.getElementById('show-cats-btn').addEventListener('click', function(){ setCategoryVisibility(false); });
    document.getElementById('markup-categories').addEventListener('change', function(){ applyStoredPercentForSelection(); syncPreviewModalCategorySelector(); saveUiState(); requestPreview(); });
    document.getElementById('markup-percent').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('preview-move-btn').addEventListener('click', moveSelectedItemsToCategory);
    document.getElementById('preview-target-category').addEventListener('change', saveUiState);
    document.getElementById('target-category-search').addEventListener('input', function(){ filterTargetCategories('preview-target-category', this.value); });
    document.getElementById('open-full-list-btn').addEventListener('click', openFullListModal);
    document.getElementById('close-full-list-btn').addEventListener('click', closeFullListModal);
    document.getElementById('full-list-modal').addEventListener('click', function(e){
        if(e.target.id === 'full-list-modal'){ closeFullListModal(); }
    });
    document.getElementById('full-list-target-category').addEventListener('change', saveUiState);
    document.getElementById('full-target-category-search').addEventListener('input', function(){ filterTargetCategories('full-list-target-category', this.value); });
    document.getElementById('full-list-move-btn').addEventListener('click', moveSelectedItemsToCategoryFromFullList);
    document.getElementById('open-preview-modal-btn').addEventListener('click', openPreviewModal);
    document.getElementById('close-preview-btn').addEventListener('click', closePreviewModal);
    document.getElementById('preview-modal').addEventListener('click', function(e){
        if(e.target.id === 'preview-modal'){ closePreviewModal(); }
    });
    document.getElementById('preview-percent').addEventListener('input', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-base-mode').addEventListener('change', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-apply-btn').addEventListener('click', function(){
        document.getElementById('markup-percent').value = document.getElementById('preview-percent').value || '0';
        applyMarkup();
    });
    document.getElementById('refresh-market-btn').addEventListener('click', startMarketRefresh);
    document.getElementById('preview-modal-categories').addEventListener('change', function(){
        var selected = getSelectedValues('preview-modal-categories');
        applySelection('markup-categories', selected);
        applyStoredPercentForPreviewSelection();
        saveUiState();
        loadPreviewModalItems();
    });
    loadTargetCategoryCatalog();
}

function loadCategoryMarkups(){
    fetch('/api/category-markups').then(function(r){ return r.json(); }).then(function(d){
        categoryMarkups = d.markups || {};
        renderCategoryMarkupTable();
        applyStoredPercentForSelection();
        applyStoredPercentForPreviewSelection();
    }).catch(function(){});
}

function renderCategoryMarkupTable(){
    var tbody = document.querySelector('#category-markup-table tbody');
    if(!tbody){ return; }
    var names = Object.keys(categoryMarkups || {}).sort(compareCategoriesByUiOrder);
    tbody.innerHTML = '';
    if(!names.length){
        var trEmpty = document.createElement('tr');
        trEmpty.innerHTML = '<td colspan="2" style="color:#6b7280;">Наценки по категориям пока не заданы.</td>';
        tbody.appendChild(trEmpty);
        return;
    }
    names.forEach(function(name){
        var tr = document.createElement('tr');
        var val = Number(categoryMarkups[name]);
        tr.innerHTML = '<td>' + name + '</td><td>' + (isNaN(val) ? '' : val.toFixed(2)) + '</td>';
        tbody.appendChild(tr);
    });
}

function compareCategoriesByUiOrder(a, b){
    var idxA = getCategoryOrderIndex(a);
    var idxB = getCategoryOrderIndex(b);
    if(idxA !== idxB){ return idxA - idxB; }
    return String(a).localeCompare(String(b), 'ru');
}

function getCategoryOrderIndex(name){
    var sel = document.getElementById('markup-categories');
    if(sel && sel.options && sel.options.length){
        for(var i=0;i<sel.options.length;i++){
            if(sel.options[i].value === name){ return i; }
        }
        return 10000;
    }
    var p = CATEGORY_PRIORITY_JS.indexOf(name);
    if(p >= 0){ return p; }
    return 10000;
}

function applyStoredPercentForSelection(){
    var selected = getSelectedValues('markup-categories');
    if(!selected.length){ return; }
    var vals = selected.map(function(c){ return categoryMarkups[c]; }).filter(function(v){ return v !== undefined; });
    if(!vals.length){ return; }
    var allSame = vals.every(function(v){ return Number(v) === Number(vals[0]); });
    if(allSame){
        var value = Number(vals[0]);
        document.getElementById('markup-percent').value = value;
        document.getElementById('preview-percent').value = value;
    }
}

function applyStoredPercentForPreviewSelection(){
    var selected = getSelectedValues('preview-modal-categories');
    if(!selected.length){ selected = getSelectedValues('markup-categories'); }
    if(!selected.length){ return; }
    var vals = selected.map(function(c){ return categoryMarkups[c]; }).filter(function(v){ return v !== undefined; });
    if(!vals.length){ return; }
    var allSame = vals.every(function(v){ return Number(v) === Number(vals[0]); });
    if(allSame){
        document.getElementById('preview-percent').value = Number(vals[0]);
    }
}

function loadCategories(preselected){
    fetch('/api/categories').then(function(r){ return r.json(); }).then(function(d){
        var sel = document.getElementById('markup-categories');
        sel.innerHTML = '';
        var categories = d.categories || [];
        categories.forEach(function(c){
            var o = document.createElement('option');
            o.value = c.name;
            o.textContent = c.name + ' (' + c.count + ')';
            sel.appendChild(o);
        });
        renderCategoryMarkupTable();
        if(preselected && preselected.length){ applySelection('markup-categories', preselected); }
        else { applySelection('markup-categories', (loadUiState().categories || [])); }
        syncPreviewModalCategorySelector();
        applyStoredPercentForSelection();
        document.getElementById('markup-note').textContent = categories.length
            ? 'Выберите категории и процент. РРЦ будет пересчитан от колонки "Лучшая цена".'
            : 'Категории не найдены.';
        requestPreview();
    }).catch(function(){
        document.getElementById('markup-note').textContent = 'Не удалось загрузить категории.';
    });
}

function syncPreviewModalCategorySelector(){
    var src = document.getElementById('markup-categories');
    var dst = document.getElementById('preview-modal-categories');
    if(!src || !dst){ return; }
    dst.innerHTML = '';
    Array.from(src.options).forEach(function(o){
        var opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.textContent;
        opt.selected = !!o.selected;
        dst.appendChild(opt);
    });
}

function requestPreview(){
    if(previewTimer){ clearTimeout(previewTimer); }
    previewTimer = setTimeout(function(){
        loadPreviewItems();
        if(document.getElementById('preview-modal').classList.contains('active')){
            loadPreviewModalItems();
        }
    }, 220);
}

function loadPreviewItems(){
    var categories = getSelectedValues('markup-categories');
    var sel = document.getElementById('preview-items');
    var note = document.getElementById('preview-items-note');
    sel.innerHTML = '';
    if(!categories.length){
        note.textContent = 'Выберите категории выше, чтобы увидеть товары этих категорий.';
        return;
    }
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, limit: 10000})
    }).then(function(r){ return r.json(); }).then(function(d){
        var items = d.items || [];
        items.forEach(function(it){
            var o = document.createElement('option');
            o.value = it.key;
            o.textContent = '[' + it.category + '] ' + it.name + ' (' + it.supplier + ')';
            sel.appendChild(o);
        });
        note.textContent = 'Найдено товаров: ' + items.length + '. Можно выделять несколько (Shift/Ctrl) и переносить в новую категорию.';
    }).catch(function(){
        note.textContent = 'Не удалось загрузить товары выбранных категорий.';
    });
}

function applyMarkup(){
    var btn = document.getElementById('apply-markup-btn');
    var percent = parseFloat(document.getElementById('markup-percent').value);
    if(isNaN(percent) || percent < 0){
        document.getElementById('markup-note').textContent = 'Укажите корректный процент наценки (>= 0).';
        return;
    }
    var selected = getSelectedValues('markup-categories');
    if(!selected.length){
        document.getElementById('markup-note').textContent = 'Выберите хотя бы одну категорию.';
        return;
    }
    saveUiState();
    var baseMode = document.getElementById('preview-base-mode').value || 'wholesale';
    btn.disabled = true;
    btn.textContent = 'Применение...';
    btn.classList.add('pulse');
    fetch('/api/apply-markup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: selected, percent: percent, base_mode: baseMode})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'ok'){
            document.getElementById('markup-note').textContent =
                'Готово. Обновлено: ' + d.updated + ' из ' + (d.eligible || 0) +
                ' подходящих (всего в прайсе: ' + (d.total || 0) + '). База: ' + (d.base_mode || 'wholesale') + '.';
            selected.forEach(function(c){ categoryMarkups[c] = d.percent; });
            document.getElementById('preview-percent').value = d.percent;
            renderCategoryMarkupTable();
            if(tblMain){ tblMain.ajax.reload(null, false); }
            loadCategories(selected);
            if(document.getElementById('preview-modal').classList.contains('active')){
                loadPreviewModalItems();
            }
        } else {
            document.getElementById('markup-note').textContent = d.message || 'Ошибка применения наценки.';
        }
    }).catch(function(){
        document.getElementById('markup-note').textContent = 'Ошибка связи с сервером.';
    }).finally(function(){
        btn.disabled = false;
        btn.classList.remove('pulse');
        btn.textContent = 'Применить Наценку';
        requestPreview();
    });
}

function loadSuppliers(){
    fetch('/api/suppliers').then(function(r){ return r.json(); }).then(function(d){
        var sel = document.getElementById('supplier-select');
        sel.innerHTML = '';
        var state = loadUiState();
        (d.suppliers || []).forEach(function(s){
            var o = document.createElement('option');
            o.value = s;
            o.textContent = s;
            sel.appendChild(o);
        });
        if(sel.options.length){
            var chosen = state.supplier || sel.options[0].value;
            for(var i=0;i<sel.options.length;i++){
                sel.options[i].selected = (sel.options[i].value === chosen);
            }
            loadSupplierCategories();
        } else {
            document.getElementById('visibility-note').textContent = 'Поставщики не найдены.';
        }
    }).catch(function(){
        document.getElementById('visibility-note').textContent = 'Не удалось загрузить поставщиков.';
    });
}

function loadSupplierCategories(){
    var selSup = document.getElementById('supplier-select');
    if(!selSup.value){ return; }
    saveUiState();
    fetch('/api/supplier-categories?supplier=' + encodeURIComponent(selSup.value))
    .then(function(r){ return r.json(); })
    .then(function(d){
        var sel = document.getElementById('supplier-categories');
        sel.innerHTML = '';
        (d.categories || []).forEach(function(c){
            var o = document.createElement('option');
            o.value = c.name;
            o.textContent = (c.hidden ? '[скрыто] ' : '') + c.name + ' (' + c.count + ')';
            sel.appendChild(o);
        });
        document.getElementById('visibility-note').textContent = 'Скрытые категории помечены префиксом [скрыто].';
    }).catch(function(){
        document.getElementById('visibility-note').textContent = 'Не удалось загрузить категории поставщика.';
    });
}

function setCategoryVisibility(hidden){
    var sup = document.getElementById('supplier-select').value;
    if(!sup){
        document.getElementById('visibility-note').textContent = 'Выберите поставщика.';
        return;
    }
    var sel = document.getElementById('supplier-categories');
    var categories = Array.from(sel.options).filter(function(o){ return o.selected; }).map(function(o){ return o.value; });
    if(!categories.length){
        document.getElementById('visibility-note').textContent = 'Выберите хотя бы одну категорию.';
        return;
    }
    fetch('/api/category-visibility', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({supplier: sup, categories: categories, hidden: hidden})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'ok'){
            document.getElementById('visibility-note').textContent = hidden ? 'Категории скрыты.' : 'Категории показаны.';
            loadSupplierCategories();
            loadCategories(getSelectedValues('markup-categories'));
            if(tblMain){ tblMain.ajax.reload(null, false); }
            requestPreview();
        } else {
            document.getElementById('visibility-note').textContent = d.message || 'Ошибка изменения видимости.';
        }
    }).catch(function(){
        document.getElementById('visibility-note').textContent = 'Ошибка связи с сервером.';
    });
}

function loadTargetCategoryCatalog(){
    fetch('/api/category-catalog').then(function(r){ return r.json(); }).then(function(d){
        var state = loadUiState();
        categoryCatalog = (d.categories || []).map(function(c){ return (typeof c === 'string') ? c : c.name; });
        fillTargetCategorySelect('preview-target-category', categoryCatalog, state.targetCategory || '');
        fillTargetCategorySelect('full-list-target-category', categoryCatalog, state.fullTargetCategory || '');
        saveUiState();
    });
}

function fillTargetCategorySelect(selectId, categories, selected){
    var sel = document.getElementById(selectId);
    if(!sel){ return; }
    sel.innerHTML = '';
    categories.forEach(function(c){
        var o = document.createElement('option');
        var val = (typeof c === 'string') ? c : c.name;
        o.value = val;
        o.textContent = val;
        if(val === selected){ o.selected = true; }
        sel.appendChild(o);
    });
    if(!sel.value && sel.options.length){ sel.options[0].selected = true; }
}

function filterTargetCategories(selectId, query){
    var selected = document.getElementById(selectId).value || '';
    var q = String(query || '').trim().toLowerCase();
    var filtered = categoryCatalog.filter(function(name){
        return !q || name.toLowerCase().indexOf(q) >= 0;
    });
    fillTargetCategorySelect(selectId, filtered, selected);
}

function moveSelectedItemsToCategory(){
    var items = getSelectedValues('preview-items');
    var target = document.getElementById('preview-target-category').value;
    if(!items.length){
        document.getElementById('preview-items-note').textContent = 'Выберите хотя бы один товар в списке.';
        return;
    }
    if(!target){
        document.getElementById('preview-items-note').textContent = 'Выберите целевую категорию.';
        return;
    }
    fetch('/api/category-override-bulk', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({item_keys: items, target_category: target})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'ok'){
            document.getElementById('preview-items-note').textContent = 'Перенесено товаров: ' + d.updated + '. Изменение сохранено постоянно.';
            loadCategories(getSelectedValues('markup-categories'));
            loadSupplierCategories();
            loadTargetCategoryCatalog();
            loadFullListItems();
            requestPreview();
            if(tblMain){ tblMain.ajax.reload(null, false); }
        } else {
            document.getElementById('preview-items-note').textContent = d.message || 'Не удалось перенести категории.';
        }
    }).catch(function(){
        document.getElementById('preview-items-note').textContent = 'Ошибка связи с сервером.';
    });
}

function openFullListModal(){
    document.getElementById('full-list-modal').classList.add('active');
    loadFullListItems();
}

function closeFullListModal(){
    document.getElementById('full-list-modal').classList.remove('active');
}

function loadFullListItems(){
    var categories = getSelectedValues('markup-categories');
    var note = document.getElementById('full-list-note');
    var listSel = document.getElementById('full-list-items');
    var tbody = document.querySelector('#full-list-table tbody');
    listSel.innerHTML = '';
    tbody.innerHTML = '';
    if(!categories.length){
        note.textContent = 'Выберите категории в блоке наценки, затем нажмите "Смотреть Все".';
        return;
    }
    note.textContent = 'Загрузка полного списка...';
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, limit: 10000})
    }).then(function(r){ return r.json(); }).then(function(d){
        var items = d.items || [];
        items.forEach(function(it){
            var o = document.createElement('option');
            o.value = it.key;
            o.textContent = '[' + it.category + '] ' + it.name + ' (' + it.supplier + ')';
            listSel.appendChild(o);
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + it.category + '</td>'
                + '<td>' + it.name + '</td>'
                + '<td>' + it.supplier + '</td>'
                + '<td>' + (it.price || '') + '</td>'
                + '<td>' + (it.rrc || '') + '</td>';
            tbody.appendChild(tr);
        });
        note.textContent = 'Найдено товаров: ' + items.length + '. Можно выделить позиции и перенести в другую категорию.';
    }).catch(function(){
        note.textContent = 'Не удалось загрузить полный список товаров.';
    });
}

function roundPriceTo90(value){
    var v = Number(value);
    if(!isFinite(v)){ return ''; }
    if(v <= 0){ return 0.90; }
    var base = Math.floor(v) + 0.9;
    if(v > base){ base += 1.0; }
    return Math.round(base * 100) / 100;
}

function openPreviewModal(){
    var categories = getSelectedValues('markup-categories');
    if(!categories.length){
        document.getElementById('markup-note').textContent = 'Сначала выберите хотя бы одну категорию.';
        return;
    }
    document.getElementById('preview-percent').value = document.getElementById('markup-percent').value || '0';
    syncPreviewModalCategorySelector();
    applyStoredPercentForPreviewSelection();
    document.getElementById('preview-modal').classList.add('active');
    loadPreviewModalItems();
}

function closePreviewModal(){
    document.getElementById('preview-modal').classList.remove('active');
    if(marketRefreshPollTimer){ clearTimeout(marketRefreshPollTimer); marketRefreshPollTimer = null; }
    var btn = document.getElementById('refresh-market-btn');
    if(btn){ btn.disabled = false; btn.textContent = 'Обновить Цены Onliner'; }
}

function loadPreviewModalItems(options){
    options = options || {};
    var marketOnly = !!options.marketOnly;
    var categories = getSelectedValues('preview-modal-categories');
    if(!categories.length){ categories = getSelectedValues('markup-categories'); }
    var note = document.getElementById('preview-modal-note');
    var requestSeq = ++previewModalRequestSeq;
    var stage2Applied = false;
    var previousMarketMap = buildPreviewMarketMap(previewModalItems);
    previewModalItems = [];
    renderPreviewModalRows();
    if(!categories.length){
        note.textContent = 'Выберите хотя бы одну категорию в основном блоке.';
        return;
    }
    note.textContent = marketOnly ? 'Обновляю цены Onliner...' : 'Переключаю категории...';
    var catsPreview = categories.slice(0, 4).join(', ') + (categories.length > 4 ? '...' : '');

    // Stage 1: fast category refresh (without market prices) to avoid stale view.
    // Skip this stage when we need immediate post-refresh render from cache.
    if(!marketOnly){
        fetch('/api/category-preview-items', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({categories: categories, limit: 10000, with_market: false})
        }).then(function(r){ return r.json(); }).then(function(d){
            if(requestSeq !== previewModalRequestSeq){ return; }
            // Do not overwrite rows if stage 2 (with market data) already rendered.
            if(stage2Applied){ return; }
            previewModalItems = d.items || [];
            renderPreviewModalRows();
            note.textContent = 'Категории: ' + catsPreview + '. Показано товаров: ' + previewModalItems.length + '. Загружаю цены Onliner...';
        }).catch(function(){
            if(requestSeq !== previewModalRequestSeq){ return; }
            if(stage2Applied){ return; }
            note.textContent = 'Не удалось быстро обновить список категории.';
        });
    }

    // Stage 2: enrich with Onliner min/avg/max.
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, limit: 10000, with_market: true, allow_stale_market: true, max_market_checks: 400})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(requestSeq !== previewModalRequestSeq){ return; }
        stage2Applied = true;
        previewModalItems = applyPreviewMarketTrend((d.items || []), previousMarketMap);
        renderPreviewModalRows();
        note.textContent = 'Категории: ' + catsPreview + '. Показано товаров: ' + previewModalItems.length
            + '. Onliner проверено: ' + (d.market_checked || 0)
            + ', без данных по ID: ' + (d.missing_market_ids || 0)
            + ', без OnlinerID: ' + (d.no_onliner_id || 0)
            + '. Цены Onliner показаны если есть хотя бы 1 конкурент.';
    }).catch(function(){
        if(requestSeq !== previewModalRequestSeq){ return; }
        note.textContent = 'Не удалось загрузить данные для предпросмотра.';
        renderPreviewModalRows();
    });
}

function buildPreviewMarketMap(items){
    var map = {};
    (items || []).forEach(function(it){
        var key = String((it && (it.row_idx || it.row_idx === 0)) ? it.row_idx : (it.onliner_id || '')) + '|' + String((it && it.name) || '');
        if(!key){ return; }
        map[key] = {
            min: Number(it.market_min),
            avg: Number(it.market_avg),
            max: Number(it.market_max),
        };
    });
    return map;
}

function trendByValues(prev, current){
    var p = Number(prev);
    var c = Number(current);
    if(!isFinite(p) || !isFinite(c)){ return ''; }
    if(Math.abs(c - p) < 0.0001){ return 'flat'; }
    return c > p ? 'up' : 'down';
}

function applyPreviewMarketTrend(items, previousMap){
    previousMap = previousMap || {};
    return (items || []).map(function(it){
        var rowIdx = (it && (it.row_idx || it.row_idx === 0)) ? it.row_idx : '';
        var key = String(rowIdx) + '|' + String((it && it.name) || '');
        var prev = previousMap[key] || null;
        var out = Object.assign({}, it || {});
        out.market_trend_min = prev ? trendByValues(prev.min, out.market_min) : '';
        out.market_trend_avg = prev ? trendByValues(prev.avg, out.market_avg) : '';
        out.market_trend_max = prev ? trendByValues(prev.max, out.market_max) : '';
        return out;
    });
}

function formatMarketTrend(trend){
    if(trend === 'up'){ return '<span class="market-trend market-trend-up">↑</span>'; }
    if(trend === 'down'){ return '<span class="market-trend market-trend-down">↓</span>'; }
    if(trend === 'flat'){ return '<span class="market-trend market-trend-flat">→</span>'; }
    return '';
}

function formatMarketCell(value, trend, competitors){
    var txt = (value || value === 0) ? String(value) : '';
    if(txt === ''){ return ''; }
    var cnt = Number(competitors || 0);
    if(cnt > 0){ txt += ' (' + cnt + ')'; }
    return txt + formatMarketTrend(trend);
}

function startMarketRefresh(){
    var categories = getSelectedValues('preview-modal-categories');
    if(!categories.length){ categories = getSelectedValues('markup-categories'); }
    var note = document.getElementById('market-refresh-note');
    var btn = document.getElementById('refresh-market-btn');
    if(!categories.length){
        note.textContent = 'Сначала выберите категории для обновления цен.';
        return;
    }
    btn.disabled = true;
    btn.textContent = 'Обновление...';
    fetch('/api/market-refresh-start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'started' || d.status === 'already_running'){
            pollMarketRefreshStatus();
        } else {
            note.textContent = d.message || 'Не удалось запустить обновление цен.';
            btn.disabled = false;
            btn.textContent = 'Обновить Цены Onliner';
        }
    }).catch(function(){
        note.textContent = 'Ошибка запуска обновления цен.';
        btn.disabled = false;
        btn.textContent = 'Обновить Цены Onliner';
    });
}

function pollMarketRefreshStatus(){
    if(marketRefreshPollTimer){ clearTimeout(marketRefreshPollTimer); }
    var note = document.getElementById('market-refresh-note');
    var btn = document.getElementById('refresh-market-btn');
    fetch('/api/market-refresh-status').then(function(r){ return r.json(); }).then(function(d){
        var cats = d.categories || {};
        var lines = Object.keys(cats).sort(compareCategoriesByUiOrder).slice(0, 6).map(function(name){
            var s = cats[name];
            return name + ': ' + (s.percent || 0) + '% (' + (s.done || 0) + '/' + (s.total || 0) + ')';
        });
        note.textContent = 'Обновление кэша Onliner: ' + (d.overall_percent || 0) + '% (' + (d.done || 0) + '/' + (d.total || 0) + '). '
            + (lines.length ? 'Категории: ' + lines.join(' | ') : '');
        if(d.running){
            marketRefreshPollTimer = setTimeout(pollMarketRefreshStatus, 1200);
            return;
        }
        btn.disabled = false;
        btn.textContent = 'Обновить Цены Onliner';
        note.textContent = 'Кэш Onliner обновлен: ' + (d.done || 0) + ' товаров. Обновляю предпросмотр...';
        loadPreviewModalItems({marketOnly:true});
    }).catch(function(){
        btn.disabled = false;
        btn.textContent = 'Обновить Цены Onliner';
        note.textContent = 'Ошибка чтения прогресса обновления.';
    });
}

function renderPreviewModalRows(){
    var tbody = document.querySelector('#preview-full-table tbody');
    var percent = Number(document.getElementById('preview-percent').value);
    var baseMode = document.getElementById('preview-base-mode').value || 'wholesale';
    if(!isFinite(percent) || percent < 0){ percent = 0; }
    tbody.innerHTML = '';
    previewModalItems.forEach(function(it){
        var wholesale = Number(it.price);
        var marketMin = Number(it.market_min);
        var marketAvg = Number(it.market_avg);
        var marketMax = Number(it.market_max);
        var hasMarketMin = isFinite(marketMin);
        var hasMarketAvg = isFinite(marketAvg);
        var hasMarketMax = isFinite(marketMax);
        var hasWholesale = isFinite(wholesale);
        var basePrice = hasWholesale ? wholesale : NaN;
        if(baseMode === 'onliner_min' && hasMarketMin){ basePrice = marketMin; }
        if(baseMode === 'onliner_avg' && hasMarketAvg){ basePrice = marketAvg; }
        var newRrc = '';
        if(isFinite(basePrice)){
            newRrc = roundPriceTo90(basePrice * (1 + percent / 100));
        }
        var marginPct = '';
        if(isFinite(newRrc) && hasWholesale && wholesale > 0){
            marginPct = ((newRrc - wholesale) / wholesale) * 100;
        }
        var avgCompetitors = Number(it.avg_competitors || 0);
        var minCompetitors = Number(it.min_competitors || 0);
        var rrcColor = '#1d4ed8';
        if(isFinite(newRrc) && hasMarketAvg){
            if(newRrc > marketAvg * 1.15){
                rrcColor = '#dc2626'; // high vs market average
            } else if(avgCompetitors > minCompetitors){
                rrcColor = '#15803d'; // market mostly sits near average
            } else {
                rrcColor = '#ca8a04'; // cautious / close to min zone
            }
        }
        var tr = document.createElement('tr');
        var minTxt = formatMarketCell(it.market_min, it.market_trend_min, it.min_competitors);
        var avgTxt = formatMarketCell(it.market_avg, it.market_trend_avg, it.avg_competitors);
        var maxTxt = formatMarketCell(it.market_max, it.market_trend_max, it.market_offers);
        tr.innerHTML = '<td>' + (it.onliner_id || '') + '</td>'
            + '<td>' + it.category + '</td>'
            + '<td>' + it.name + '</td>'
            + '<td>' + it.supplier + '</td>'
            + '<td>' + (it.price || '') + '</td>'
            + '<td>' + minTxt + '</td>'
            + '<td>' + avgTxt + '</td>'
            + '<td>' + maxTxt + '</td>'
            + '<td>' + (it.rrc || '') + '</td>'
            + '<td><b style="color:' + rrcColor + '">' + (newRrc === '' ? '' : Number(newRrc).toFixed(2)) + '</b></td>'
            + '<td>' + (marginPct === '' ? '' : Number(marginPct).toFixed(2)) + '</td>';
        tbody.appendChild(tr);
    });
}

function moveSelectedItemsToCategoryFromFullList(){
    var items = getSelectedValues('full-list-items');
    var target = document.getElementById('full-list-target-category').value;
    var note = document.getElementById('full-list-note');
    if(!items.length){
        note.textContent = 'Выберите хотя бы один товар в списке.';
        return;
    }
    if(!target){
        note.textContent = 'Выберите целевую категорию.';
        return;
    }
    fetch('/api/category-override-bulk', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({item_keys: items, target_category: target})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'ok'){
            note.textContent = 'Перенесено товаров: ' + d.updated + '. Изменение сохранено.';
            loadCategories(getSelectedValues('markup-categories'));
            loadSupplierCategories();
            loadTargetCategoryCatalog();
            loadPreviewItems();
            loadFullListItems();
            if(tblMain){ tblMain.ajax.reload(null, false); }
        } else {
            note.textContent = d.message || 'Не удалось перенести выбранные товары.';
        }
    }).catch(function(){
        note.textContent = 'Ошибка связи с сервером.';
    });
}

function findIds(){
    var btn = document.getElementById('find-btn');
    btn.disabled = true;
    btn.textContent = 'Поиск...';
    openProgressModal();
    fetch('/api/find-ids-start', {method:'POST'}).then(function(r){return r.json();}).then(function(d){
        if(d.status==='started' || d.status==='already_running'){
            pollFindIds();
        } else if(d.status==='done'){
            btn.textContent = 'Все найдены!';
            btn.style.background = '#2e7d32';
            document.getElementById('progress-subtitle').textContent = d.message || 'Все товары уже имеют OnlinerID';
            completeProgressUI();
        } else if(d.status==='error'){
            document.getElementById('progress-subtitle').textContent = d.message || 'Ошибка запуска поиска';
            completeProgressUI();
            btn.disabled = false;
            btn.textContent = 'Найти ID';
        }
    }).catch(function(){
        document.getElementById('progress-subtitle').textContent = 'Ошибка связи с сервером';
        completeProgressUI();
        btn.disabled = false;
        btn.textContent = 'Найти ID';
    });
}

function openProgressModal(){
    document.getElementById('find-progress-modal').classList.add('active');
    document.getElementById('progress-close').style.display = 'none';
    document.getElementById('progress-spinner').classList.remove('done');
}

function closeProgressModal(){
    document.getElementById('find-progress-modal').classList.remove('active');
}

function setPhaseState(id, state){
    var pill = document.getElementById(id);
    pill.classList.remove('active', 'done');
    if(state === 'active'){
        pill.classList.add('active');
        pill.textContent = 'В работе';
    } else if(state === 'done'){
        pill.classList.add('done');
        pill.textContent = 'Готово';
    } else {
        pill.textContent = 'Ожидание';
    }
}

function completeProgressUI(){
    var spinner = document.getElementById('progress-spinner');
    spinner.classList.add('done');
    document.getElementById('progress-close').style.display = 'inline-block';
}

function updateProgressUI(d){
    var total = d.total || 0;
    var sheetChecked = d.sheet_checked || 0;
    var sheetTotal = d.sheet_total || total;
    var sheetFound = d.sheet_found || 0;
    var apiChecked = d.api_checked || 0;
    var apiTotal = d.api_total || 0;
    var apiFound = d.api_found || 0;
    var notFound = d.not_found || 0;
    var found = d.found || 0;
    var phase = d.phase || 'sheet';

    document.getElementById('sheet-meta').textContent = sheetChecked + ' / ' + sheetTotal + ' проверено, найдено: ' + sheetFound;
    document.getElementById('api-meta').textContent = apiChecked + ' / ' + apiTotal + ' проверено, найдено: ' + apiFound;
    document.getElementById('stat-found').textContent = found;
    document.getElementById('stat-not-found').textContent = notFound;
    document.getElementById('stat-total').textContent = total;

    var checked = Math.min((sheetFound + apiChecked), total || 1);
    var pct = total > 0 ? Math.round((checked / total) * 100) : 100;
    document.getElementById('progress-fill').style.width = pct + '%';

    if(phase === 'sheet'){
        setPhaseState('sheet-pill', 'active');
        setPhaseState('api-pill', 'pending');
        document.getElementById('progress-subtitle').textContent = 'Ищем совпадения в Google Sheets…';
    } else if(phase === 'api'){
        setPhaseState('sheet-pill', 'done');
        setPhaseState('api-pill', 'active');
        document.getElementById('progress-subtitle').textContent = 'Этап API отключен';
    } else {
        setPhaseState('sheet-pill', 'done');
        setPhaseState('api-pill', 'done');
        document.getElementById('progress-subtitle').textContent = 'Поиск завершен';
    }
}

function pollFindIds(){
    var btn = document.getElementById('find-btn');
    fetch('/api/find-ids-status').then(function(r){return r.json();}).then(function(d){
        updateProgressUI(d);
        btn.textContent = d.checked + '/' + d.total + ' (найдено: ' + d.found + ')';
        if(d.running){
            setTimeout(pollFindIds, 1500);
        } else {
            btn.textContent = 'Готово! Найдено: ' + d.found;
            btn.style.background = '#2e7d32';
            btn.disabled = false;
            btn.onclick = function(){ location.reload(); };
            completeProgressUI();
        }
    }).catch(function(){
        document.getElementById('progress-subtitle').textContent = 'Ошибка чтения статуса';
        completeProgressUI();
        btn.disabled = false;
        btn.textContent = 'Найти ID';
    });
}
</script>
</body></html>"""
)


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    error = request.args.get("error")
    return render_template_string(UPLOAD_PAGE, error=error)


def get_article_from_name(name):
    """Извлечь артикул из названия."""
    if not name:
        return ""
    article = extract_article(name)
    if article:
        return article
    return name[:100]  # Fallback на название


CATEGORY_PRIORITY = [
    "Процессор",
    "Кулер",
    "Охлаждение",
    "Материнская плата",
    "Оперативная память",
    "SSD",
    "Жесткий диск",
    "Видеокарта",
    "Блок питания",
    "Корпус",
    "Монитор",
]

CATEGORY_OVERRIDE_FILE = Path(__file__).parent / "category_overrides.json"
CATEGORY_MARKUPS_FILE = Path(__file__).parent / "category_markups.json"
CATEGORY_VISIBILITY_FILE = Path(__file__).parent / "category_visibility.json"
ONLINER_MARKET_CACHE_FILE = Path(__file__).parent / "onliner_market_cache.json"
ONLINER_PRODUCT_CACHE_FILE = Path(__file__).parent / "onliner_product_cache.json"
MANUAL_ID_BINDINGS_FILE = Path(__file__).parent / "manual_id_bindings.json"
ONLINER_MARKET_CACHE_TTL = 24 * 3600
ONLINER_PRODUCT_CACHE_TTL = 7 * 24 * 3600
ID_REPLACE_QUERY_CACHE_TTL = 3600
ID_REPLACE_QUERY_CACHE = {}
ID_REPLACE_QUERY_CACHE_LOCK = threading.RLock()


def _category_sort_key(category_name):
    if category_name in CATEGORY_PRIORITY:
        return (0, CATEGORY_PRIORITY.index(category_name), category_name)
    return (1, 999, category_name.lower())


def load_category_overrides():
    if not CATEGORY_OVERRIDE_FILE.exists():
        return {}
    try:
        with open(CATEGORY_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Legacy cleanup: keys by article caused cross-category contamination.
            cleaned = {k: v for k, v in data.items() if not str(k).startswith("art:")}
            # Defensive cleanup: drop obviously conflicting saved mappings.
            # Example: keys containing "корпус"/"кулер"/"сжо" mapped to "Блок питания".
            suspicious = []
            for k, v in cleaned.items():
                kk = str(k or "").lower()
                vv = str(v or "").strip()
                if vv == "Блок питания":
                    if re.search(r"\bкорпус\b|\bcase\b|\bкулер\b|cooler|охлажден|сжо|водян|fan", kk):
                        suspicious.append(k)
            for k in suspicious:
                cleaned.pop(k, None)
            if len(cleaned) != len(data):
                try:
                    save_category_overrides(cleaned)
                except Exception:
                    pass
            return cleaned
    except Exception:
        pass
    return {}


def save_category_overrides(overrides):
    with open(CATEGORY_OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)


def load_category_markups():
    if not CATEGORY_MARKUPS_FILE.exists():
        return {}
    try:
        with open(CATEGORY_MARKUPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_category_markups(markups):
    with open(CATEGORY_MARKUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(markups, f, ensure_ascii=False, indent=2)


def load_onliner_market_cache():
    if not ONLINER_MARKET_CACHE_FILE.exists():
        return {}
    try:
        with open(ONLINER_MARKET_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_onliner_market_cache(cache):
    with open(ONLINER_MARKET_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_onliner_product_cache():
    if not ONLINER_PRODUCT_CACHE_FILE.exists():
        return {}
    try:
        with open(ONLINER_PRODUCT_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_onliner_product_cache(cache):
    with open(ONLINER_PRODUCT_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_manual_id_bindings():
    if not MANUAL_ID_BINDINGS_FILE.exists():
        return {}
    try:
        with open(MANUAL_ID_BINDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_manual_id_bindings(bindings):
    with open(MANUAL_ID_BINDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bindings, f, ensure_ascii=False, indent=2)


def _safe_float(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _extract_position_prices(payload):
    prices = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "position_price" and isinstance(v, dict):
                amount = _safe_float(v.get("amount"))
                if amount is not None and amount > 0:
                    prices.append(amount)
            else:
                prices.extend(_extract_position_prices(v))
    elif isinstance(payload, list):
        for x in payload:
            prices.extend(_extract_position_prices(x))
    return prices


def fetch_onliner_market_stats(onliner_id):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "offers": 0}

    # Step 1: find product by exact ID in catalog search.
    search_url = f"https://catalog.api.onliner.by/search/products?query={oid}"
    try:
        r = requests.get(search_url, timeout=6)
        if not r.ok:
            return {"min": None, "avg": None, "offers": 0}
        products = (r.json() or {}).get("products", [])
    except Exception:
        return {"min": None, "avg": None, "offers": 0}

    product = None
    for p in products:
        if str(p.get("id", "")).strip() == oid:
            product = p
            break
    if product is None and products:
        product = products[0]
    if not product:
        return {"min": None, "avg": None, "offers": 0}

    prices_obj = product.get("prices") or {}
    min_price = _safe_float((((prices_obj.get("price_min") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
    if min_price is None:
        min_price = _safe_float((prices_obj.get("price_min") or {}).get("amount"))
    offers_count = int(((prices_obj.get("offers") or {}).get("count") or 0))
    avg_price = None
    max_price = None
    min_competitors = 0
    avg_competitors = 0

    # Step 2: compute average from all current positions.
    positions_url = str(prices_obj.get("url", "")).strip()
    if positions_url:
        try:
            rp = requests.get(positions_url, timeout=8)
            if rp.ok:
                position_prices = _extract_position_prices(rp.json())
                if position_prices:
                    avg_price = round(float(sum(position_prices)) / len(position_prices), 2)
                    max_price = round(float(max(position_prices)), 2)
                    min_price = round(float(min(position_prices)), 2)
                    min_competitors = sum(1 for p in position_prices if p <= min_price * 1.02)
                    avg_competitors = sum(1 for p in position_prices if abs(p - avg_price) <= max(1.0, avg_price * 0.05))
                    if not offers_count:
                        offers_count = len(position_prices)
        except Exception:
            pass

    # Показываем рыночные цены уже при 1+ конкуренте.
    # Если API не отдал offers.count, но min цена есть — считаем как минимум 1 предложение.
    if offers_count <= 0 and min_price is not None:
        offers_count = 1

    if offers_count < 1:
        min_price = None
        avg_price = None
        max_price = None
        min_competitors = 0
        avg_competitors = 0
    elif min_price is not None:
        if avg_price is None:
            avg_price = min_price
        if max_price is None:
            max_price = min_price

    return {
        "min": None if min_price is None else round(float(min_price), 2),
        "avg": None if avg_price is None else round(float(avg_price), 2),
        "max": None if max_price is None else round(float(max_price), 2),
        "offers": offers_count,
        "min_competitors": int(min_competitors),
        "avg_competitors": int(avg_competitors),
    }


def get_onliner_market_stats_cached(onliner_id, cache=None):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "offers": 0}
    if cache is None:
        cache = load_onliner_market_cache()
    now = int(time.time())
    cached = cache.get(oid)
    if isinstance(cached, dict) and (now - int(cached.get("updated_at", 0)) <= ONLINER_MARKET_CACHE_TTL):
        return {
            "min": _safe_float(cached.get("min")),
            "avg": _safe_float(cached.get("avg")),
            "max": _safe_float(cached.get("max")),
            "offers": int(cached.get("offers", 0) or 0),
            "min_competitors": int(cached.get("min_competitors", 0) or 0),
            "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
        }
    stats = fetch_onliner_market_stats(oid)
    cache[oid] = {"updated_at": now, **stats}
    return stats


def get_onliner_market_stats_from_cache_only(onliner_id, cache=None, allow_stale=True):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    if cache is None:
        cache = load_onliner_market_cache()
    cached = cache.get(oid)
    if not isinstance(cached, dict):
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    if not allow_stale:
        now = int(time.time())
        if now - int(cached.get("updated_at", 0)) > ONLINER_MARKET_CACHE_TTL:
            return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    return {
        "min": _safe_float(cached.get("min")),
        "avg": _safe_float(cached.get("avg")),
        "max": _safe_float(cached.get("max")),
        "offers": int(cached.get("offers", 0) or 0),
        "min_competitors": int(cached.get("min_competitors", 0) or 0),
        "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
    }


def get_onliner_market_stats_bulk(onliner_ids, max_workers=8):
    ids = [normalize_onliner_id(x) for x in onliner_ids]
    ids = [x for x in ids if x]
    if not ids:
        return {}
    cache = load_onliner_market_cache()
    result = {}
    pending = []
    now = int(time.time())
    for oid in ids:
        cached = cache.get(oid)
        if isinstance(cached, dict) and (now - int(cached.get("updated_at", 0)) <= ONLINER_MARKET_CACHE_TTL):
            result[oid] = {
                "min": _safe_float(cached.get("min")),
                "avg": _safe_float(cached.get("avg")),
                "max": _safe_float(cached.get("max")),
                "offers": int(cached.get("offers", 0) or 0),
                "min_competitors": int(cached.get("min_competitors", 0) or 0),
                "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
            }
        else:
            pending.append(oid)
    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_oid = {ex.submit(fetch_onliner_market_stats, oid): oid for oid in pending}
            for fut in as_completed(fut_to_oid):
                oid = fut_to_oid[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = {"min": None, "avg": None, "offers": 0}
                result[oid] = stats
                cache[oid] = {"updated_at": now, **stats}
        save_onliner_market_cache(cache)
    return result


def fetch_onliner_product_info(onliner_id, cache=None, force_refresh=False, use_cache_on_error=True):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"name": "", "url": "", "source": "empty"}
    if cache is None:
        cache = load_onliner_product_cache()
    now = int(time.time())
    cached = cache.get(oid)
    if (not force_refresh) and isinstance(cached, dict) and now - int(cached.get("updated_at", 0)) <= ONLINER_PRODUCT_CACHE_TTL:
        return {
            "name": str(cached.get("name", "")).strip(),
            "url": str(cached.get("url", "")).strip(),
            "source": "cache",
        }
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    def _search_fallback():
        try:
            rs = requests.get(
                f"https://catalog.api.onliner.by/search/products?query={oid}",
                timeout=8,
                headers=headers,
            )
            if not rs.ok:
                return None
            data = rs.json() or {}
            products = data.get("products") or []
            for p in products:
                if str(p.get("id", "")).strip() == oid:
                    name = str(p.get("full_name") or p.get("name") or "").strip()
                    url = str(p.get("html_url") or "").strip()
                    return {"name": name, "url": url}
            return None
        except Exception:
            return None
    try:
        # Primary path: direct product endpoint.
        r = requests.get(
            f"https://catalog.api.onliner.by/products/{oid}",
            timeout=6,
            headers=headers,
        )
        if r.ok:
            d = r.json() or {}
            name = str(d.get("full_name") or d.get("name") or "").strip()
            url = str(d.get("html_url") or "").strip()
            cache[oid] = {"updated_at": now, "name": name, "url": url}
            return {"name": name, "url": url, "source": "api"}

        # Fallback path: search endpoint by numeric ID.
        fb = _search_fallback()
        if not fb:
            if use_cache_on_error and isinstance(cached, dict):
                return {
                    "name": str(cached.get("name", "")).strip(),
                    "url": str(cached.get("url", "")).strip(),
                    "source": "cache_fallback_http_error",
                }
            return {"name": "", "url": "", "source": "http_error"}
        name = str(fb.get("name", "")).strip()
        url = str(fb.get("url", "")).strip()
        cache[oid] = {"updated_at": now, "name": name, "url": url}
        return {"name": name, "url": url, "source": "search_fallback"}
    except Exception:
        fb = _search_fallback()
        if fb:
            name = str(fb.get("name", "")).strip()
            url = str(fb.get("url", "")).strip()
            cache[oid] = {"updated_at": now, "name": name, "url": url}
            return {"name": name, "url": url, "source": "search_fallback_after_error"}
        if use_cache_on_error and isinstance(cached, dict):
            return {
                "name": str(cached.get("name", "")).strip(),
                "url": str(cached.get("url", "")).strip(),
                "source": "cache_fallback_error",
            }
        return {"name": "", "url": "", "source": "error"}


def search_onliner_product_by_name(local_name):
    """
    Fallback-поиск товара в Onliner API по названию локального товара.
    Возвращает лучший кандидат по score.
    """
    name = str(local_name or "").strip()
    if not name:
        return {"id": "", "name": "", "url": "", "score": 0.0, "source": "empty_query"}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    candidates = []
    art = str(extract_article(name) or "").strip()
    if art:
        candidates.append(art)
    tokens = _name_tokens(name)
    if tokens:
        candidates.append(" ".join(tokens[:6]))
    candidates.append(name[:120])

    seen = set()
    queries = []
    for q in candidates:
        q = str(q).strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        queries.append(q)

    best = {"id": "", "name": "", "url": "", "score": 0.0, "source": "not_found"}
    for q in queries[:3]:
        try:
            rs = requests.get(
                f"https://catalog.api.onliner.by/search/products?query={quote(q)}",
                timeout=12,
                headers=headers,
            )
            if not rs.ok:
                continue
            data = rs.json() or {}
            products = data.get("products") or []
            for p in products[:15]:
                pid = normalize_onliner_id(p.get("id", ""))
                pname = str(p.get("full_name") or p.get("name") or "").strip()
                purl = str(p.get("html_url") or "").strip()
                if not pid or not pname:
                    continue
                cmp = calc_name_match(name, pname)
                score = float(cmp.get("score", 0.0) or 0.0)
                if cmp.get("match"):
                    score = max(score, 0.75)
                if score > float(best.get("score", 0.0)):
                    best = {"id": pid, "name": pname, "url": purl, "score": score, "source": "search_name"}
        except Exception:
            continue
        if float(best.get("score", 0.0)) >= 0.78:
            break
    return best


def _category_path_hints(category_name):
    c = str(category_name or "").strip().lower()
    if c == "процессор":
        return ["/cpu/"]
    if c == "видеокарта":
        return ["/videocard/"]
    if c == "оперативная память":
        return ["/dram/"]
    if c == "материнская плата":
        return ["/motherboard/"]
    if c == "ssd":
        return ["/ssd/"]
    if c == "жесткий диск":
        return ["/hdd/"]
    if c == "блок питания":
        return ["/powersupply/", "/psu/"]
    if c == "корпус":
        return ["/case/"]
    if c == "кулер":
        return ["/cooler/"]
    if c == "монитор":
        return ["/display/"]
    return []


def search_onliner_candidates(local_name, category_name="", query="", limit=80, max_queries=2, timeout_sec=6):
    name = str(local_name or "").strip()
    text_query = str(query or "").strip()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    hints = _category_path_hints(category_name)
    limit = max(5, min(int(limit or 80), 150))
    if not name and not text_query:
        return []

    queries = []
    if text_query:
        queries.append(text_query)
    art = str(extract_article(name) or "").strip()
    if art and art not in queries:
        queries.append(art)
    token_query = " ".join(_name_tokens(name)[:8]).strip()
    if token_query and token_query not in queries:
        queries.append(token_query)
    if name and name[:130] not in queries:
        queries.append(name[:130])
    queries = queries[:max(1, int(max_queries or 1))]

    cache_key = f"{str(category_name or '').strip().lower()}|{(text_query or token_query or name[:80]).strip().lower()}|{int(limit)}"
    now_ts = int(time.time())
    with ID_REPLACE_QUERY_CACHE_LOCK:
        cached = ID_REPLACE_QUERY_CACHE.get(cache_key)
        if isinstance(cached, dict) and now_ts - int(cached.get("ts", 0)) <= ID_REPLACE_QUERY_CACHE_TTL:
            return list(cached.get("items") or [])[:limit]

    seen_ids = set()
    candidates = []
    for q in queries:
        try:
            rs = requests.get(
                f"https://catalog.api.onliner.by/search/products?query={quote(q)}",
                timeout=max(2, int(timeout_sec or 6)),
                headers=headers,
            )
            if not rs.ok:
                continue
            data = rs.json() or {}
            products = data.get("products") or []
        except Exception:
            continue
        for p in products[:40]:
            pid = normalize_onliner_id(p.get("id", ""))
            pname = str(p.get("full_name") or p.get("name") or "").strip()
            purl = str(p.get("html_url") or "").strip()
            if not pid or not pname or pid in seen_ids:
                continue
            cmp = calc_name_match(name or text_query, pname)
            score = float(cmp.get("score", 0.0) or 0.0)
            if cmp.get("match"):
                score = max(score, 0.74)
            if hints and purl and not any(h in purl for h in hints):
                score *= 0.78
            candidates.append({
                "id": pid,
                "name": pname,
                "url": purl,
                "score": round(float(score), 3),
                "source": "api",
            })
            seen_ids.add(pid)
        if len(candidates) >= limit:
            break

    candidates.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    final_items = candidates[:limit]
    with ID_REPLACE_QUERY_CACHE_LOCK:
        ID_REPLACE_QUERY_CACHE[cache_key] = {"ts": now_ts, "items": final_items}
        if len(ID_REPLACE_QUERY_CACHE) > 400:
            keys = list(ID_REPLACE_QUERY_CACHE.keys())[:120]
            for k in keys:
                ID_REPLACE_QUERY_CACHE.pop(k, None)
    return final_items


def _name_tokens(text):
    words = re.findall(r"[a-zа-я0-9]+", str(text or "").lower())
    stop = {"для", "с", "и", "на", "по", "ret", "rtl", "oem", "box", "black", "white"}
    out = []
    for w in words:
        if len(w) < 3:
            continue
        if w in stop:
            continue
        out.append(w)
    return out


def calc_name_match(local_name, onliner_name):
    a = str(local_name or "").strip()
    b = str(onliner_name or "").strip()
    if not a or not b:
        return {"score": 0.0, "match": False, "reason": "no_name"}

    art_local = str(extract_article(a) or "").upper()
    art_onl = str(extract_article(b) or "").upper()
    if art_local and art_onl and art_local == art_onl:
        return {"score": 1.0, "match": True, "reason": "article"}

    ta = set(_name_tokens(a))
    tb = set(_name_tokens(b))
    overlap = 0.0
    if ta and tb:
        overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    seq = SequenceMatcher(None, " ".join(sorted(ta))[:300], " ".join(sorted(tb))[:300]).ratio() if ta and tb else 0.0
    score = round(0.7 * overlap + 0.3 * seq, 3)
    ok = score >= 0.52 or overlap >= 0.62
    return {"score": float(score), "match": bool(ok), "reason": "tokens"}


def normalize_onliner_id(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def reconcile_ids_from_catalog(df):
    """
    Принудительно сверить OnlinerID по All_Catalog.
    Если по названию найден однозначный ID и он отличается от текущего — исправить.
    """
    if "OnlinerID" not in df.columns:
        return 0
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    # В pandas string-dtype прямое присваивание числам/float может падать.
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    corrected = 0
    for i, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)
        if not catalog_id:
            continue
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        if current_id != str(catalog_id):
            df.at[i, "OnlinerID"] = str(catalog_id)
            if catalog_url:
                df.at[i, "Ссылка"] = catalog_url
            corrected += 1
        elif catalog_url and not str(row.get("Ссылка", "")).strip():
            df.at[i, "Ссылка"] = catalog_url
    return corrected


def enforce_catalog_consistency(df, session_dir=None):
    """
    Жесткая сверка с All_Catalog:
    - если найден однозначный CatalogID, он считается эталоном;
    - если текущий OnlinerID отличается — исправляем;
    - если есть артикул, но каталог не дал соответствие — ID очищаем (безопасный режим).
    Дополнительно пишет отчет по спорным строкам.
    """
    if "OnlinerID" not in df.columns:
        return {
            "checked": 0,
            "set_from_catalog": 0,
            "corrected_conflicts": 0,
            "cleared_unverified": 0,
            "report_rows": 0,
        }

    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")

    checked = 0
    set_from_catalog = 0
    corrected_conflicts = 0
    cleared_unverified = 0
    report_rows = []

    for i, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        checked += 1
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        article = get_article_from_name(name)
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)

        if catalog_id:
            catalog_id = str(catalog_id).strip()
            if not current_id:
                df.at[i, "OnlinerID"] = catalog_id
                set_from_catalog += 1
            elif current_id != catalog_id:
                report_rows.append({
                    "row": int(i) + 2,
                    "supplier": str(row.get("Поставщик", "")).strip(),
                    "name": name,
                    "article": article,
                    "current_id": current_id,
                    "catalog_id": catalog_id,
                    "action": "corrected_to_catalog",
                })
                df.at[i, "OnlinerID"] = catalog_id
                corrected_conflicts += 1
            if catalog_url:
                df.at[i, "Ссылка"] = str(catalog_url).strip()
            continue

        # Нет однозначного соответствия в каталоге.
        # Безопасный режим: если у товара есть артикул, но каталог не подтверждает ID —
        # снимаем ID, чтобы не отправить неверную позицию в магазин.
        if article and current_id:
            report_rows.append({
                "row": int(i) + 2,
                "supplier": str(row.get("Поставщик", "")).strip(),
                "name": name,
                "article": article,
                "current_id": current_id,
                "catalog_id": "",
                "action": "cleared_unverified_no_catalog_match",
            })
            df.at[i, "OnlinerID"] = ""
            df.at[i, "Ссылка"] = ""
            cleared_unverified += 1

    if session_dir:
        session_dir = Path(session_dir)
        try:
            report_df = pd.DataFrame(report_rows)
            report_path = session_dir / "id_quality_report.csv"
            report_df.to_csv(report_path, index=False, encoding="utf-8-sig")
            summary = {
                "checked": checked,
                "set_from_catalog": set_from_catalog,
                "corrected_conflicts": corrected_conflicts,
                "cleared_unverified": cleared_unverified,
                "report_rows": len(report_rows),
                "report_file": str(report_path),
            }
            with open(session_dir / "id_quality_report.json", "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Не удалось сохранить ID quality report: {e}")

    return {
        "checked": checked,
        "set_from_catalog": set_from_catalog,
        "corrected_conflicts": corrected_conflicts,
        "cleared_unverified": cleared_unverified,
        "report_rows": len(report_rows),
    }


def _normalize_name_key(name):
    text = str(name or "").strip().lower()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    # No truncation: avoid collisions between long similar names.
    return text


def build_item_category_keys(row):
    """Стабильные ключи для категорий: только имя (+поставщик), без oid/art."""
    keys = []
    name = str(row.get("Название", "")).strip()
    supplier = str(row.get("Поставщик", "")).strip().lower()
    name_key = _normalize_name_key(name)
    if supplier and name_key:
        keys.append(f"sname:{supplier}:{name_key}")
    if name_key:
        keys.append(f"name:{name_key}")
    # unique keep order
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_item_category_key(row):
    keys = build_item_category_keys(row)
    return keys[0] if keys else ""


def infer_category(name):
    """Определить укрупненную категорию из названия товара."""
    text = str(name or "").strip().lower()
    if not text:
        return "Без категории"

    norm = re.sub(r"[^a-zа-я0-9\+\s\-]", " ", text)
    norm = re.sub(r"\s+", " ", norm).strip()

    # Корпуса с формулировкой "без БП" не должны попадать в "Блок питания".
    has_case_words = bool(re.search(r"\bкорпус\b|\bcase\b|midi[\s\-]?tower|mini[\s\-]?tower", norm))
    no_psu_hint = bool(re.search(r"\bбез\s+бп\b|\bбез\s+блока\s+питания\b|\bno\s*psu\b|\bwithout\s+psu\b", norm))
    if has_case_words:
        return "Корпус"

    # Явный приоритет для БП, чтобы бренды типа PcCooler не уводили в "Кулер".
    if re.search(r"\bбп\b|блок питания|power supply|\bpsu\b", norm) and not no_psu_hint:
        return "Блок питания"

    category_rules = [
        ("Процессор", [r"процессор", r"\bcpu\b", r"\bintel core\b", r"\bryzen\b"]),
        ("Кулер", [r"\bкулер\b", r"cooler"]),
        ("Охлаждение", [r"термопаст", r"термопроклад", r"водян", r"сжо", r"радиатор", r"вентилятор"]),
        ("Материнская плата", [r"материн", r"\bmotherboard\b", r"\bmb\b"]),
        ("SSD", [r"\bssd\b", r"nvme", r"m\.?2", r"твердотельн"]),
        ("Жесткий диск", [r"\bhdd\b", r"жестк", r"винчестер"]),
        ("Видеокарта", [r"видеокарт", r"\bgpu\b", r"geforce", r"radeon", r"\brtx\b", r"\bgtx\b"]),
        ("Корпус", [r"\bкорпус\b", r"\bcase\b", r"midi[\s\-]?tower", r"mini[\s\-]?tower"]),
        ("Блок питания", [r"\bбп\b", r"блок питания", r"power supply", r"\bpsu\b"]),
        ("Монитор", [r"монитор", r"display"]),
        ("Оперативная память", [r"\bddr[345]\b", r"оперативн", r"\bram\b"]),
        ("Системный блок", [r"системный блок", r"\bпэвм\b", r"\bpc\b"]),
        ("Ноутбук", [r"ноутбук", r"laptop"]),
        ("Клавиатура", [r"клавиатур"]),
        ("Мышь", [r"\bмыш", r"\bmouse\b"]),
        ("Наушники", [r"наушник", r"гарнитур"]),
        ("Акустика", [r"колонк", r"акустик", r"soundbar"]),
        ("Сеть", [r"роутер", r"маршрутизатор", r"switch", r"коммутатор", r"точка доступа", r"wifi", r"wi fi"]),
        ("Накопители USB", [r"\busb\b", r"flash", r"флеш", r"накопител"]),
        ("Кабели и переходники", [r"кабель", r"переходник", r"адаптер", r"патч[\s\-]?корд"]),
    ]

    for category_name, patterns in category_rules:
        for pattern in patterns:
            if re.search(pattern, norm):
                return category_name

    tokens = re.findall(r"[a-zа-я0-9\+\-]+", norm)
    if not tokens:
        return "Без категории"
    return tokens[0].upper()


def get_effective_category(row, overrides=None):
    if overrides is None:
        overrides = load_category_overrides()
    for key in build_item_category_keys(row):
        manual = str(overrides.get(key, "")).strip()
        if manual:
            return manual
    return infer_category(row.get("Название", ""))


def row_category(row, overrides=None):
    existing = str(row.get("Категория", "")).strip()
    if existing:
        return existing
    return get_effective_category(row, overrides)


def ensure_category_column(df, overrides=None):
    if overrides is None:
        overrides = load_category_overrides()
    categories = []
    for _, row in df.iterrows():
        categories.append(row_category(row, overrides))
    df["Категория"] = categories
    return df


def round_price_to_90(value):
    """
    Округлить цену вверх до формата *.90.
    Пример: 28.81 -> 28.90, 28.95 -> 29.90
    """
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return np.nan
    v = float(v)
    if v <= 0:
        return 0.9
    base = math.floor(v) + 0.9
    if v > base:
        base += 1.0
    return round(base, 2)


def load_visibility_map(session_dir):
    _ = session_dir  # compatibility: visibility now global, not per-session
    if not CATEGORY_VISIBILITY_FILE.exists():
        return {}
    try:
        with open(CATEGORY_VISIBILITY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_visibility_map(session_dir, visibility_map):
    _ = session_dir  # compatibility: visibility now global, not per-session
    with open(CATEGORY_VISIBILITY_FILE, "w", encoding="utf-8") as f:
        json.dump(visibility_map, f, ensure_ascii=False, indent=2)


def apply_saved_markups_to_df(df):
    if df.empty:
        return df
    markups = load_category_markups()
    if not markups:
        return df
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    # Allow writing numeric RRC values regardless of source column dtype (str/string).
    df["РРЦ"] = df["РРЦ"].astype("object")
    overrides = load_category_overrides()
    for i, row in df.iterrows():
        category = row_category(row, overrides)
        if category not in markups:
            continue
        base_price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(base_price):
            continue
        try:
            percent = float(markups.get(category, 0))
        except Exception:
            continue
        rrc = round_price_to_90(float(base_price) * (1.0 + percent / 100.0))
        df.at[i, "РРЦ"] = rrc
    return df


def apply_visibility_filter(df, session_dir):
    if df.empty or "Поставщик" not in df.columns or "Название" not in df.columns:
        return df
    visibility_map = load_visibility_map(session_dir)
    if not visibility_map:
        return df

    overrides = load_category_overrides()
    mask = []
    for i, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip()
        category = row_category(row, overrides)
        hidden_for_supplier = set(visibility_map.get(supplier, []))
        mask.append(category not in hidden_for_supplier)
    filtered = df[pd.Series(mask, index=df.index)].copy()
    # Защита от "пустого результата": если сохраненные скрытия убрали все строки,
    # возвращаем исходный df, чтобы пользователь не видел "пустой обработанный прайс".
    if filtered.empty and not df.empty:
        return df
    return filtered


def write_consolidated_json(df, json_path):
    def _safe_json_value(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        if isinstance(value, (np.floating, float)):
            fv = float(value)
            if not math.isfinite(fv):
                return ""
            return round(fv, 2)
        if isinstance(value, (np.integer, int)):
            return int(value)
        if isinstance(value, str):
            return value.strip()
        return value

    cons_data = []
    for _, row in df.iterrows():
        cons_data.append([
            _safe_json_value(row.get("OnlinerID", "")),
            _safe_json_value(row.get("Название", "")),
            _safe_json_value(row.get("Цена", 0)),
            _safe_json_value(row.get("Поставщик", "")),
            _safe_json_value(row.get("Гарантия", "")),
            _safe_json_value(row.get("Под заказ", "от 2х дней")) or "от 2х дней",
            _safe_json_value(row.get("РРЦ", "")),
        ])
    with open(str(json_path), "w", encoding="utf-8") as f:
        json.dump({"data": cons_data}, f, ensure_ascii=False, allow_nan=False)


def read_consolidated_df(session_dir):
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    with CONSOLIDATED_IO_LOCK:
        return pd.read_excel(cons_path)


def write_consolidated_df(session_dir, df):
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    tmp_path = Path(session_dir) / "consolidated_price.tmp.xlsx"
    with CONSOLIDATED_IO_LOCK:
        df.to_excel(tmp_path, index=False)
        os.replace(tmp_path, cons_path)


@app.route("/upload", methods=["POST"])
def upload():
    session_id = str(uuid.uuid4())[:8]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(exist_ok=True)

    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return redirect(url_for("index", error="Не загружено ни одного файла"))

    supplier_mapping = {}
    for key in request.form:
        if key.startswith("supplier_"):
            fname = key.replace("supplier_", "")
            supplier_mapping[fname] = request.form[key].strip()

    all_frames = []
    supplier_names = set()
    
    for file in files:
        if not file.filename:
            continue
        fname_enc = file.filename
        from urllib.parse import quote, unquote
        for enc_fname, sup_name in supplier_mapping.items():
            if unquote(enc_fname) == fname_enc or enc_fname == fname_enc:
                supplier_name = sup_name
                break
        else:
            supplier_name = "Unknown"
        
        if not supplier_name:
            supplier_name = "Unknown"
        
        filepath = session_dir / file.filename
        file.save(str(filepath))
        
        try:
            df = parse_generic_excel(filepath, supplier_name)
            if not df.empty:
                all_frames.append(df)
                supplier_names.add(supplier_name)
                print(f"Загружен {file.filename}: {len(df)} товаров, поставщик: {supplier_name}")
        except Exception as e:
            print(f"Ошибка парсинга {file.filename}: {e}")
            import traceback
            traceback.print_exc()

    if not all_frames:
        shutil.rmtree(session_dir, ignore_errors=True)
        return redirect(url_for("index", error="Не удалось обработать файлы"))

    all_data = pd.concat(all_frames, ignore_index=True)
    print(f"Всего загружено: {len(all_data)} товаров")
    print(f"Колонки: {list(all_data.columns)}")
    if "onliner_id" in all_data.columns:
        print(f"С OnlinerID: {all_data['onliner_id'].notna().sum()}")
    
    consolidated_df = consolidate_simple(all_data)
    consolidated_df = ensure_category_column(consolidated_df)
    consolidated_df = apply_saved_markups_to_df(consolidated_df)
    
    # Подставляем ID из кэша: сначала ручные привязки по имени, затем по артикулу.
    manual_bindings = load_manual_id_bindings()
    id_cache = load_id_cache()
    id_fanout = build_id_fanout_map(id_cache)
    for i, row in consolidated_df.iterrows():
        oid = row.get("OnlinerID")
        if not oid or str(oid).strip() == "" or str(oid) == "nan":
            name = row.get("Название", "")
            name_key = _normalize_name_key(name)
            manual = manual_bindings.get(name_key) if name_key else None
            if isinstance(manual, dict):
                mid = normalize_onliner_id(manual.get("id", ""))
                if mid:
                    consolidated_df.at[i, "OnlinerID"] = mid
                    continue
            cache_key = get_article_from_name(name)
            if cache_key in id_cache:
                cached = id_cache[cache_key]
                if is_trusted_cached_id(cache_key, cached, id_fanout=id_fanout):
                    consolidated_df.at[i, "OnlinerID"] = cached["id"]

    output_path = session_dir / "consolidated_price.xlsx"
    consolidated_df.to_excel(output_path, index=False)

    write_consolidated_json(consolidated_df, session_dir / "consolidated.json")

    stats = {
        "total": len(all_data),
        "suppliers": len(supplier_names),
        "consolidated": len(consolidated_df),
        "matched": int(all_data["onliner_id"].notna().sum()) if "onliner_id" in all_data.columns else 0,
        "without_id": len(consolidated_df) - sum(1 for _, r in consolidated_df.iterrows() if r.get("OnlinerID") and str(r.get("OnlinerID")).strip()),
    }

    session["session_id"] = session_id
    session["output_path"] = str(output_path)
    session["session_dir"] = str(session_dir)

    return render_template_string(RESULT_PAGE, stats=stats)


@app.route("/api/consolidated")
def api_consolidated():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"data": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"data": []})
    df = read_consolidated_df(session_dir)
    df = apply_visibility_filter(df, session_dir)

    path = Path(session_dir) / "consolidated.json"
    write_consolidated_json(df, path)
    return send_file(str(path), mimetype="application/json")


@app.route("/api/id-verify-batch", methods=["POST"])
def api_id_verify_batch():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list):
        return jsonify({"items": []})
    items = items[:200]
    out = []
    for it in items:
        key = str((it or {}).get("key", "")).strip()
        oid = normalize_onliner_id((it or {}).get("id", ""))
        local_name = str((it or {}).get("name", "")).strip()
        result = verify_catalog_id_with_prefix(oid, local_name)
        out.append({
            "key": key,
            "status": result.get("status", "unverified"),
            "score": float(result.get("score", 0.0) or 0.0),
            "catalog_name": str(result.get("catalog_name", "")).strip(),
            "url": str(result.get("url", "")).strip(),
            "catalog_id": str(result.get("catalog_id", "")).strip(),
        })
    return jsonify({"items": out})


@app.route("/api/id-verify-category-base", methods=["POST"])
def api_id_verify_category_base():
    """
    Стабильная проверка базы по выбранной категории:
    выполняется полностью на сервере одним запросом (без фронтовых батчей).
    """
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "")).strip()
    try:
        limit = int(payload.get("limit", 6000))
    except Exception:
        limit = 6000
    limit = max(1, min(limit, 10000))
    if not category:
        return jsonify({"items": []})

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)

    # Важный момент: грузим индекс каталога один раз на весь прогон категории.
    # Иначе на больших категориях можно зависнуть на повторных загрузках.
    catalog_index = _load_catalog_sheet_index(force_reload=False, light=True)
    if not isinstance(catalog_index, dict) or not catalog_index.get("by_id"):
        catalog_index = _load_catalog_sheet_index(force_reload=True, light=True)

    out = []
    for i, row in df.iterrows():
        local_category = row_category(row)
        if local_category != category:
            continue
        key = f"row:{int(i)}"
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        local_name = str(row.get("Название", "")).strip()
        result = verify_catalog_id_with_prefix(oid, local_name, catalog_index=catalog_index)
        out.append({
            "key": key,
            "status": result.get("status", "unverified"),
            "score": float(result.get("score", 0.0) or 0.0),
            "catalog_name": str(result.get("catalog_name", "")).strip(),
            "url": str(result.get("url", "")).strip(),
            "catalog_id": str(result.get("catalog_id", "")).strip(),
        })
        if len(out) >= limit:
            break
    return jsonify({"items": out})


@app.route("/api/id-verify-api-batch", methods=["POST"])
def api_id_verify_api_batch():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list):
        return jsonify({"items": []})
    items = items[:200]
    cache = load_onliner_product_cache()
    touched = False
    out = []
    for it in items:
        key = str((it or {}).get("key", "")).strip()
        oid = normalize_onliner_id((it or {}).get("id", ""))
        local_name = str((it or {}).get("name", "")).strip()
        local_category = str((it or {}).get("category", "")).strip() or infer_category(local_name)
        if not oid:
            out.append({
                "key": key,
                "status": "no_id",
                "score": 0.0,
                "api_id": "",
                "api_name": "",
                "url": "",
            })
            continue
        # Строгая проверка по ID: не доверяем старому кэшу при валидации.
        info = fetch_onliner_product_info(oid, cache=cache, force_refresh=True, use_cache_on_error=False)
        if info.get("source") == "api":
            touched = True
        api_name = str(info.get("name", "")).strip()
        api_url = str(info.get("url", "")).strip()
        api_id = oid if api_name else ""
        # Если API вернул товар из чужой категории (например, plaid вместо cpu),
        # не считаем это mismatch: помечаем как unverified и не чистим ID автоматически.
        hints = _category_path_hints(local_category)
        if api_name and hints and api_url and not any(h in api_url for h in hints):
            out.append({
                "key": key,
                "status": "unverified",
                "score": 0.0,
                "api_id": api_id or oid,
                "api_name": "",
                "url": "",
            })
            continue
        if not api_name:
            fallback = search_onliner_product_by_name(local_name)
            api_id = str(fallback.get("id", "")).strip()
            api_name = str(fallback.get("name", "")).strip()
            api_url = str(fallback.get("url", "")).strip()
            fallback_score = float(fallback.get("score", 0.0) or 0.0)
            if api_name:
                out.append({
                    "key": key,
                    # В fallback по названию нельзя ставить mismatch:
                    # это только подсказка, а не валидация текущего ID.
                    "status": "unverified" if normalize_onliner_id(api_id) != oid else "match",
                    "score": fallback_score,
                    "api_id": api_id,
                    "api_name": api_name,
                    "url": api_url,
                })
                continue
            out.append({
                "key": key,
                "status": "unverified",
                "score": 0.0,
                "api_id": "",
                "api_name": "",
                "url": api_url,
            })
            continue
        cmp = calc_name_match(local_name, api_name)
        out.append({
            "key": key,
            "status": "match" if cmp.get("match") else "mismatch",
            "score": float(cmp.get("score", 0.0) or 0.0),
            "api_id": api_id or oid,
            "api_name": api_name,
            "url": api_url,
        })
    if touched:
        save_onliner_product_cache(cache)
    return jsonify({"items": out})


@app.route("/api/manual-id-bind", methods=["POST"])
def api_manual_id_bind():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    supplier = str(payload.get("supplier", "")).strip()
    item_key = str(payload.get("item_key", "")).strip()
    row_idx_raw = payload.get("row_idx", None)
    oid = normalize_onliner_id(payload.get("onliner_id", ""))
    if not name or not oid:
        return jsonify({"status": "error", "message": "Нужно имя товара и OnlinerID"}), 400

    cache_key = get_article_from_name(name)
    final_url = str(payload.get("url", "")).strip()

    if cache_key:
        id_cache = load_id_cache()
        id_cache[cache_key] = {"id": oid, "url": final_url}
        save_id_cache(id_cache)

    # Вечная ручная привязка по нормализованному имени товара.
    target_name_key = _normalize_name_key(name)
    if target_name_key:
        manual_bindings = load_manual_id_bindings()
        manual_bindings[target_name_key] = {"id": oid, "url": final_url}
        save_manual_id_bindings(manual_bindings)

    df = read_consolidated_df(session_dir)
    updated = 0
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    # URL-строки должны писаться в object-колонку (иначе pandas может держать float64 и падать).
    df["Ссылка"] = df["Ссылка"].astype("object")
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    target_row_idx = None
    try:
        if row_idx_raw is not None and str(row_idx_raw).strip() != "":
            target_row_idx = int(row_idx_raw)
    except Exception:
        target_row_idx = None

    # Безопасный режим для ID-check: обновляем строго одну выбранную строку.
    if target_row_idx is not None:
        if target_row_idx in df.index:
            df.at[target_row_idx, "OnlinerID"] = oid
            if final_url:
                df.at[target_row_idx, "Ссылка"] = final_url
            write_consolidated_df(session_dir, df)
            write_consolidated_json(df, Path(session_dir) / "consolidated.json")
            return jsonify({"status": "ok", "updated": 1, "cache_key": cache_key or "", "onliner_id": oid})
        return jsonify({
            "status": "error",
            "message": "Выбранная строка не найдена. Обновите проверку категории.",
            "updated": 0,
            "onliner_id": oid,
        }), 400

    for i, row in df.iterrows():
        row_name = str(row.get("Название", "")).strip()
        row_supplier = str(row.get("Поставщик", "")).strip()
        matched = False

        # 1) Самый точный путь: совпадение item_key из UI со стабильными ключами строки.
        if item_key:
            keys = set(build_item_category_keys(row))
            if item_key in keys:
                matched = True

        # 2) Совпадение по артикулу (если артикул удалось извлечь).
        if not matched and cache_key:
            if get_article_from_name(row_name) == cache_key:
                matched = True

        # 3) Фолбэк: нормализованное имя.
        if not matched and target_name_key and _normalize_name_key(row_name) == target_name_key:
            matched = True

        if not matched:
            continue
        if supplier and row_supplier and row_supplier != supplier:
            continue
        df.at[i, "OnlinerID"] = oid
        if final_url:
            df.at[i, "Ссылка"] = final_url
        updated += 1

    # Fallback pass: если из-за supplier/ключей не обновили ни одной строки,
    # обновляем по точному нормализованному имени без учета поставщика.
    if updated <= 0 and target_name_key:
        for i, row in df.iterrows():
            row_name = str(row.get("Название", "")).strip()
            if _normalize_name_key(row_name) != target_name_key:
                continue
            df.at[i, "OnlinerID"] = oid
            if final_url:
                df.at[i, "Ссылка"] = final_url
            updated += 1

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    if updated <= 0:
        return jsonify({
            "status": "error",
            "message": "Не найдено строк для обновления. Проверьте категорию/поставщика.",
            "updated": 0,
            "onliner_id": oid,
        }), 400

    return jsonify({"status": "ok", "updated": updated, "cache_key": cache_key or "", "onliner_id": oid})


@app.route("/api/clear-invalid-onliner-ids", methods=["POST"])
def api_clear_invalid_onliner_ids():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"status": "ok", "cleared": 0})

    keys_to_clear = set()
    ids_to_clear = set()
    for it in items[:2000]:
        key = str((it or {}).get("key", "")).strip()
        oid = normalize_onliner_id((it or {}).get("onliner_id", ""))
        if key:
            keys_to_clear.add(key)
        if oid:
            ids_to_clear.add(oid)

    if not keys_to_clear and not ids_to_clear:
        return jsonify({"status": "ok", "cleared": 0})

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return jsonify({"status": "ok", "cleared": 0})
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")

    cleared = 0
    touched_name_keys = []
    touched_articles = []
    for i, row in df.iterrows():
        row_key = build_item_category_key(row)
        row_oid = normalize_onliner_id(row.get("OnlinerID", ""))
        should_clear = False
        if row_key and row_key in keys_to_clear:
            should_clear = True
        elif row_oid and row_oid in ids_to_clear:
            should_clear = True
        if not should_clear:
            continue
        if row_oid:
            name = str(row.get("Название", "")).strip()
            touched_name_keys.append(_normalize_name_key(name))
            touched_articles.append(get_article_from_name(name))
        df.at[i, "OnlinerID"] = ""
        df.at[i, "Ссылка"] = ""
        cleared += 1

    if cleared > 0:
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        # Чистим кэши ручных/артикульных привязок для этих товаров, чтобы старый ID не возвращался.
        id_cache = load_id_cache()
        changed_id_cache = False
        for art in touched_articles:
            a = str(art or "").strip()
            if not a:
                continue
            rec = id_cache.get(a)
            if isinstance(rec, dict):
                rid = normalize_onliner_id(rec.get("id", ""))
                if rid and rid in ids_to_clear:
                    id_cache.pop(a, None)
                    changed_id_cache = True
        if changed_id_cache:
            save_id_cache(id_cache)

        bindings = load_manual_id_bindings()
        changed_bindings = False
        for nk in touched_name_keys:
            k = str(nk or "").strip()
            if not k:
                continue
            rec = bindings.get(k)
            if isinstance(rec, dict):
                rid = normalize_onliner_id(rec.get("id", ""))
                if rid and rid in ids_to_clear:
                    bindings.pop(k, None)
                    changed_bindings = True
        if changed_bindings:
            save_manual_id_bindings(bindings)

    return jsonify({"status": "ok", "cleared": int(cleared)})


@app.route("/api/id-replace-candidates", methods=["POST"])
def api_id_replace_candidates():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    query = str(payload.get("query", "")).strip()
    current_id = normalize_onliner_id(payload.get("onliner_id", ""))
    try:
        limit = int(payload.get("limit", 80))
    except Exception:
        limit = 80
    limit = max(10, min(limit, 150))

    if not name and not query:
        return jsonify({"items": []})

    items = []
    seen = set()

    # 1) Быстрый приоритет: текущий ID (для сравнения) сразу в список.
    if current_id:
        # Для окна замены показываем актуальный товар по текущему ID (без фантомного кэша).
        info = fetch_onliner_product_info(current_id, force_refresh=False, use_cache_on_error=True)
        cur_name = str(info.get("name", "")).strip()
        cur_url = str(info.get("url", "")).strip()
        hints = _category_path_hints(category)
        if hints and cur_url and not any(h in cur_url for h in hints):
            cur_name = ""
            cur_url = ""
        items.append({
            "id": current_id,
            "name": cur_name or f"Текущий ID {current_id}",
            "url": cur_url,
            "score": 0.0,
            "source": "current",
        })
        seen.add(current_id)

    # 2) API-кандидаты (только API, без каталожной базы).
    for c in search_onliner_candidates(
        name,
        category_name=category,
        query=query,
        limit=limit,
        max_queries=2,
        timeout_sec=6,
    ):
        cid = normalize_onliner_id(c.get("id", ""))
        if not cid or cid in seen:
            continue
        items.append(c)
        seen.add(cid)
        if len(items) >= limit:
            break

    return jsonify({"items": items[:limit]})


@app.route("/api/categories")
def api_categories():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"categories": []})

    df = read_consolidated_df(session_dir)
    if "Название" not in df.columns:
        return jsonify({"categories": []})

    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    category_counts = {}
    for i, row in df.iterrows():
        category = row_category(row)
        category_counts[category] = category_counts.get(category, 0) + 1

    items = [
        {"name": name, "count": count}
        for name, count in sorted(category_counts.items(), key=lambda x: _category_sort_key(x[0]))
    ]
    return jsonify({"categories": items})


@app.route("/api/category-catalog")
def api_category_catalog():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": CATEGORY_PRIORITY})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    all_cats = set(CATEGORY_PRIORITY)
    overrides = load_category_overrides()
    all_cats.update(v for v in overrides.values() if str(v).strip())
    all_cats.update(k for k in load_category_markups().keys() if str(k).strip())
    if cons_path.exists():
        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df, overrides)
        for _, row in df.iterrows():
            all_cats.add(row_category(row, overrides))
    return jsonify({"categories": sorted(all_cats, key=_category_sort_key)})


@app.route("/api/suppliers")
def api_suppliers():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"suppliers": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"suppliers": []})
    df = read_consolidated_df(session_dir)
    suppliers = sorted({str(s).strip() for s in df.get("Поставщик", pd.Series(dtype=str)).dropna().tolist() if str(s).strip()})
    return jsonify({"suppliers": suppliers})


@app.route("/api/supplier-categories")
def api_supplier_categories():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": []})
    supplier = str(request.args.get("supplier", "")).strip()
    if not supplier:
        return jsonify({"categories": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"categories": []})

    df = read_consolidated_df(session_dir)
    if "Поставщик" not in df.columns:
        return jsonify({"categories": []})
    df = df[df["Поставщик"].astype(str).str.strip() == supplier]
    df = ensure_category_column(df)
    visibility_map = load_visibility_map(session_dir)
    hidden_set = set(visibility_map.get(supplier, []))

    counts = {}
    for _, row in df.iterrows():
        cat = row_category(row)
        counts[cat] = counts.get(cat, 0) + 1

    items = []
    for name, count in sorted(counts.items(), key=lambda x: _category_sort_key(x[0])):
        items.append({"name": name, "count": count, "hidden": name in hidden_set})
    return jsonify({"categories": items})


@app.route("/api/category-visibility", methods=["POST"])
def api_category_visibility():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})
    payload = request.get_json(silent=True) or {}
    supplier = str(payload.get("supplier", "")).strip()
    categories = payload.get("categories", [])
    hidden = bool(payload.get("hidden", True))

    if not supplier:
        return jsonify({"status": "error", "message": "Поставщик не выбран"})
    if not isinstance(categories, list) or not categories:
        return jsonify({"status": "error", "message": "Категории не выбраны"})

    cats = {str(c).strip() for c in categories if str(c).strip()}
    visibility_map = load_visibility_map(session_dir)
    current = set(visibility_map.get(supplier, []))
    if hidden:
        current.update(cats)
    else:
        current.difference_update(cats)

    if current:
        visibility_map[supplier] = sorted(current)
    elif supplier in visibility_map:
        visibility_map.pop(supplier)
    save_visibility_map(session_dir, visibility_map)
    return jsonify({"status": "ok"})


@app.route("/api/apply-markup", methods=["POST"])
def api_apply_markup():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    cons_json_path = Path(session_dir) / "consolidated.json"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    percent = payload.get("percent", None)
    base_mode = str(payload.get("base_mode", "wholesale")).strip().lower()
    if base_mode not in {"wholesale", "onliner_min", "onliner_avg"}:
        base_mode = "wholesale"
    if not isinstance(categories, list) or not categories:
        return jsonify({"status": "error", "message": "Категории не выбраны"})
    try:
        percent = float(percent)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректный процент"})
    if percent < 0:
        return jsonify({"status": "error", "message": "Процент не может быть отрицательным"})

    df = read_consolidated_df(session_dir)
    if "Название" not in df.columns or "Цена" not in df.columns:
        return jsonify({"status": "error", "message": "В файле нет нужных колонок"})
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    df["РРЦ"] = df["РРЦ"].astype("object")
    df = ensure_category_column(df)

    selected = set(str(c).strip() for c in categories if str(c).strip())
    market_map = {}
    market_checked = 0
    if base_mode in {"onliner_min", "onliner_avg"}:
        ids = []
        for _, row in df.iterrows():
            category = row_category(row)
            if category not in selected:
                continue
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if oid:
                ids.append(oid)
        # Protect against extremely heavy external checks on huge selections.
        unique_ids = list(dict.fromkeys(ids))[:400]
        market_checked = len(unique_ids)
        market_map = get_onliner_market_stats_bulk(unique_ids, max_workers=8)

    updated = 0
    eligible = 0
    missing_market = 0
    for i, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        eligible += 1
        base_price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(base_price):
            continue
        calc_base = float(base_price)
        if base_mode in {"onliner_min", "onliner_avg"}:
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            stats = market_map.get(oid, {}) if oid else {}
            market_price = stats.get("min") if base_mode == "onliner_min" else stats.get("avg")
            if market_price is None:
                missing_market += 1
            else:
                calc_base = float(market_price)
        rrc = round_price_to_90(calc_base * (1.0 + percent / 100.0))
        df.at[i, "РРЦ"] = rrc
        updated += 1

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, cons_json_path)
    # Запоминаем последнюю наценку для выбранных категорий.
    markups = load_category_markups()
    for c in selected:
        markups[c] = percent
    save_category_markups(markups)
    return jsonify({
        "status": "ok",
        "updated": updated,
        "eligible": eligible,
        "total": len(df),
        "percent": percent,
        "base_mode": base_mode,
        "market_checked": market_checked,
        "missing_market": missing_market,
    })


@app.route("/api/markup-preview", methods=["POST"])
def api_markup_preview():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    percent = payload.get("percent", 0)
    limit = payload.get("limit", 8)

    try:
        percent = float(percent)
    except Exception:
        percent = 0.0
    try:
        limit = int(limit)
    except Exception:
        limit = 8
    limit = max(1, min(limit, 20))

    selected = {str(c).strip() for c in categories if str(c).strip()}
    if not selected:
        return jsonify({"items": []})

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    if "Название" not in df.columns or "Цена" not in df.columns:
        return jsonify({"items": []})

    items = []
    for i, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(price):
            continue
        old_rrc = pd.to_numeric(row.get("РРЦ", np.nan), errors="coerce")
        calc_rrc = round_price_to_90(float(price) * (1.0 + percent / 100.0))
        items.append({
            "category": category,
            "name": str(row.get("Название", "")),
            "price": round(float(price), 2),
            "old_rrc": "" if pd.isna(old_rrc) else round(float(old_rrc), 2),
            "new_rrc": round(float(calc_rrc), 2),
        })
        if len(items) >= limit:
            break

    return jsonify({"items": items})


@app.route("/api/category-override-items")
def api_category_override_items():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    query = str(request.args.get("q", "")).strip().lower()
    limit = int(request.args.get("limit", 40) or 40)
    limit = max(1, min(limit, 200))

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if "Название" not in df.columns:
        return jsonify({"items": []})

    overrides = load_category_overrides()
    result = []
    for _, row in df.iterrows():
        name = str(row.get("Название", ""))
        if not name:
            continue
        if query and query not in name.lower():
            continue
        key = build_item_category_key(row)
        auto_cat = infer_category(name)
        eff_cat = row_category(row, overrides)
        result.append({
            "key": key,
            "name": name,
            "supplier": str(row.get("Поставщик", "")),
            "auto_category": auto_cat,
            "category": eff_cat,
            "manual": (eff_cat != auto_cat),
        })
        if len(result) >= limit:
            break

    return jsonify({"items": result})


@app.route("/api/category-override-set", methods=["POST"])
def api_category_override_set():
    session_dir = session.get("session_dir")
    payload = request.get_json(silent=True) or {}
    item_key = str(payload.get("item_key", "")).strip()
    target_category = str(payload.get("target_category", "")).strip()

    if not item_key:
        return jsonify({"status": "error", "message": "Товар не выбран"})
    if not target_category:
        return jsonify({"status": "error", "message": "Категория не выбрана"})

    overrides = load_category_overrides()
    overrides[item_key] = target_category

    if session_dir:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if cons_path.exists():
            df = read_consolidated_df(session_dir)
            df = ensure_category_column(df, overrides)
            changed = 0
            for i, row in df.iterrows():
                keys = set(build_item_category_keys(row))
                if item_key in keys:
                    df.at[i, "Категория"] = target_category
                    for k in keys:
                        overrides[k] = target_category
                    changed += 1
            if changed:
                write_consolidated_df(session_dir, df)
                write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_category_overrides(overrides)
    return jsonify({"status": "ok"})


@app.route("/api/category-preview-items", methods=["POST"])
def api_category_preview_items():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    with_market = bool(payload.get("with_market", False))
    for_idcheck = bool(payload.get("for_idcheck", False))
    allow_stale_market = bool(payload.get("allow_stale_market", True))
    try:
        limit = int(payload.get("limit", 4000))
    except Exception:
        limit = 4000
    limit = max(1, min(limit, 10000))
    try:
        max_market_checks = int(payload.get("max_market_checks", 300))
    except Exception:
        max_market_checks = 300
    max_market_checks = max(1, min(max_market_checks, 800))
    selected = {str(c).strip() for c in categories if str(c).strip()}
    if not selected:
        return jsonify({"items": []})

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)

    items = []
    onliner_ids = []
    for i, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        rrc = pd.to_numeric(row.get("РРЦ", np.nan), errors="coerce")
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if with_market and oid:
            onliner_ids.append(oid)
        items.append({
            "key": (f"row:{int(i)}" if for_idcheck else build_item_category_key(row)),
            "row_idx": int(i),
            "onliner_id": oid,
            "name": str(row.get("Название", "")),
            "supplier": str(row.get("Поставщик", "")),
            "category": category,
            "price": "" if pd.isna(price) else round(float(price), 2),
            "rrc": "" if pd.isna(rrc) else round(float(rrc), 2),
        })
        if len(items) >= limit:
            break
    market_map = {}
    market_checked = 0
    if with_market and onliner_ids:
        unique_ids = list(dict.fromkeys(onliner_ids))[:max_market_checks]
        market_checked = len(unique_ids)
        cache = load_onliner_market_cache()
        for oid in unique_ids:
            market_map[oid] = get_onliner_market_stats_from_cache_only(oid, cache=cache, allow_stale=allow_stale_market)
    missing_market = 0
    missing_market_ids = set()
    no_onliner_id = 0
    for it in items:
        oid = it.get("onliner_id", "")
        stats = market_map.get(oid, {}) if oid else {}
        mmin = stats.get("min")
        mavg = stats.get("avg")
        mmax = stats.get("max")
        if with_market and not oid:
            no_onliner_id += 1
        if with_market and oid and (mmin is None and mavg is None):
            missing_market += 1
            missing_market_ids.add(oid)
        it["market_min"] = "" if mmin is None else round(float(mmin), 2)
        it["market_avg"] = "" if mavg is None else round(float(mavg), 2)
        it["market_max"] = "" if mmax is None else round(float(mmax), 2)
        it["market_offers"] = int(stats.get("offers", 0) or 0) if stats else 0
        it["min_competitors"] = int(stats.get("min_competitors", 0) or 0) if stats else 0
        it["avg_competitors"] = int(stats.get("avg_competitors", 0) or 0) if stats else 0

    items.sort(key=lambda x: (x["category"], x["name"].lower()))
    return jsonify({
        "items": items,
        "market_checked": market_checked,
        "missing_market": missing_market,
        "missing_market_ids": len(missing_market_ids),
        "no_onliner_id": no_onliner_id,
    })


def _market_refresh_worker(session_dir, categories):
    try:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if not cons_path.exists():
            with MARKET_REFRESH_LOCK:
                market_refresh_status.update({"running": False, "finished_at": int(time.time())})
            return

        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        selected = {str(c).strip() for c in categories if str(c).strip()}
        if selected:
            df = df[df.apply(lambda r: row_category(r) in selected, axis=1)]

        cat_to_ids = {}
        for _, row in df.iterrows():
            cat = row_category(row)
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            cat_to_ids.setdefault(cat, set()).add(oid)

        all_ids = sorted(set().union(*cat_to_ids.values())) if cat_to_ids else []
        with MARKET_REFRESH_LOCK:
            market_refresh_status["total"] = len(all_ids)
            market_refresh_status["done"] = 0
            market_refresh_status["categories"] = {
                cat: {"done": 0, "total": len(ids), "percent": 0}
                for cat, ids in cat_to_ids.items()
            }

        cache = load_onliner_market_cache()
        now = int(time.time())
        id_to_cats = {}
        for cat, ids in cat_to_ids.items():
            for oid in ids:
                id_to_cats.setdefault(oid, []).append(cat)

        with ThreadPoolExecutor(max_workers=10) as ex:
            fut_to_oid = {ex.submit(fetch_onliner_market_stats, oid): oid for oid in all_ids}
            done_count = 0
            for fut in as_completed(fut_to_oid):
                oid = fut_to_oid[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
                cache[oid] = {"updated_at": now, **stats}
                done_count += 1
                with MARKET_REFRESH_LOCK:
                    market_refresh_status["done"] = done_count
                    for cat in id_to_cats.get(oid, []):
                        st = market_refresh_status["categories"].get(cat)
                        if not st:
                            continue
                        st["done"] += 1
                        st["percent"] = int(round((st["done"] / max(st["total"], 1)) * 100))

        save_onliner_market_cache(cache)
    finally:
        with MARKET_REFRESH_LOCK:
            market_refresh_status["running"] = False
            market_refresh_status["finished_at"] = int(time.time())


def _collect_known_onliner_ids(max_ids=AUTO_REFRESH_MAX_IDS):
    ids = []
    # 1) existing market cache ids
    cache = load_onliner_market_cache()
    ids.extend(cache.keys())
    # 2) id cache ids
    id_cache = load_id_cache()
    if isinstance(id_cache, dict):
        for _, rec in id_cache.items():
            if not isinstance(rec, dict):
                continue
            oid = normalize_onliner_id(rec.get("id", ""))
            if oid:
                ids.append(oid)
    out = []
    seen = set()
    for oid in ids:
        if oid and oid not in seen:
            seen.add(oid)
            out.append(oid)
        if len(out) >= max_ids:
            break
    return out


def _auto_market_refresh_loop():
    # Runs while app process is alive.
    while True:
        try:
            ids = _collect_known_onliner_ids()
            if ids:
                # refresh in bounded batches without touching UI status
                cache = load_onliner_market_cache()
                now = int(time.time())
                with ThreadPoolExecutor(max_workers=8) as ex:
                    fut_to_oid = {ex.submit(fetch_onliner_market_stats, oid): oid for oid in ids}
                    for fut in as_completed(fut_to_oid):
                        oid = fut_to_oid[fut]
                        try:
                            stats = fut.result()
                        except Exception:
                            stats = {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
                        cache[oid] = {"updated_at": now, **stats}
                save_onliner_market_cache(cache)
        except Exception:
            pass
        time.sleep(AUTO_REFRESH_INTERVAL_SEC)


@app.route("/api/market-refresh-start", methods=["POST"])
def api_market_refresh_start():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})
    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    if not isinstance(categories, list):
        categories = []
    with MARKET_REFRESH_LOCK:
        if market_refresh_status.get("running"):
            return jsonify({"status": "already_running"})
        market_refresh_status["running"] = True
        market_refresh_status["started_at"] = int(time.time())
        market_refresh_status["finished_at"] = 0
        market_refresh_status["total"] = 0
        market_refresh_status["done"] = 0
        market_refresh_status["categories"] = {}
    threading.Thread(
        target=_market_refresh_worker,
        args=(session_dir, categories),
        daemon=True,
    ).start()
    return jsonify({"status": "started"})


@app.route("/api/market-refresh-status")
def api_market_refresh_status():
    with MARKET_REFRESH_LOCK:
        st = dict(market_refresh_status)
        cats = st.get("categories", {}) or {}
        cats_pct = {
            k: {
                "done": int(v.get("done", 0)),
                "total": int(v.get("total", 0)),
                "percent": int(v.get("percent", 0)),
            }
            for k, v in cats.items()
        }
        total = int(st.get("total", 0))
        done = int(st.get("done", 0))
        overall = int(round((done / max(total, 1)) * 100)) if total else 0
        return jsonify({
            "running": bool(st.get("running")),
            "total": total,
            "done": done,
            "overall_percent": overall,
            "categories": cats_pct,
            "started_at": int(st.get("started_at", 0)),
            "finished_at": int(st.get("finished_at", 0)),
        })


@app.route("/api/category-markups")
def api_category_markups():
    return jsonify({"markups": load_category_markups()})


@app.route("/api/category-override-bulk", methods=["POST"])
def api_category_override_bulk():
    session_dir = session.get("session_dir")
    payload = request.get_json(silent=True) or {}
    item_keys = payload.get("item_keys", [])
    target_category = str(payload.get("target_category", "")).strip()
    if not isinstance(item_keys, list) or not item_keys:
        return jsonify({"status": "error", "message": "Не выбраны товары"})
    if not target_category:
        return jsonify({"status": "error", "message": "Не выбрана целевая категория"})

    keys = [str(k).strip() for k in item_keys if str(k).strip()]
    if not keys:
        return jsonify({"status": "error", "message": "Не выбраны товары"})

    overrides = load_category_overrides()
    for key in keys:
        overrides[key] = target_category

    updated_rows = 0
    if session_dir:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if cons_path.exists():
            df = read_consolidated_df(session_dir)
            df = ensure_category_column(df, overrides)
            key_set = set(keys)
            for i, row in df.iterrows():
                row_keys = set(build_item_category_keys(row))
                if key_set.intersection(row_keys):
                    df.at[i, "Категория"] = target_category
                    for k in row_keys:
                        overrides[k] = target_category
                    updated_rows += 1
            if updated_rows:
                write_consolidated_df(session_dir, df)
                write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_category_overrides(overrides)

    return jsonify({"status": "ok", "updated": len(keys), "updated_rows": updated_rows})


@app.route("/api/resolve-start", methods=["POST"])
def api_resolve_start():
    global resolve_status
    if resolve_status["running"]:
        return jsonify({"status": "already_running"})

    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    df = read_consolidated_df(session_dir)
    
    id_to_name = {}
    for _, row in df.iterrows():
        oid = row.get("OnlinerID")
        name = row.get("Название", "")
        if oid and str(oid).strip() and str(oid) != "nan":
            id_to_name[str(oid)] = name
    
    all_ids = list(id_to_name.keys())
    cache = load_url_cache()
    uncached = [oid for oid in all_ids if oid not in cache]

    resolve_status = {
        "running": True,
        "resolved": 0,
        "total": len(uncached),
        "cached": len(cache),
    }

    def _run_resolve():
        global resolve_status
        try:
            def progress(done, total):
                resolve_status["resolved"] = done
                resolve_status["cached"] = len(cache)

            resolve_onliner_urls(uncached, cache=cache, max_workers=5, progress_callback=progress, id_to_name=id_to_name)
            resolve_status["resolved"] = resolve_status["total"]
            resolve_status["cached"] = len(cache)
            
            df = read_consolidated_df(session_dir)
            for i, row in df.iterrows():
                oid = row.get("OnlinerID")
                if oid and str(oid) in cache:
                    df.at[i, "Ссылка"] = cache.get(str(oid), "")
            write_consolidated_df(session_dir, df)
            
            cons_json_path = Path(session_dir) / "consolidated.json"
            write_consolidated_json(df, cons_json_path)
        finally:
            resolve_status["running"] = False

    thread = threading.Thread(target=_run_resolve, daemon=True)
    thread.start()

    return jsonify({"status": "started", "total": len(uncached)})


@app.route("/api/resolve-status")
def api_resolve_status():
    return jsonify(resolve_status)


@app.route("/api/find-ids-start", methods=["POST"])
def api_find_ids_start():
    global find_id_status
    if find_id_status["running"]:
        return jsonify({"status": "already_running"})

    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    df = read_consolidated_df(session_dir)
    
    items = []
    for _, row in df.iterrows():
        oid = row.get("OnlinerID")
        name = row.get("Название", "")
        if (not oid or str(oid).strip() == "" or str(oid) == "nan") and name:
            items.append({"name": name, "idx": len(items)})

    if not items:
        return jsonify({"status": "done", "message": "Все товары уже имеют OnlinerID"})

    id_cache, removed_negatives = prune_negative_id_cache()
    if removed_negatives:
        print(f"Очищено пустых записей ID-кэша: {removed_negatives}")

    need_search = []
    already_found = 0
    id_fanout = build_id_fanout_map(id_cache)
    for item in items:
        name = item.get("name", "")
        cache_key = get_article_from_name(name)
        if cache_key in id_cache:
            if is_trusted_cached_id(cache_key, id_cache[cache_key], id_fanout=id_fanout):
                already_found += 1
            else:
                need_search.append(item)
        else:
            need_search.append(item)

    if not need_search:
        return jsonify({
            "status": "done",
            "message": (
                f"Кэш: найдено {already_found}, "
                "новых товаров для поиска нет"
            )
        })

    find_id_status = {
        "running": True,
        "checked": 0,
        "total": len(need_search),
        "found": already_found,
        "phase": "sheet",
        "sheet_checked": 0,
        "sheet_total": len(need_search),
        "sheet_found": 0,
        "api_checked": 0,
        "api_total": 0,
        "api_found": 0,
        "not_found": 0,
    }

    def _run_find():
        global find_id_status
        try:
            def progress(done, total, found, meta=None):
                find_id_status["checked"] = done
                find_id_status["found"] = found
                if meta:
                    for key in (
                        "phase",
                        "sheet_checked",
                        "sheet_total",
                        "sheet_found",
                        "api_checked",
                        "api_total",
                        "api_found",
                        "not_found",
                    ):
                        if key in meta:
                            find_id_status[key] = meta[key]
            
            id_cache, found = find_missing_onliner_ids(
                need_search,
                progress_callback=progress,
                max_workers=6,
                use_api_search=False,
            )
            find_id_status["found"] = found
            find_id_status["phase"] = "done"
            
            print(f"Search completed. Found total: {found}")
            print(f"Cache entries: {len(id_cache)}")
            
            # Перезагружаем кэш чтобы получить все найденные ID
            id_cache = load_id_cache()
            id_fanout = build_id_fanout_map(id_cache)
            print(f"Reloaded cache: {len(id_cache)} entries")

            url_cache, warm_count = warm_url_cache_from_id_cache(id_cache=id_cache)
            if warm_count:
                print(f"Подогрели кэш ссылок из ID-кэша: +{warm_count}")
            
            df = read_consolidated_df(session_dir)
            print(f"Excel rows: {len(df)}")
            
            updated = 0
            for i, row in df.iterrows():
                oid = row.get("OnlinerID")
                name = row.get("Название", "")
                if (not oid or str(oid).strip() == "" or str(oid) == "nan") and name:
                    cache_key = get_article_from_name(name)
                    if cache_key in id_cache:
                        cached = id_cache[cache_key]
                        if is_trusted_cached_id(cache_key, cached, id_fanout=id_fanout):
                            df.at[i, "OnlinerID"] = cached["id"]
                            cached_url = str(cached.get("url", "")).strip()
                            if cached_url:
                                df.at[i, "Ссылка"] = cached_url
                                url_cache[str(cached["id"])] = cached_url
                            updated += 1
                            if updated <= 5:
                                print(f"  Updated: {cache_key} -> {cached['id']}")

            quality = enforce_catalog_consistency(df, session_dir=session_dir)
            print(
                "ID quality after find:"
                f" checked={quality['checked']},"
                f" set={quality['set_from_catalog']},"
                f" corrected={quality['corrected_conflicts']},"
                f" cleared={quality['cleared_unverified']},"
                f" report_rows={quality['report_rows']}"
            )
            
            print(f"Total updated: {updated} OnlinerIDs")
            
            if updated > 0:
                write_consolidated_df(session_dir, df)
                print(f"Saved to: {cons_path}")
                
                cons_json_path = Path(session_dir) / "consolidated.json"
                write_consolidated_json(df, cons_json_path)
                print(f"Updated JSON: {cons_json_path}")
                save_url_cache(url_cache)
            
            find_id_status["checked"] = find_id_status["total"]
        except Exception as e:
            print(f"Error in _run_find: {e}")
            import traceback
            traceback.print_exc()
        finally:
            find_id_status["running"] = False

    thread = threading.Thread(target=_run_find, daemon=True)
    thread.start()

    return jsonify({"status": "started", "total": len(need_search)})


@app.route("/api/find-ids-status")
def api_find_ids_status():
    return jsonify(find_id_status)


@app.route("/download")
def download():
    session_dir = session.get("session_dir")
    output_path = session.get("output_path")
    if output_path and os.path.exists(output_path):
        if not session_dir:
            return send_file(output_path, as_attachment=True, download_name="consolidated_price.xlsx")
        df = pd.read_excel(output_path)
        filtered = apply_visibility_filter(df, session_dir)
        visible_path = Path(session_dir) / "consolidated_price_visible.xlsx"
        filtered.to_excel(visible_path, index=False)
        return send_file(str(visible_path), as_attachment=True, download_name="consolidated_price.xlsx")
    return redirect(url_for("index", error="Файл не найден. Загрузите прайсы заново."))


@app.route("/download/id-quality-report")
def download_id_quality_report():
    session_dir = session.get("session_dir")
    if not session_dir:
        return redirect(url_for("index", error="Нет активной сессии"))
    path = Path(session_dir) / "id_quality_report.csv"
    if not path.exists():
        return redirect(url_for("index", error="ID quality report не найден"))
    return send_file(str(path), as_attachment=True, download_name="id_quality_report.csv")


@app.route("/api/id-quality-report")
def api_id_quality_report():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "no_session"})
    summary_path = Path(session_dir) / "id_quality_report.json"
    report_path = Path(session_dir) / "id_quality_report.csv"
    if not summary_path.exists():
        return jsonify({"status": "not_found"})
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        return jsonify({"status": "error"})
    summary["status"] = "ok"
    summary["has_csv"] = report_path.exists()
    return jsonify(summary)


if __name__ == "__main__":
    print("=" * 50)
    print("Price Mixer Web")
    print("Открой в браузере: http://localhost:5001")
    print("=" * 50)
    # Stable local run mode: no Flask reloader double-process.
    app.run(debug=False, use_reloader=False, host="127.0.0.1", port=5001)
