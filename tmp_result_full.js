
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
var mainTableReloadTimer = null;
var autoSortItems = [];
var autoSortSelectedKeys = {};
var autoRefreshPollTimer = null;
var autoRefreshUiLock = false;
var showOnlyNoIdRows = false;
var noIdInlinePickerState = { rowIdx: -1, loading: false, applyingId: '', message: '', items: [], queryName: '' };
var verifyAllIdsPollTimer = null;
var verifyAllIdsItems = [];
var verifyAllIdsCandidateState = {};
var verifyAllIdsReportItems = [];
var verifyAllIdsReportVisible = false;
var verifyAllIdsCardCollapsed = false;
var duplicateIdIssues = [];
var duplicateIdCandidateState = {};
var duplicateIdCardCollapsed = false;
var duplicateIdProblemCount = 0;
var duplicateIdLastActionMessage = '';
var qualityCheckCardCollapsed = false;
var selectedPreviewRowIdx = -1;
var showOnlySnapshotRows = false;
var snapshotFilterMode = '';
var snapshotFilterNames = [];
var snapshotDetailMode = '';
if (typeof window.showBusyOverlay !== 'function') {
    window.showBusyOverlay = function(){};
}
if (typeof window.updateBusyOverlay !== 'function') {
    window.updateBusyOverlay = function(){};
}
if (typeof window.hideBusyOverlay !== 'function') {
    window.hideBusyOverlay = function(){};
}
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
    window.snapshotDiffData = {{ (stats.snapshot_diff or {})|tojson|safe }};
    if(window.snapshotDiffData && window.snapshotDiffData.filters){
        snapshotFilterNames = [];
    }
    if(window.jQuery && $.fn && $.fn.dataTable && $.fn.dataTable.ext && $.fn.dataTable.ext.search){
        $.fn.dataTable.ext.search.push(function(settings, data, dataIndex, rowData){
            if(settings.nTable && settings.nTable.id !== 'tbl-main'){ return true; }
            if(!showOnlyNoIdRows){ return true; }
            var rawId = '';
            if(Array.isArray(rowData)){
                rawId = String((rowData && rowData[0]) || '').trim();
            } else if(settings && settings.aoData && settings.aoData[dataIndex] && Array.isArray(settings.aoData[dataIndex]._aData)){
                rawId = String((settings.aoData[dataIndex]._aData[0]) || '').trim();
            }
            return !rawId;
        });
        $.fn.dataTable.ext.search.push(function(settings, data, dataIndex, rowData){
            if(settings.nTable && settings.nTable.id !== 'tbl-main'){ return true; }
            if(!showOnlySnapshotRows || !Array.isArray(snapshotFilterNames) || !snapshotFilterNames.length){ return true; }
            var rawName = '';
            if(Array.isArray(rowData)){
                rawName = String((rowData && rowData[1]) || '').trim();
            } else if(settings && settings.aoData && settings.aoData[dataIndex] && Array.isArray(settings.aoData[dataIndex]._aData)){
                rawName = String((settings.aoData[dataIndex]._aData[1]) || '').trim();
            } else if(Array.isArray(data)) {
                rawName = String((data && data[1]) || '').trim();
            }
            return snapshotFilterNames.indexOf(rawName) >= 0;
        });
    }
    if(window.jQuery && $.fn && $.fn.DataTable){
        tblMain = $('#tbl-main').DataTable({
            ajax: {
                url: '/api/consolidated',
                dataSrc: function(json){
                    var rows = (json && json.data) ? json.data : [];
                    mainTableRows = rows;
                    updateWithoutIdCount(rows);
                    return rows;
                }
            },
            deferRender: true,
            pageLength: 100,
            order: [[1, 'asc']],
            language: dtLang,
            drawCallback: function(){
                if(!showOnlyNoIdRows){
                    updateWithoutIdCount(mainTableRows || []);
                    return;
                }
                var api = this.api();
                var visibleRows = api.rows({search: 'applied'}).data().toArray();
                updateWithoutIdCount(visibleRows);
            },
            columns: [
                {data: 0, className: 'dt-center', render: function(d, type, row){return renderMainTableIdCell(String(d || '').trim(), row || []);}}, 
                {data: 1, render: function(d, type, row){ return renderMainTableNameCell(d, row || []); }},
                {data: 2, className: 'dt-center', render: function(d){return d ? '<b style="color:#2e7d32">'+parseFloat(d).toFixed(2)+'</b>' : '';}}, 
                {data: 3, className: 'dt-center'},
                {data: 4, className: 'dt-center'},
                {data: 5, className: 'dt-center'},
                {data: 6, className: 'dt-center', render: function(d){ return (d || d===0) ? parseFloat(d).toFixed(2) : ''; }},
                {data: 7, className: 'dt-center', render: function(d){ return (d || d===0) ? parseFloat(d).toFixed(2) : ''; }}
            ]
        });
    } else {
        initMainTableFallback();
    }
    initMarkupUI();
    initNoIdFilterUI();
    initSnapshotFilterUI();
    initOnlinerDbWidget();
});

function initMainTableFallback(){
    var tbody = document.getElementById('tbl-main-body');
    if(!tbody){ return; }
    fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
        mainTableRows = (d && d.data) ? d.data : [];
        updateWithoutIdCount(mainTableRows);
        renderMainTableFallback();
    }).catch(function(){
        tbody.innerHTML = '<tr><td colspan="8" style="padding:14px;color:#b91c1c;">Ошибка загрузки данных</td></tr>';
    });
    tblMain = {
        ajax: {
            reload: function(cb){
                fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
                    mainTableRows = (d && d.data) ? d.data : [];
                    updateWithoutIdCount(mainTableRows);
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
    if(showOnlyNoIdRows){
        rows = rows.filter(function(r){
            return !String(r[0] || '').trim();
        });
    }
    if(showOnlySnapshotRows && Array.isArray(snapshotFilterNames) && snapshotFilterNames.length){
        rows = rows.filter(function(r){
            return snapshotFilterNames.indexOf(String(r[1] || '').trim()) >= 0;
        });
    }
    updateWithoutIdCount(showOnlyNoIdRows ? rows : mainTableRows);
    if(!rows.length){
        tbody.innerHTML = '<tr><td colspan="8" style="padding:14px;color:#64748b;">Нет данных</td></tr>';
        return;
    }
    var html = '';
    rows.forEach(function(r){
        var oid = String(r[0] || '').trim();
        var rowIdx = Number(r[8] || -1);
        var name = renderMainTableNameCell(r[1] || '', r);
        var price = (r[2] || r[2]===0) ? ('<b style="color:#2e7d32">' + Number(r[2]).toFixed(2) + '</b>') : '';
        var supplier = escapeHtml(r[3] || '');
        var warranty = escapeHtml(r[4] || '');
        var lead = escapeHtml(r[5] || '');
        var rrc = (r[6] || r[6]===0) ? Number(r[6]).toFixed(2) : '';
        var noDiscount = (r[7] || r[7]===0) ? Number(r[7]).toFixed(2) : '';
        html += '<tr>'
            + '<td>' + renderMainTableIdCell(oid, r) + '</td>'
            + '<td>' + name + '</td>'
            + '<td>' + price + '</td>'
            + '<td>' + supplier + '</td>'
            + '<td>' + warranty + '</td>'
            + '<td>' + lead + '</td>'
            + '<td>' + rrc + '</td>'
            + '<td>' + noDiscount + '</td>'
            + '</tr>';
    });
    tbody.innerHTML = html;
}

function redrawMainTable(){
    if(tblMain){
        if(typeof tblMain.draw === 'function'){
            tblMain.draw(false);
        } else if(tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        }
    } else {
        renderMainTableFallback();
    }
}

function initNoIdFilterUI(){
    var btn = document.getElementById('toggle-noid-btn');
    var autoBtn = document.getElementById('autofill-tgpc-pc-btn');
    var autoTestBtn = document.getElementById('autofill-tgpc-pc-test-btn');
    var autoNote = document.getElementById('autofill-tgpc-pc-note');
    var autoTestLimit = autoTestBtn ? Number(autoTestBtn.getAttribute('data-limit') || 100) : 100;
    var autoPollTimer = null;
    var autoVisualTimer = null;
    var autoVisualPercent = 0;
    var autoRunLabel = 'Авто TGPC ПЭВМ';
    function renderAutoReport(items, st){
        var host = document.getElementById('autofill-tgpc-pc-report');
        var chipsEl = document.getElementById('autofill-tgpc-chips');
        if(!host){ return; }
        var list = Array.isArray(items) ? items : [];

        // --- chips summary ---
        if(chipsEl && st && (Number(st.total||0) > 0 || st.finished_at)){
            var applied = Number(st.applied||0);
            var skipped = Number(st.skipped||0);
            var notFound = Math.max(0, Number(st.done||0) - applied - skipped);
            var chips = '';
            if(applied > 0) chips += '<span style="display:inline-flex;align-items:center;gap:3px;background:#dcfce7;color:#15803d;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✓ '+applied+' найдено</span>';
            if(notFound > 0) chips += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fee2e2;color:#dc2626;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✕ '+notFound+' нет на Onliner</span>';
            if(skipped > 0) chips += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fef3c7;color:#b45309;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">~ '+skipped+' низкий score</span>';
            chipsEl.innerHTML = chips;
            chipsEl.style.display = chips ? 'flex' : 'none';
        }

        if(!list.length){ host.innerHTML = ''; return; }

        var matched = list.filter(function(i){ return i && i.status === 'matched'; });
        var others  = list.filter(function(i){ return i && i.status !== 'matched'; });

        var html = '<div style="margin-top:12px;text-align:left;">';

        // --- найдено ---
        if(matched.length){
            html += '<div style="font-size:10px;font-weight:700;color:#15803d;letter-spacing:.05em;text-transform:uppercase;margin-bottom:5px;">✓ Найдено ('+matched.length+')</div>';
            html += '<div style="max-height:210px;overflow-y:auto;border-radius:8px;border:1px solid #bbf7d0;background:#f0fdf4;margin-bottom:10px;">';
            matched.forEach(function(item, idx){
                var border = idx > 0 ? 'border-top:1px solid #dcfce7;' : '';
                html += '<div style="padding:8px 10px;'+border+'">';
                html += '<div style="font-size:12px;font-weight:600;color:#14532d;line-height:1.3;margin-bottom:4px;">'+ escapeHtml(item.name||'') +'</div>';
                html += '<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">';
                if(item.onliner_id){
                    html += '<span style="background:#d1fae5;color:#065f46;border-radius:5px;padding:2px 7px;font-size:11px;font-weight:700;font-family:monospace;">ID&nbsp;'+ escapeHtml(String(item.onliner_id)) +'</span>';
                }
                if(item.score){
                    var sc = Number(item.score);
                    var scColor = sc >= 0.95 ? '#15803d' : '#b45309';
                    html += '<span style="background:#fff;color:'+scColor+';border-radius:5px;padding:2px 6px;font-size:10px;border:1px solid #e5e7eb;">score&nbsp;'+escapeHtml(String(item.score))+'</span>';
                }
                if(item.onliner_name){
                    html += '<span style="font-size:11px;color:#374151;font-style:italic;">'+ escapeHtml(item.onliner_name) +'</span>';
                }
                html += '</div></div>';
            });
            html += '</div>';
        }

        // --- не найдено / пропущено ---
        if(others.length){
            html += '<div style="font-size:10px;font-weight:700;color:#dc2626;letter-spacing:.05em;text-transform:uppercase;margin-bottom:5px;">✕ Не найдено / пропущено ('+others.length+')</div>';
            html += '<div style="max-height:180px;overflow-y:auto;border-radius:8px;border:1px solid #fecaca;background:#fff8f8;">';
            others.forEach(function(item, idx){
                var border = idx > 0 ? 'border-top:1px solid #fee2e2;' : '';
                var isSkip = item.status === 'skipped';
                html += '<div style="padding:7px 10px;'+border+'">';
                html += '<div style="font-size:12px;color:#374151;line-height:1.3;">'+ escapeHtml(item.name||'') +'</div>';
                if(isSkip && item.onliner_id){
                    html += '<div style="font-size:11px;color:#b45309;margin-top:2px;">Найден похожий · ID '+ escapeHtml(String(item.onliner_id)) +' · score '+ escapeHtml(String(item.score||'')) +' (недостаточно уверен)</div>';
                } else {
                    html += '<div style="font-size:11px;color:#9ca3af;margin-top:2px;">Нет совпадения в каталоге Onliner</div>';
                }
                html += '</div>';
            });
            html += '</div>';
        }

        html += '</div>';
        host.innerHTML = html;
    }
    function stopAutoPoll(){
        if(autoPollTimer){
            clearInterval(autoPollTimer);
            autoPollTimer = null;
        }
    }
    function stopAutoVisual(){
        if(autoVisualTimer){
            clearInterval(autoVisualTimer);
            autoVisualTimer = null;
        }
    }
    function startAutoVisual(){
        stopAutoVisual();
        autoVisualPercent = 1;
        if(autoBtn){
            autoBtn.textContent = 'Подбираю ' + autoVisualPercent + '%';
        }
        autoVisualTimer = setInterval(function(){
            if(autoVisualPercent < 95){
                autoVisualPercent = Math.min(95, autoVisualPercent + (autoVisualPercent < 20 ? 3 : 2));
                if(autoBtn){
                    autoBtn.textContent = 'Подбираю ' + autoVisualPercent + '%';
                }
            }
        }, 1200);
    }
    function pollAutoStatus(){
        fetch('/api/autofill-tgpc-pc-status?_ts=' + Date.now(), {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(st){
            if(!st){ throw new Error('no_status'); }
            var percent = Number(st.percent || 0);
            var total = Number(st.total || 0);
            var done = Number(st.done || 0);
            var applied = Number(st.applied || 0);
            var skipped = Number(st.skipped || 0);
            var items = Array.isArray(st.items) ? st.items : [];
            if(percent > autoVisualPercent){
                autoVisualPercent = percent;
            }
            // progress bar
            var progWrap = document.getElementById('autofill-tgpc-progress-wrap');
            var progBar  = document.getElementById('autofill-tgpc-progress-bar');
            if(progWrap && progBar){
                if(st.running || st.finished_at){
                    progWrap.style.display = 'block';
                    progBar.style.width = Math.max(percent, autoVisualPercent) + '%';
                }
                if(!st.running && st.finished_at){
                    progBar.style.background = applied > 0 ? 'linear-gradient(90deg,#4ade80,#16a34a)' : '#d1d5db';
                }
            }
            if(autoBtn){
                autoBtn.textContent = st.running ? ('Подбираю ' + Math.max(percent, autoVisualPercent) + '%') : (autoRunLabel + (st.finished_at ? (' ' + percent + '%') : ''));
                if(!st.running && !st.finished_at){
                    autoBtn.textContent = autoRunLabel;
                }
            }
            if(autoTestBtn){
                autoTestBtn.disabled = !!st.running;
            }
            if(autoNote){
                if(st.running){
                    autoNote.textContent = 'Обработано ' + done + ' из ' + total + ' TGPC ПЭВМ. Подставлено: ' + applied + '.';
                } else if(st.message && String(st.message).toLowerCase().indexOf('ошибка') === 0){
                    autoNote.textContent = st.message;
                } else if(st.finished_at){
                    autoNote.textContent = 'Автоподбор завершён: подставлено ' + applied + ' из ' + total + ' TGPC ПЭВМ (' + percent + '%). Пропущено: ' + skipped + '.';
                } else if(st.message){
                    autoNote.textContent = st.message;
                }
            }
            renderAutoReport(items, st);
            if(st.running){
                updateBusyOverlay('Автоподбор TGPC ПЭВМ', 'Обработано ' + done + ' из ' + total + '. Подставлено: ' + applied + '.');
                return;
            }
            stopAutoPoll();
            stopAutoVisual();
            if(autoBtn){ autoBtn.disabled = false; }
            hideBusyOverlay();
            if(st.finished_at){
                closeNoIdInlinePicker(false);
                if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                    tblMain.ajax.reload(null, false);
                } else {
                    fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(resp){
                        mainTableRows = (resp && resp.data) ? resp.data : [];
                        updateWithoutIdCount(mainTableRows);
                        renderMainTableFallback();
                    });
                }
                runPreExportQualityCheck();
            }
        }).catch(function(){
            stopAutoPoll();
            stopAutoVisual();
            if(autoBtn){
                autoBtn.disabled = false;
                autoBtn.textContent = autoRunLabel;
            }
            if(autoTestBtn){
                autoTestBtn.disabled = false;
            }
            if(autoNote){
                autoNote.textContent = 'Не удалось получить прогресс автоподбора TGPC ПЭВМ.';
            }
            renderAutoReport([]);
            hideBusyOverlay();
        });
    }
    function startAutoFill(limitValue, labelText){
        if(autoBtn && autoBtn.disabled){ return; }
        autoRunLabel = labelText || 'Авто TGPC ПЭВМ';
        if(autoBtn){
            autoBtn.disabled = true;
            autoBtn.textContent = 'Подбираю 1%';
        }
        if(autoTestBtn){
            autoTestBtn.disabled = true;
        }
        if(autoNote){
            autoNote.textContent = 'Запустили подбор TGPC ПЭВМ. Сейчас начнём проверку первых позиций...';
        }
        renderAutoReport([], null);
        var progWrap2 = document.getElementById('autofill-tgpc-progress-wrap');
        var progBar2  = document.getElementById('autofill-tgpc-progress-bar');
        var chips2    = document.getElementById('autofill-tgpc-chips');
        if(progWrap2){ progWrap2.style.display = 'block'; }
        if(progBar2){ progBar2.style.width = '2%'; progBar2.style.background = 'linear-gradient(90deg,#f59e0b,#d56e0c)'; }
        if(chips2){ chips2.innerHTML = ''; chips2.style.display = 'none'; }
        startAutoVisual();
        showBusyOverlay('Автоподбор TGPC ПЭВМ', 'Ищем точные совпадения Onliner и сохраняем найденные ID...');
        fetch('/api/autofill-tgpc-pc-ids', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(limitValue ? {limit: limitValue} : {})
        }).then(function(r){ return r.json(); }).then(function(d){
            if(!d || (d.status !== 'started' && d.status !== 'already_running')){
                throw new Error((d && d.message) || 'autofill_failed');
            }
            stopAutoPoll();
            autoPollTimer = setInterval(pollAutoStatus, 1200);
            pollAutoStatus();
        }).catch(function(){
            if(autoNote){
                autoNote.textContent = 'Не удалось завершить автоподбор TGPC ПЭВМ.';
            }
            stopAutoVisual();
            if(autoBtn){
                autoBtn.disabled = false;
                autoBtn.textContent = autoRunLabel;
            }
            if(autoTestBtn){
                autoTestBtn.disabled = false;
            }
            hideBusyOverlay();
        });
    }
    if(!btn){ return; }
    btn.addEventListener('click', function(){
        showOnlyNoIdRows = !showOnlyNoIdRows;
        if(!showOnlyNoIdRows){
            closeNoIdInlinePicker(false);
        }
        btn.textContent = showOnlyNoIdRows ? 'Показать все' : 'Показать';
        if(tblMain){
            if(typeof tblMain.draw === 'function'){
                tblMain.draw(false);
            } else if(tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                tblMain.ajax.reload(null, false);
            }
        } else {
            renderMainTableFallback();
        }
    });
    if(autoBtn){
        autoBtn.addEventListener('click', function(){
            startAutoFill(0, 'Авто TGPC ПЭВМ');
        });
    }
    if(autoTestBtn){
        autoTestBtn.addEventListener('click', function(){
            startAutoFill(autoTestLimit, 'Тест ' + autoTestLimit);
        });
    }

    // ── IVEN Bridge autofill ──────────────────────────────────────────────────
    (function(){
        var ivenBtn       = document.getElementById('autofill-iven-btn');
        var b2bBtn        = document.getElementById('autofill-b2b-btn');
        var clearNonPcBtn = document.getElementById('clear-nonpc-ids-btn');
        var cpuReviewBtn = document.getElementById('cpu-review-btn');
        var ivenReportBtn = document.getElementById('autofill-iven-report-btn');
        var ivenWrap      = document.getElementById('autofill-iven-progress-wrap');
        var ivenBar       = document.getElementById('autofill-iven-progress-bar');
        var ivenMsg       = document.getElementById('autofill-iven-msg');
        var ivenTimer     = null;
        var lastStatus    = null;

        function scoreColor(sc){
            if(sc >= 0.95) return '#16a34a';
            if(sc >= 0.85) return '#2563eb';
            if(sc >= 0.75) return '#d97706';
            return '#dc2626';
        }

        function scoreBg(sc){
            if(sc >= 0.95) return '#f0fdf4';
            if(sc >= 0.85) return '#eff6ff';
            if(sc >= 0.75) return '#fffbeb';
            return '#fff1f2';
        }

        // Track confirmed/rejected rows: name → state ('confirmed'|'rejected')
        var ivenRowStates = {};

        function ivenConfirmRow(tr, m){
            // Save to manual bindings via existing batch endpoint
            var items = [{name: m.name, onliner_id: m.id, url: m.url || '', row_idx: m.row_idx}];
            fetch('/api/manual-id-confirm-batch', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({source:'iven_report', items: items})
            }).then(function(r){ return r.json(); }).then(function(d){
                if(d.status === 'ok'){
                    ivenRowStates[m.name] = 'confirmed';
                    tr.style.background = '#f0fdf4';
                    var actCell = tr.querySelector('.iven-act-cell');
                    if(actCell) actCell.innerHTML = '<span style="color:#16a34a;font-weight:600;font-size:12px;">✓ Сохранено</span>';
                }
            }).catch(function(){});
        }

        function ivenRejectRow(tr, m){
            fetch('/api/iven-reject-match', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({name: m.name, row_idx: m.row_idx})
            }).then(function(r){ return r.json(); }).then(function(d){
                if(d.status === 'ok'){
                    ivenRowStates[m.name] = 'rejected';
                    tr.style.background = '#fef2f2';
                    tr.style.opacity = '0.55';
                    var actCell = tr.querySelector('.iven-act-cell');
                    if(actCell) actCell.innerHTML = '<span style="color:#dc2626;font-weight:600;font-size:12px;">✗ Удалено</span>';
                    // Update no-id counter
                    var wiel = document.getElementById('without-id-count');
                    if(wiel && !isNaN(parseInt(wiel.textContent))){
                        wiel.textContent = parseInt(wiel.textContent) + 1;
                    }
                }
            }).catch(function(){});
        }

        function ivenSaveManualId(name, rowIdx, rawId, btn, input, caption){
            var finalId = String(rawId || '').trim().replace(/\.0$/, '');
            if(!/^\d+$/.test(finalId)){
                if(caption) caption.textContent = 'Нужен числовой Onliner ID';
                if(input) input.focus();
                return;
            }
            if(btn) btn.disabled = true;
            if(caption) caption.textContent = 'Сохраняю...';
            fetch('/api/manual-id-confirm-batch', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({
                    source:'iven_manual_input',
                    items:[{name:name, onliner_id:finalId, row_idx: rowIdx}]
                })
            }).then(function(r){ return r.json(); }).then(function(d){
                if(d && d.status === 'ok'){
                    ivenRowStates[(name||'') + '_' + finalId] = 'confirmed';
                    if(caption) caption.innerHTML = '<span style="color:#16a34a;font-weight:700;">✓ Сохранено в ручные привязки</span>';
                    if(input) input.value = finalId;
                } else {
                    if(caption) caption.textContent = (d && d.message) || 'Не удалось сохранить';
                }
            }).catch(function(){
                if(caption) caption.textContent = 'Ошибка сохранения';
            }).finally(function(){
                if(btn) btn.disabled = false;
            });
        }

        function ivenSourceBadge(source){
            var src = String(source || '').trim();
            if(!src) return '';
            var isExact = (src === 'db_exact' || src === 'b2b_exact');
            var isB2B = src.indexOf('b2b') === 0;
            var bg = isExact ? '#dcfce7' : (isB2B ? '#dbeafe' : '#fef3c7');
            var col = isExact ? '#166534' : (isB2B ? '#1d4ed8' : '#92400e');
            var label = src;
            return '<span style="display:inline-block;margin-top:4px;padding:2px 6px;border-radius:999px;background:' + bg + ';color:' + col + ';font-size:10px;font-weight:700;">' + label + '</span>';
        }

        function renderIvenModal(st){
            var modal  = document.getElementById('iven-report-modal');
            var tbody  = document.getElementById('iven-modal-tbody');
            var showNM = document.getElementById('iven-modal-show-nomatch');
            if(!modal || !tbody) return;

            var matches = (st && st.matches)  || [];
            var noMatch = (st && st.no_match) || [];
            var showNoMatch = showNM && showNM.checked;

            // Update summary stats
            var el = function(id){ return document.getElementById(id); };
            if(el('iven-modal-stat-matched')) el('iven-modal-stat-matched').textContent = matches.length;
            if(el('iven-modal-stat-nomatch')) el('iven-modal-stat-nomatch').textContent = noMatch.length;
            if(el('iven-modal-subtitle'))
                el('iven-modal-subtitle').textContent =
                    'Обработано: ' + (matches.length + noMatch.length) + ' товаров N-Tech';
            if(el('iven-modal-stat-avgsc')){
                var avgSc = matches.length > 0
                    ? (matches.reduce(function(s,m){ return s + (parseFloat(m.score)||0); }, 0) / matches.length).toFixed(2)
                    : '—';
                el('iven-modal-stat-avgsc').textContent = avgSc;
            }

            tbody.innerHTML = '';
            matches.forEach(function(m, i){
                var tr = document.createElement('tr');
                var state = ivenRowStates[m.name];
                var bg = state === 'confirmed' ? '#f0fdf4'
                       : state === 'rejected'  ? '#fef2f2'
                       : (i % 2 === 0 ? '#fff' : '#f8fafc');
                tr.style.cssText = 'background:' + bg + ';border-bottom:1px solid #f1f5f9;' +
                    (state === 'rejected' ? 'opacity:0.55;' : '');

                var sc = parseFloat(m.score) || 0;
                var scBadge = '<span style="display:inline-block;padding:2px 7px;border-radius:20px;font-weight:700;font-size:12px;background:' +
                    scoreBg(sc) + ';color:' + scoreColor(sc) + ';">' + (m.score || '—') + '</span>';
                var idCell = m.id
                    ? '<a href="https://catalog.onliner.by/p/' + m.id + '" target="_blank" style="color:#2563eb;text-decoration:none;font-weight:600;font-size:12px;">' + m.id + '</a>'
                    : '—';
                var matchSourceHtml = ivenSourceBadge(m.source);

                var actHtml;
                if(state === 'confirmed'){
                    actHtml = '<span style="color:#16a34a;font-weight:600;font-size:12px;">✓ Сохранено</span>';
                } else if(state === 'rejected'){
                    actHtml = '<span style="color:#dc2626;font-weight:600;font-size:12px;">✗ Удалено</span>';
                } else {
                    actHtml = '<button class="iven-confirm-btn" style="padding:3px 8px;border:1px solid #16a34a;border-radius:5px;background:#f0fdf4;color:#16a34a;font-size:11px;font-weight:600;cursor:pointer;margin-right:4px;" title="Подтвердить — сохранить в ручные привязки">✓</button>' +
                              '<button class="iven-reject-btn"  style="padding:3px 8px;border:1px solid #fca5a5;border-radius:5px;background:#fef2f2;color:#dc2626;font-size:11px;font-weight:600;cursor:pointer;" title="Неверно — удалить ID">✗</button>';
                }

                tr.innerHTML =
                    '<td style="padding:8px 14px;color:#1f2937;line-height:1.4;font-size:12px;">' + (m.name || '') + '</td>' +
                    '<td style="padding:8px 14px;color:#374151;line-height:1.4;font-size:12px;">' + (m.matched_name || '') + matchSourceHtml + '</td>' +
                    '<td style="padding:8px;text-align:center;">' + scBadge + '</td>' +
                    '<td style="padding:8px;text-align:center;">' + idCell + '</td>' +
                    '<td class="iven-act-cell" style="padding:6px 8px;text-align:center;white-space:nowrap;">' + actHtml + '</td>';

                // Wire up buttons after DOM insertion
                tbody.appendChild(tr);
                var confirmBtn = tr.querySelector('.iven-confirm-btn');
                var rejectBtn  = tr.querySelector('.iven-reject-btn');
                if(confirmBtn) confirmBtn.addEventListener('click', (function(row, match){ return function(){ ivenConfirmRow(row, match); }; })(tr, m));
                if(rejectBtn)  rejectBtn.addEventListener('click',  (function(row, match){ return function(){ ivenRejectRow(row, match); }; })(tr, m));
            });

            // Count items with and without candidates
            var withCands   = noMatch.filter(function(m){ return m.candidates && m.candidates.length > 0; });
            var withoutCands= noMatch.filter(function(m){ return !m.candidates || m.candidates.length === 0; });

            if(withCands.length > 0){
                var sepC = document.createElement('tr');
                sepC.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:700;border-top:2px solid #bfdbfe;">Ручная модерация — автоподстановка запрещена для score &lt; 1 (' + withCands.length + '):</td>';
                tbody.appendChild(sepC);
                withCands.forEach(function(m, i){
                    var tr = document.createElement('tr');
                    tr.style.cssText = 'background:' + (i%2===0?'#fff':'#f0f9ff') + ';border-bottom:1px solid #e0f2fe;vertical-align:top;';
                    var bestSourceHtml = m.best_source
                        ? '<div style="margin-bottom:6px;font-size:11px;color:#475569;">Лучший матч из базы: ' + ivenSourceBadge(m.best_source) + '</div>'
                        : '';
                    var candsHtml = '<div style="display:flex;flex-direction:column;gap:4px;">' + bestSourceHtml;
                    (m.candidates || []).forEach(function(c){
                        var scCol = c.score >= 0.75 ? '#16a34a' : c.score >= 0.55 ? '#d97706' : '#9ca3af';
                        var keyState = (m.name||'') + '_' + c.id;
                        var savedState = ivenRowStates[keyState];
                        var candSourceHtml = ivenSourceBadge(c.source || (c.id === m.best_id ? m.best_source : ''));
                        if(savedState === 'confirmed'){
                            candsHtml += '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;">' +
                                '<span style="color:#16a34a;font-weight:700;font-size:11px;">✓ Сохранено</span>' +
                                '<span style="font-size:11px;color:#374151;">' + c.name + '</span>' +
                                candSourceHtml +
                                '<a href="https://catalog.onliner.by/p/' + c.id + '" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;">' + c.id + '</a>' +
                                '</div>';
                        } else {
                            candsHtml += '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;">' +
                                '<button class="iven-manual-pick" data-name="' + (m.name||'').replace(/"/g,'&quot;') + '" data-row="' + (m.row_idx||'') + '" data-id="' + c.id + '" data-cname="' + c.name.replace(/"/g,'&quot;') + '"' +
                                ' style="padding:2px 8px;border:1px solid #3b82f6;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;">Выбрать</button>' +
                                '<span style="color:' + scCol + ';font-weight:700;font-size:11px;min-width:36px;">' + c.score + '</span>' +
                                '<span style="font-size:11px;color:#374151;">' + c.name + '</span>' +
                                candSourceHtml +
                                '<a href="https://catalog.onliner.by/p/' + c.id + '" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;text-decoration:none;">' + c.id + '</a>' +
                                '</div>';
                        }
                    });
                    var manualRowId = 'iven-manual-id-' + (m.row_idx || i);
                    var manualBtnId = 'iven-manual-btn-' + (m.row_idx || i);
                    var manualNoteId = 'iven-manual-note-' + (m.row_idx || i);
                    candsHtml += '<div style="display:flex;align-items:center;gap:6px;padding-top:8px;margin-top:6px;border-top:1px dashed #bfdbfe;flex-wrap:wrap;">' +
                        '<input id="' + manualRowId + '" type="text" inputmode="numeric" placeholder="Вставить Onliner ID вручную" ' +
                        'style="width:210px;padding:4px 8px;border:1px solid #93c5fd;border-radius:4px;font-size:11px;">' +
                        '<button id="' + manualBtnId + '" type="button" style="padding:3px 8px;border:1px solid #2563eb;border-radius:4px;background:#2563eb;color:#fff;font-size:11px;font-weight:600;cursor:pointer;">Сохранить ID</button>' +
                        '<span id="' + manualNoteId + '" style="font-size:11px;color:#64748b;">Сохранится в вечный кеш</span>' +
                        '</div>';
                    candsHtml += '</div>';
                    tr.innerHTML =
                        '<td colspan="2" style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:280px;">' + (m.name || '') + '</td>' +
                        '<td colspan="3" style="padding:7px 14px;">' + candsHtml + '</td>';
                    tbody.appendChild(tr);
                    // Wire pick buttons
                    tr.querySelectorAll('.iven-manual-pick').forEach(function(btn){
                        btn.addEventListener('click', function(){
                            var payload = [{name: btn.dataset.name, onliner_id: btn.dataset.id,
                                            url: '', row_idx: btn.dataset.row ? parseInt(btn.dataset.row) : null}];
                            fetch('/api/manual-id-confirm-batch', {
                                method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify({source:'iven_manual_pick', items: payload})
                            }).then(function(r){ return r.json(); }).then(function(){
                                ivenRowStates[(btn.dataset.name||'') + '_' + btn.dataset.id] = 'confirmed';
                                btn.closest('div').innerHTML = '<span style="color:#16a34a;font-weight:700;font-size:11px;">✓ Сохранено</span>' +
                                    '<span style="font-size:11px;color:#374151;margin-left:6px;">' + btn.dataset.cname + '</span>' +
                                    '<a href="https://catalog.onliner.by/p/' + btn.dataset.id + '" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;margin-left:6px;">' + btn.dataset.id + '</a>';
                            });
                        });
                    });
                    var manualInput = document.getElementById(manualRowId);
                    var manualBtn = document.getElementById(manualBtnId);
                    var manualNote = document.getElementById(manualNoteId);
                    if(manualBtn){
                        manualBtn.addEventListener('click', function(){
                            ivenSaveManualId(m.name || '', m.row_idx, manualInput ? manualInput.value : '', manualBtn, manualInput, manualNote);
                        });
                    }
                });
            }

            if(showNoMatch && withoutCands.length > 0){
                var sep = document.createElement('tr');
                sep.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fef9c3;color:#92400e;font-size:12px;font-weight:700;border-top:2px solid #fde68a;">Без кандидатов из базы — можно вставить ID вручную (' + withoutCands.length + '):</td>';
                tbody.appendChild(sep);
                withoutCands.forEach(function(m, i){
                    var tr = document.createElement('tr');
                    tr.style.cssText = 'background:' + (i%2===0?'#fff':'#fafafa') + ';border-bottom:1px solid #f5f5f5;';
                    var manualRowId = 'iven-nomatch-id-' + (m.row_idx || i);
                    var manualBtnId = 'iven-nomatch-btn-' + (m.row_idx || i);
                    var manualNoteId = 'iven-nomatch-note-' + (m.row_idx || i);
                    tr.innerHTML =
                        '<td colspan="2" style="padding:7px 14px;color:#6b7280;font-size:12px;">' + (m.name || '') + '</td>' +
                        '<td style="padding:7px;text-align:center;color:#9ca3af;font-size:12px;">—</td>' +
                        '<td style="padding:7px;text-align:center;color:#9ca3af;font-size:12px;">—</td>' +
                        '<td style="padding:7px;">' +
                            '<div style="display:flex;flex-direction:column;gap:6px;align-items:flex-start;">' +
                                '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
                                    '<input id="' + manualRowId + '" type="text" inputmode="numeric" placeholder="Onliner ID вручную" style="width:170px;padding:4px 8px;border:1px solid #d6d3d1;border-radius:4px;font-size:11px;">' +
                                    '<button id="' + manualBtnId + '" type="button" style="padding:3px 8px;border:1px solid #a16207;border-radius:4px;background:#f59e0b;color:#fff;font-size:11px;font-weight:600;cursor:pointer;">Сохранить ID</button>' +
                                '</div>' +
                                '<span id="' + manualNoteId + '" style="font-size:11px;color:#78716c;">Сохранится в вечный кеш</span>' +
                            '</div>' +
                        '</td>';
                    tbody.appendChild(tr);
                    var manualInput = document.getElementById(manualRowId);
                    var manualBtn = document.getElementById(manualBtnId);
                    var manualNote = document.getElementById(manualNoteId);
                    if(manualBtn){
                        manualBtn.addEventListener('click', function(){
                            ivenSaveManualId(m.name || '', m.row_idx, manualInput ? manualInput.value : '', manualBtn, manualInput, manualNote);
                        });
                    }
                });
            }

            modal.style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        function closeIvenModal(){
            var modal = document.getElementById('iven-report-modal');
            if(modal) modal.style.display = 'none';
            document.body.style.overflow = '';
        }

        function clearNonPcIdsForRematch(){
            if(!window.confirm('Очистить все OnlinerID у товаров поставщика N-Tech, кроме ПЭВМ? После этого можно заново нажать "Найти в базе".')){
                return;
            }
            if(clearNonPcBtn){ clearNonPcBtn.disabled = true; clearNonPcBtn.textContent = 'Очищаю N-Tech...'; }
            if(ivenMsg){ ivenMsg.textContent = 'Очищаю ID у N-Tech товаров кроме ПЭВМ...'; ivenMsg.style.color = '#dc2626'; }
            fetch('/api/clear-all-nonpc-onliner-ids', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'clear_nonpc_failed');
                }
                if(ivenReportBtn){ ivenReportBtn.style.display = 'none'; }
                if(ivenWrap){ ivenWrap.style.display = 'none'; }
                if(ivenBar){ ivenBar.style.width = '0%'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Очищено ID: ' + String(d.cleared || 0));
                    ivenMsg.style.color = '#16a34a';
                }
                fetch('/api/stats?_ts=' + Date.now(), {cache:'no-store'})
                .then(function(r){ return r.json(); })
                .then(function(s){
                    var withoutIdEl = document.getElementById('without-id-count');
                    if(withoutIdEl && s && s.without_id !== undefined){
                        withoutIdEl.textContent = s.without_id;
                    }
                    if(typeof reloadMainTable === 'function'){
                        reloadMainTable();
                    }
                }).catch(function(){});
            }).catch(function(err){
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка очистки: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                if(clearNonPcBtn){ clearNonPcBtn.disabled = false; clearNonPcBtn.textContent = 'Очистить ID N-Tech кроме ПЭВМ'; }
            });
        }

        function startCpuReviewQueue(){
            var cpuBtn = document.getElementById('cpu-review-btn');
            if(cpuBtn){ cpuBtn.disabled = true; cpuBtn.textContent = 'Собираю CPU...'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу процессоры N-Tech по производителю и модели...'; ivenMsg.style.color = '#7c3aed'; }
            showBusyOverlay('Процессоры N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/cpu-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'cpu_review_failed');
                }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Процессоров добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = '#16a34a';
                }
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ede9fe'; }
            }).catch(function(err){
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка CPU-подбора: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(cpuBtn){ cpuBtn.disabled = false; cpuBtn.textContent = 'Процессоры N-Tech'; }
            });
        }

        function startIvenBridge(runMode){
            var useB2B = runMode === 'b2b';
            var triggerBtn = useB2B ? b2bBtn : ivenBtn;
            if(triggerBtn && triggerBtn.disabled) return;
            if(ivenBtn){ ivenBtn.disabled = true; }
            if(b2bBtn){ b2bBtn.disabled = true; }
            if(clearNonPcBtn){ clearNonPcBtn.disabled = true; }
            if(ivenBtn){ ivenBtn.textContent = useB2B ? 'Найти в базе' : 'Запускаю...'; }
            if(b2bBtn){ b2bBtn.textContent = useB2B ? 'Запускаю...' : 'B2B без кеша'; }
            if(ivenReportBtn) ivenReportBtn.style.display = 'none';
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '2%'; }
            if(ivenMsg){
                ivenMsg.textContent = useB2B ? 'Готовлю B2B-прогон без вечного кеша...' : 'Готовлю IVEN-бридж...';
                ivenMsg.style.color = '#1d4ed8';
            }
            showBusyOverlay(
                useB2B ? 'B2B без кеша' : 'Поиск в базе',
                useB2B
                    ? 'Сравниваем товары без участия вечного кеша и пытаемся добрать совпадения через B2B...'
                    : 'Сопоставляем N-Tech товары с локальной базой по модели и артикулу...'
            );
            fetch('/api/autofill-iven-bridge', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify(useB2B ? {ignore_manual_cache:true, prefer_b2b:true} : {})
            })
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || (d.status !== 'started' && d.status !== 'already_running')){
                    throw new Error((d && d.message) || 'iven_bridge_failed');
                }
                clearInterval(ivenTimer);
                ivenTimer = setInterval(pollIvenStatus, 1000);
                pollIvenStatus();
            }).catch(function(e){
                if(ivenBtn){ ivenBtn.disabled = false; ivenBtn.textContent = 'Найти в базе'; }
                if(b2bBtn){ b2bBtn.disabled = false; b2bBtn.textContent = 'B2B без кеша'; }
                if(clearNonPcBtn){ clearNonPcBtn.disabled = false; }
                if(ivenMsg){ ivenMsg.textContent = 'Ошибка: ' + (e.message || e); ivenMsg.style.color = '#dc2626'; }
                hideBusyOverlay();
            });
        }

        // Close buttons
        var mc1 = document.getElementById('iven-report-modal-close');
        var mc2 = document.getElementById('iven-report-modal-close2');
        if(mc1) mc1.addEventListener('click', closeIvenModal);
        if(mc2) mc2.addEventListener('click', closeIvenModal);
        // Click on backdrop closes
        var ivenModalEl = document.getElementById('iven-report-modal');
        if(ivenModalEl){
            ivenModalEl.addEventListener('click', function(e){
                if(e.target === ivenModalEl) closeIvenModal();
            });
        }
        // Escape key
        document.addEventListener('keydown', function(e){
            if(e.key === 'Escape') closeIvenModal();
        });
        // Show-no-match checkbox
        var ivenModalNoMatch = document.getElementById('iven-modal-show-nomatch');
        if(ivenModalNoMatch){
            ivenModalNoMatch.addEventListener('change', function(){ renderIvenModal(lastStatus); });
        }

        function pollIvenStatus(){
            fetch('/api/autofill-iven-status?_ts=' + Date.now(), {cache:'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(st){
                lastStatus = st;
                var pct = parseInt(st.percent || 0);
                if(ivenBar){ ivenBar.style.width = Math.max(2, pct) + '%'; }
                if(ivenMsg){ ivenMsg.textContent = st.message || ''; }
                if(!st.running){
                    clearInterval(ivenTimer); ivenTimer = null;
                    if(ivenBtn){ ivenBtn.disabled = false; ivenBtn.textContent = 'Найти в базе'; }
                    if(b2bBtn){ b2bBtn.disabled = false; b2bBtn.textContent = 'B2B без кеша'; }
                    if(clearNonPcBtn){ clearNonPcBtn.disabled = false; }
                    hideBusyOverlay();
                    if(st.applied > 0){
                        if(ivenMsg){ ivenMsg.style.color = '#16a34a'; }
                        setTimeout(function(){ if(typeof reloadMainTable === 'function') reloadMainTable(); }, 600);
                    }
                    // Показываем кнопку "Отчёт" если есть данные
                    var hasData = (st.matches && st.matches.length > 0) || (st.no_match && st.no_match.length > 0);
                    if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                    var withoutIdEl = document.getElementById('without-id-count');
                    if(withoutIdEl){ fetch('/api/stats?_ts='+Date.now(),{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){ if(s && s.without_id !== undefined) withoutIdEl.textContent = s.without_id; }).catch(function(){}); }
                }
            }).catch(function(){});
        }

        if(ivenBtn){
            ivenBtn.addEventListener('click', function(){
                startIvenBridge('default');
            });
        }

        if(b2bBtn){
            b2bBtn.addEventListener('click', function(){
                startIvenBridge('b2b');
            });
        }

        if(clearNonPcBtn){
            clearNonPcBtn.addEventListener('click', clearNonPcIdsForRematch);
        }
        if(cpuReviewBtn){
            cpuReviewBtn.addEventListener('click', startCpuReviewQueue);
        }

        if(ivenReportBtn){
            ivenReportBtn.addEventListener('click', function(){
                renderIvenModal(lastStatus);
            });
        }

        // Загружаем последний статус при открытии страницы
        fetch('/api/autofill-iven-status?_ts=' + Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            lastStatus = st;
            var hasData = (st.matches && st.matches.length > 0) || (st.no_match && st.no_match.length > 0);
            if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
            if(st.message && ivenMsg){ ivenMsg.textContent = st.message; }
            if(st.percent && ivenBar){ ivenBar.style.width = st.percent + '%'; ivenWrap.style.display = 'block'; }
        }).catch(function(){});
    })();
    // ─────────────────────────────────────────────────────────────────────────

    var tableEl = document.getElementById('tbl-main');
    if(tableEl){
        tableEl.addEventListener('click', handleNoIdTableClick);
    }
}

function initOnlinerDbWidget(){
    var countEl  = document.getElementById('db-products-count');
    var detailEl = document.getElementById('db-stats-detail');
    var noteEl   = document.getElementById('db-stats-note');
    var rebuildBtn = document.getElementById('db-rebuild-btn');

    function loadDbStats(){
        fetch('/api/onliner-db-stats?_ts=' + Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(s){
            if(countEl) countEl.textContent = (s.total_products || 0).toLocaleString();
            var lines = [];
            lines.push((s.total_names || 0).toLocaleString() + ' вариантов названий');
            var src = s.by_source || {};
            Object.keys(src).slice(0,4).forEach(function(k){
                lines.push(k + ': ' + src[k].toLocaleString());
            });
            if(detailEl) detailEl.innerHTML = lines.join('<br>');
        }).catch(function(){ if(countEl) countEl.textContent = '?'; });
    }

    if(rebuildBtn){
        rebuildBtn.addEventListener('click', function(){
            rebuildBtn.disabled = true;
            rebuildBtn.textContent = 'Обновляю...';
            if(noteEl) noteEl.textContent = 'Пополняю БД из текущего прайса...';
            fetch('/api/onliner-db-rebuild', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                rebuildBtn.disabled = false;
                rebuildBtn.textContent = 'Обновить БД';
                if(noteEl) noteEl.textContent = d.status === 'ok'
                    ? 'Добавлено: ' + (d.products||0) + ' товаров, ' + (d.names||0) + ' имён.'
                    : 'Ошибка: ' + (d.message || '');
                loadDbStats();
            }).catch(function(){
                rebuildBtn.disabled = false;
                rebuildBtn.textContent = 'Обновить БД';
            });
        });
    }

    // ── Import full Onliner catalog (CSV/XLSX) ──────────────────────────
    var importBtn  = document.getElementById('db-import-catalog-btn');
    var importFile = document.getElementById('db-import-catalog-file');
    var importWrap = document.getElementById('db-import-progress-wrap');
    var importBar  = document.getElementById('db-import-progress-bar');
    var importMsg  = document.getElementById('db-import-msg');
    var importPollTimer = null;

    function stopImportPoll(){ if(importPollTimer){ clearInterval(importPollTimer); importPollTimer = null; } }

    function pollImportStatus(){
        fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var pct = parseInt(st.percent || 0);
            if(importBar)  importBar.style.width  = Math.max(2, pct) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            if(importWrap) importWrap.style.display = 'block';
            if(!st.running && st.finished_at){
                stopImportPoll();
                if(importBtn){ importBtn.disabled = false; importBtn.textContent = '📥 Загрузить каталог'; }
                importBar && (importBar.style.background = st.message && st.message.indexOf('Ошибка') === 0
                    ? 'linear-gradient(90deg,#f87171,#dc2626)'
                    : 'linear-gradient(90deg,#0891b2,#0e7490)');
                loadDbStats();
            }
        }).catch(function(){});
    }

    if(importBtn && importFile){
        importBtn.addEventListener('click', function(){
            importFile.value = '';
            importFile.click();
        });
        importFile.addEventListener('change', function(){
            var file = importFile.files[0];
            if(!file) return;
            var sizeMb = (file.size / 1024 / 1024).toFixed(1);
            if(file.size > 120 * 1024 * 1024){
                alert('Файл слишком большой (' + sizeMb + ' МБ). Максимум 120 МБ.');
                return;
            }
            importBtn.disabled = true;
            importBtn.textContent = 'Загружаю...';
            if(importWrap) importWrap.style.display = 'block';
            if(importBar)  importBar.style.width = '2%';
            if(importMsg)  importMsg.textContent  = 'Отправляю файл (' + sizeMb + ' МБ)...';

            var fd = new FormData();
            fd.append('file', file);
            fetch('/api/onliner-db-import-csv', {method:'POST', body: fd})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(d.status !== 'started' && d.status !== 'already_running'){
                    throw new Error(d.message || 'start_failed');
                }
                importBtn.textContent = 'Импортирую...';
                stopImportPoll();
                importPollTimer = setInterval(pollImportStatus, 1000);
                pollImportStatus();
            }).catch(function(e){
                importBtn.disabled = false;
                importBtn.textContent = '📥 Загрузить каталог';
                if(importMsg) importMsg.textContent = 'Ошибка: ' + (e.message || e);
            });
        });
    }

    // ── Google Sheets direct import ─────────────────────────────────────
    var gsheetIdInput    = document.getElementById('db-gsheet-id');
    var gsheetSheetInput = document.getElementById('db-gsheet-sheet');
    var gsheetBtn        = document.getElementById('db-gsheet-btn');

    // Pre-fill saved values
    if(gsheetIdInput && localStorage.getItem('db_gsheet_id'))
        gsheetIdInput.value = localStorage.getItem('db_gsheet_id');
    if(gsheetSheetInput && localStorage.getItem('db_gsheet_sheet'))
        gsheetSheetInput.value = localStorage.getItem('db_gsheet_sheet');

    if(gsheetBtn){
        gsheetBtn.addEventListener('click', function(){
            var sid   = (gsheetIdInput   ? gsheetIdInput.value   : '').trim();
            var sname = (gsheetSheetInput ? gsheetSheetInput.value : '').trim() || 'All_Catalog';
            if(!sid){ alert('Введи ID Google таблицы'); return; }
            localStorage.setItem('db_gsheet_id',    sid);
            localStorage.setItem('db_gsheet_sheet', sname);

            gsheetBtn.disabled = true;
            gsheetBtn.textContent = 'Скачиваю...';
            if(importWrap) importWrap.style.display = 'block';
            if(importBar)  importBar.style.width = '2%';
            if(importMsg)  importMsg.textContent  = 'Подключаюсь к Google Sheets…';

            fetch('/api/onliner-db-import-gsheet', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sheet_id: sid, sheet_name: sname})
            })
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(d.status !== 'started' && d.status !== 'already_running'){
                    throw new Error(d.message || 'start_failed');
                }
                gsheetBtn.textContent = 'Импортирую...';
                stopImportPoll();
                importPollTimer = setInterval(pollImportStatus, 1200);
                pollImportStatus();
            }).catch(function(e){
                gsheetBtn.disabled = false;
                gsheetBtn.textContent = '▶ Импорт GSheets';
                if(importMsg) importMsg.textContent = 'Ошибка: ' + (e.message || e);
            });
        });
    }

    // Also re-enable gsheetBtn when import finishes (patch pollImportStatus)
    var _origPollImport = pollImportStatus;
    pollImportStatus = function(){
        fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var pct = parseInt(st.percent || 0);
            if(importBar)  importBar.style.width  = Math.max(2, pct) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            if(importWrap) importWrap.style.display = 'block';
            if(!st.running && st.finished_at){
                stopImportPoll();
                if(importBtn){ importBtn.disabled = false; importBtn.textContent = '📥 Загрузить каталог'; }
                if(gsheetBtn){ gsheetBtn.disabled = false; gsheetBtn.textContent = '▶ Импорт GSheets'; }
                importBar && (importBar.style.background = st.message && st.message.indexOf('Ошибка') === 0
                    ? 'linear-gradient(90deg,#f87171,#dc2626)'
                    : 'linear-gradient(90deg,#0891b2,#0e7490)');
                loadDbStats();
            }
        }).catch(function(){});
    };

    // Resume poll if import was running before page load
    fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(st){
        if(st.running){
            if(importBtn){ importBtn.disabled = true; importBtn.textContent = 'Импортирую...'; }
            if(gsheetBtn){ gsheetBtn.disabled = true; gsheetBtn.textContent = 'Импортирую...'; }
            if(importWrap) importWrap.style.display = 'block';
            if(importBar)  importBar.style.width = Math.max(2, parseInt(st.percent||0)) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            stopImportPoll();
            importPollTimer = setInterval(pollImportStatus, 1200);
        } else if(st.finished_at && st.message){
            if(importWrap) importWrap.style.display = 'block';
            if(importMsg)  importMsg.textContent  = st.message;
            if(importBar)  importBar.style.width  = '100%';
        }
    }).catch(function(){});

    loadDbStats();
}

function initSnapshotFilterUI(){
    function syncSnapshotDetailUI(){
        var wrap = document.getElementById('snapshot-lists');
        if(!wrap){ return; }
        var mode = String(snapshotDetailMode || '').trim();
        wrap.classList.toggle('active', !!mode);
        wrap.querySelectorAll('.snapshot-list').forEach(function(card){
            var kind = String(card.getAttribute('data-kind') || '').trim();
            card.classList.toggle('active', !!mode && kind === mode);
        });
        document.querySelectorAll('.snapshot-mini[data-kind]').forEach(function(card){
            var kind = String(card.getAttribute('data-kind') || '').trim();
            card.classList.toggle('active', !!mode && kind === mode);
        });
    }
    function toggleSnapshotDetail(mode){
        var next = String(mode || '').trim();
        snapshotDetailMode = (snapshotDetailMode === next) ? '' : next;
        syncSnapshotDetailUI();
    }
    function setSnapshotFilter(mode){
        var filters = (window.snapshotDiffData && window.snapshotDiffData.filters) ? window.snapshotDiffData.filters : {};
        snapshotFilterMode = mode || '';
        if(mode === 'new'){
            snapshotFilterNames = Array.isArray(filters.new_names) ? filters.new_names.slice() : [];
        } else if(mode === 'new_without_id'){
            snapshotFilterNames = Array.isArray(filters.new_without_id_names) ? filters.new_without_id_names.slice() : [];
        } else {
            snapshotFilterNames = [];
        }
        showOnlySnapshotRows = !!snapshotFilterNames.length;
        redrawMainTable();
    }
    var btnNew = document.getElementById('show-new-items-btn');
    if(btnNew){
        btnNew.addEventListener('click', function(){ setSnapshotFilter('new'); });
    }
    var btnNewNoId = document.getElementById('show-new-noid-items-btn');
    if(btnNewNoId){
        btnNewNoId.addEventListener('click', function(){ setSnapshotFilter('new_without_id'); });
    }
    var btnClear = document.getElementById('clear-snapshot-filter-btn');
    if(btnClear){
        btnClear.addEventListener('click', function(){ setSnapshotFilter(''); });
    }
    document.querySelectorAll('.snapshot-mini[data-kind]').forEach(function(card){
        card.addEventListener('click', function(){
            toggleSnapshotDetail(card.getAttribute('data-kind'));
        });
    });
    syncSnapshotDetailUI();
}

function getNoIdInlineState(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx >= 0 && noIdInlinePickerState && Number(noIdInlinePickerState.rowIdx) === idx){
        return noIdInlinePickerState;
    }
    return null;
}

function renderNoIdInlinePicker(row){
    var rowIdx = Number(row[8] || -1);
    var state = getNoIdInlineState(rowIdx);
    if(!state){ return ''; }
    var html = '<div class="noid-inline-picker">';
    html += '<div class="noid-inline-top">';
    html += '<div class="noid-inline-note" style="margin-bottom:0;">' + escapeHtml(state.message || 'Ищу точные совпадения по Onliner...') + '</div>';
    html += '<button type="button" class="noid-inline-close" data-close-row-idx="' + rowIdx + '">Скрыть</button>';
    html += '</div>';
    if(state.loading){
        html += '<div class="noid-inline-note">Загрузка кандидатов...</div>';
    } else if(Array.isArray(state.items) && state.items.length){
        html += '<div class="noid-inline-list">';
        state.items.forEach(function(item){
            var candidateId = String((item && item.id) || '').trim();
            var candidateName = String((item && item.name) || '').trim();
            var candidateUrl = String((item && item.url) || '').trim();
            var scoreNum = Number((item && item.score) || 0);
            var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
            var isApplying = !!(state.applyingId && state.applyingId === candidateId);
            html += '<div class="noid-inline-item">';
            html += '<div class="noid-inline-meta">';
            html += '<div class="noid-inline-title">' + highlightCandidateName(state.queryName || '', candidateName || candidateId || 'Кандидат без названия') + '</div>';
            html += renderCandidateBadges(item || {});
            html += '<div class="noid-inline-sub">ID: ' + escapeHtml(candidateId || '—') + (score ? (' · score ' + escapeHtml(score)) : '') + '</div>';
            html += '</div>';
            html += '<div class="noid-inline-actions">';
            if(candidateUrl){
                html += '<a href="' + escapeHtml(candidateUrl) + '" target="_blank" rel="noopener noreferrer" class="noid-inline-open">Открыть</a>';
            }
            html += '<button type="button" class="noid-inline-apply" data-row-idx="' + rowIdx + '" data-oid="' + escapeHtml(candidateId) + '" data-url="' + escapeHtml(candidateUrl) + '"' + (isApplying ? ' disabled' : '') + '>' + (isApplying ? 'Сохраняю...' : 'Подставить ID') + '</button>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
    } else {
        html += '<div class="noid-inline-note">Ничего достаточно точного не нашли. Окно можно скрыть и перейти к следующей строке.</div>';
    }
    html += '</div>';
    return html;
}

function renderMainTableIdCell(oid, row){
    var hasId = !!String(oid || '').trim();
    if(hasId){
        return '<b style="color:#2e7d32">' + escapeHtml(oid) + '</b>';
    }
    var rowIdx = Number((row && row[8]) || -1);
    var state = getNoIdInlineState(rowIdx);
    var btnText = (state && state.loading) ? 'Ищу...' : 'Подобрать';
    var disabled = (state && (state.loading || !!state.applyingId)) ? ' disabled' : '';
    return '<span style="color:#e65100">нет</span><div><button type="button" class="noid-pick-btn" data-row-idx="' + rowIdx + '"' + disabled + '>' + btnText + '</button></div>';
}

function renderMainTableNameCell(name, row){
    var html = escapeHtml(name || '');
    var oid = String((row && row[0]) || '').trim();
    if(!oid){
        html += renderNoIdInlinePicker(row || []);
    }
    return html;
}

function redrawMainTablePreservePage(){
    if(tblMain && typeof tblMain.rows === 'function' && typeof tblMain.draw === 'function'){
        tblMain.rows().invalidate();
        tblMain.draw(false);
        return;
    }
    renderMainTableFallback();
}

function resetNoIdInlinePicker(){
    noIdInlinePickerState = { rowIdx: -1, loading: false, applyingId: '', message: '', items: [], queryName: '' };
}

function closeNoIdInlinePicker(redraw){
    resetNoIdInlinePicker();
    if(redraw !== false){
        redrawMainTablePreservePage();
    }
}

function openNoIdInlinePicker(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var row = (mainTableRows || []).find(function(r){
        return Number((r && r[8]) || -1) === idx;
    });
    if(!row){ return; }
    noIdInlinePickerState = {
        rowIdx: idx,
        loading: true,
        applyingId: '',
        message: 'Ищу совпадения по Onliner для: ' + String(row[1] || ''),
        items: [],
        queryName: String(row[1] || '')
    };
    redrawMainTablePreservePage();
    var basePayload = {
        name: String(row[1] || ''),
        category: String(row[9] || ''),
        onliner_id: '',
        query: '',
        limit: 12
    };
    fetchNoIdCandidates(basePayload).then(function(items){
        if(items.length){ return items; }
        var retryQuery = compactBrandModelQuery(basePayload.name);
        if(!retryQuery){ return items; }
        return fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: '',
            query: retryQuery,
            limit: 12
        });
    }).then(function(items){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.loading = false;
        noIdInlinePickerState.items = Array.isArray(items) ? items : [];
        noIdInlinePickerState.message = noIdInlinePickerState.items.length
            ? 'Найдены кандидаты Onliner. Выбери нужную позицию.'
            : 'Точных кандидатов не найдено.';
        redrawMainTablePreservePage();
    }).catch(function(){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.loading = false;
        noIdInlinePickerState.items = [];
        noIdInlinePickerState.message = 'Ошибка поиска кандидатов Onliner.';
        redrawMainTablePreservePage();
    });
}

function applyNoIdCandidate(rowIdx, oid, url){
    var idx = Number(rowIdx || -1);
    var finalId = String(oid || '').trim();
    if(idx < 0 || !finalId){ return; }
    var row = (mainTableRows || []).find(function(r){
        return Number((r && r[8]) || -1) === idx;
    });
    if(!row){ return; }
    noIdInlinePickerState.applyingId = finalId;
    noIdInlinePickerState.message = 'Сохраняю ID в постоянный серверный кэш...';
    redrawMainTablePreservePage();
    fetch('/api/manual-id-confirm-batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            source: 'inline_noid_picker',
            items: [{
                row_idx: idx,
                name: String(row[1] || ''),
                onliner_id: finalId,
                url: String(url || '')
            }]
        })
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            throw new Error((d && d.message) || 'save_failed');
        }
        row[0] = finalId;
        if(showOnlyNoIdRows){
            mainTableRows = (mainTableRows || []).filter(function(r){
                return Number((r && r[8]) || -1) !== idx;
            });
        }
        closeNoIdInlinePicker(false);
        redrawMainTablePreservePage();
        if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        } else {
            fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(resp){
                mainTableRows = (resp && resp.data) ? resp.data : [];
                updateWithoutIdCount(mainTableRows);
                renderMainTableFallback();
            });
        }
        runPreExportQualityCheck();
    }).catch(function(){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.applyingId = '';
        noIdInlinePickerState.message = 'Не удалось сохранить ID. Попробуй еще раз.';
        redrawMainTablePreservePage();
    });
}

function handleNoIdTableClick(e){
    var pickBtn = e.target.closest('.noid-pick-btn');
    if(pickBtn){
        e.preventDefault();
        openNoIdInlinePicker(pickBtn.getAttribute('data-row-idx'));
        return;
    }
    var applyBtn = e.target.closest('.noid-inline-apply');
    if(applyBtn){
        e.preventDefault();
        applyNoIdCandidate(
            applyBtn.getAttribute('data-row-idx'),
            applyBtn.getAttribute('data-oid'),
            applyBtn.getAttribute('data-url')
        );
        return;
    }
    var closeBtn = e.target.closest('.noid-inline-close');
    if(closeBtn){
        e.preventDefault();
        closeNoIdInlinePicker();
    }
}

function updateWithoutIdCount(rows){
    var el = document.getElementById('without-id-count');
    if(!el){ return; }
    var list = Array.isArray(rows) ? rows : [];
    var count = list.reduce(function(acc, r){
        return acc + (!String((r && r[0]) || '').trim() ? 1 : 0);
    }, 0);
    el.textContent = String(count);
}

function escapeHtml(text){
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeCompactMatch(text){
    return String(text || '').toLowerCase().replace(/[^a-zа-я0-9]+/g, '');
}

function extractInlineHighlightTokens(localName){
    var raw = String(localName || '');
    var lower = raw.toLowerCase();
    var tokens = {};
    var colorWords = ['black','white','blue','red','green','grey','gray','silver','gold','pink','purple','orange','черный','чёрный','белый','синий','голубой','красный','зеленый','зелёный','серый','серебристый','золотой','желтый','жёлтый','розовый'];
    colorWords.forEach(function(word){
        if(lower.indexOf(word) >= 0){
            tokens[normalizeCompactMatch(word)] = true;
        }
    });
    var capacities = String(raw).match(/\b\d+(?:[.,]\d+)?\s*(?:tb|gb)\b/gi) || [];
    capacities.forEach(function(token){
        tokens[normalizeCompactMatch(token)] = true;
    });
    var latinModelTokens = String(raw).match(/\b[A-Za-z][A-Za-z0-9-]{2,}\b/g) || [];
    latinModelTokens.forEach(function(token){
        if(/\d/.test(token) || token.length >= 5){
            tokens[normalizeCompactMatch(token)] = true;
        }
    });
    return tokens;
}

function highlightCandidateName(localName, candidateName){
    var text = String(candidateName || '');
    var needles = extractInlineHighlightTokens(localName);
    if(!text || !Object.keys(needles).length){
        return escapeHtml(text);
    }
    var parts = [];
    var lastIdx = 0;
    var re = /[A-Za-zА-Яа-яЁё0-9.,-]+/g;
    var match;
    while((match = re.exec(text)) !== null){
        var token = match[0];
        var normalized = normalizeCompactMatch(token);
        parts.push(escapeHtml(text.slice(lastIdx, match.index)));
        if(normalized && needles[normalized]){
            parts.push('<span class="noid-inline-hit">' + escapeHtml(token) + '</span>');
        } else {
            parts.push(escapeHtml(token));
        }
        lastIdx = match.index + token.length;
    }
    parts.push(escapeHtml(text.slice(lastIdx)));
    return parts.join('');
}

function renderCandidateBadges(item){
    var badges = [];
    var reason = String((item && item.reason) || '').trim();
    var scoreNum = Number((item && item.score) || 0);
    var score = isNaN(scoreNum) ? 0 : scoreNum;
    var name = String((item && item.name) || '');
    if(score >= 0.97){
        badges.push('точное');
    } else if(reason === 'model_token' || reason === 'paren_model' || score >= 0.84){
        badges.push('модель');
    } else if(reason === 'article_like' || reason === 'article'){
        badges.push('артикул');
    }
    if(/\((черный|чёрный|белый|зеленый|зелёный|розовый|синий|красный)/i.test(name)){
        badges.push('цвет');
    }
    if(/(?:^|[^a-z0-9])(?:xbox|playstation|usb)(?=$|[^a-z0-9])/i.test(name)){
        badges.push('версия');
    }
    if(!badges.length){ return ''; }
    return '<div class="noid-inline-badges">' + badges.map(function(b){
        return '<span class="noid-inline-badge">' + escapeHtml(b) + '</span>';
    }).join('') + '</div>';
}

function compactBrandModelQuery(name){
    var text = String(name || '').replace(/\([^)]*\)/g, ' ');
    text = text.replace(/[,"']/g, ' ');
    text = text.replace(/\s+/g, ' ').trim();
    if(!text){ return ''; }
    var generic = {
        'гарнитура':1,'наушники':1,'наушникисмикрофоном':1,'с':1,'микрофоном':1,'мониторные':1,
        'охватывающие':1,'геймерские':1,'кабель':1,'черный':1,'чёрный':1,'белый':1,'зеленый':1,
        'зелёный':1,'розовый':1,'накладные':1,'usb':1
    };
    var parts = text.split(/\s+/);
    var picked = [];
    for(var i = 0; i < parts.length; i++){
        var token = parts[i];
        var norm = normalizeCompactMatch(token);
        if(!norm || generic[norm]){ continue; }
        if(picked.length < 2){
            picked.push(token);
            continue;
        }
        if(/[A-Za-z]/.test(token) && /\d/.test(token)){
            picked.push(token);
            continue;
        }
        if(/^v\d+$/i.test(token) || /^[xvspro]+$/i.test(token) || /^h\d{3,4}$/i.test(token)){
            picked.push(token);
            continue;
        }
        if(picked.length >= 4){ break; }
    }
    return picked.slice(0, 5).join(' ').trim();
}

function bracketModelQuery(name){
    var text = String(name || '');
    if(!text){ return ''; }
    var generic = {
        'hdd':1,'ssd':1,'sata':1,'sataiii':1,'sataii':1,'nvme':1,'m2':1,'usb':1,'typec':1,
        'tb':1,'gb':1,'mb':1,'rpm':1
    };
    var brand = '';
    var words = text.replace(/[,"']/g, ' ').split(/\s+/);
    for(var i = 0; i < words.length; i++){
        var token = String(words[i] || '').trim();
        var norm = normalizeCompactMatch(token);
        if(!norm || generic[norm] || /\d/.test(token)){ continue; }
        if(/[A-Za-zА-Яа-я]/.test(token)){
            brand = token;
            break;
        }
    }
    var parts = text.match(/\(([^)]+)\)/g) || [];
    for(var j = 0; j < parts.length; j++){
        var inside = String(parts[j] || '').replace(/[()]/g, '').trim();
        var normInside = normalizeCompactMatch(inside);
        if(normInside.length < 5){ continue; }
        if(/[A-Za-z]/.test(inside) && /\d/.test(inside)){
            return brand ? (brand + ' ' + inside) : inside;
        }
    }
    return '';
}

function processorModelQuery(name){
    var text = String(name || '');
    if(!text){ return ''; }
    var patterns = [
        /(?:^|[^a-z0-9])(i[3579]-\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(pentium\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(celeron\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(athlon\s+\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i
    ];
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            return String(m[1]).replace(/\s+/g, ' ').trim();
        }
    }
    return '';
}

function fetchNoIdCandidates(payload){
    return fetch('/api/id-replace-candidates', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || {})
    }).then(function(r){ return r.json(); }).then(function(d){
        return Array.isArray(d && d.items) ? d.items : [];
    });
}

function getVerifyAllIdCandidateState(rowIdx){
    var key = String(Number(rowIdx || -1));
    if(!verifyAllIdsCandidateState[key]){
        verifyAllIdsCandidateState[key] = { loading: false, applyingId: '', items: [], message: '', manualOpen: false, manualValue: '' };
    }
    return verifyAllIdsCandidateState[key];
}

function renderVerifyAllIdCandidates(issue){
    var idx = Number((issue && issue.row_idx) || -1);
    if(idx < 0){ return ''; }
    var state = getVerifyAllIdCandidateState(idx);
    var html = '<div class="verify-id-inline-box">';
    if(state.loading){
        html += '<div class="noid-inline-note">Ищу варианты замены...</div>';
    } else if(state.message){
        html += '<div class="noid-inline-note">' + escapeHtml(state.message) + '</div>';
    }
    if(state.manualOpen){
        html += '<div class="noid-inline-picker" style="margin-bottom:8px;">';
        html += '<div class="noid-inline-note">Введите правильный Onliner ID для этого товара.</div>';
        html += '<div class="noid-inline-top">';
        html += '<input type="text" class="verify-id-manual-input" data-row-idx="' + idx + '" value="' + escapeHtml(state.manualValue || '') + '" placeholder="Например: 123456" style="flex:1; min-width:180px; padding:7px 10px; border:1px solid #cfd8e3; border-radius:8px; font-size:12px;">';
        html += '<div style="display:flex; gap:8px;">';
        html += '<button type="button" class="noid-inline-apply verify-id-manual-save" data-row-idx="' + idx + '">Сохранить ID</button>';
        html += '<button type="button" class="noid-inline-close verify-id-manual-cancel" data-row-idx="' + idx + '">Отмена</button>';
        html += '</div>';
        html += '</div>';
        html += '</div>';
    }
    if(Array.isArray(state.items) && state.items.length){
        html += '<div class="noid-inline-list">';
        state.items.forEach(function(item){
            var candidateId = String((item && item.id) || '').trim();
            var candidateName = String((item && item.name) || '').trim();
            var candidateUrl = String((item && item.url) || '').trim();
            var scoreNum = Number((item && item.score) || 0);
            var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
            var isApplying = !!(state.applyingId && state.applyingId === candidateId);
            html += '<div class="noid-inline-item">';
            html += '<div class="noid-inline-meta">';
            html += '<div class="noid-inline-title">' + highlightCandidateName(issue.name || '', candidateName || candidateId || 'Кандидат без названия') + '</div>';
            html += renderCandidateBadges(item || {});
            html += '<div class="noid-inline-sub">ID: ' + escapeHtml(candidateId || '—') + (score ? (' · score ' + escapeHtml(score)) : '') + '</div>';
            html += '</div>';
            html += '<div class="noid-inline-actions">';
            if(candidateUrl){
                html += '<a href="' + escapeHtml(candidateUrl) + '" target="_blank" rel="noopener noreferrer" class="noid-inline-open">Открыть</a>';
            }
            html += '<button type="button" class="noid-inline-apply verify-id-inline-apply" data-row-idx="' + idx + '" data-oid="' + escapeHtml(candidateId) + '" data-url="' + escapeHtml(candidateUrl) + '"' + (isApplying ? ' disabled' : '') + '>' + (isApplying ? 'Сохраняю...' : 'Заменить ID') + '</button>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
    }
    html += '</div>';
    return html;
}

function promptVerifyAllIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var issue = (verifyAllIdsItems || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var currentId = String((issue && issue.onliner_id) || '').trim();
    var state = getVerifyAllIdCandidateState(idx);
    state.manualOpen = true;
    state.manualValue = state.manualValue || currentId || '';
    state.message = 'Введите ID и сохраните его для этого товара.';
    renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
}

function saveVerifyAllIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var state = getVerifyAllIdCandidateState(idx);
    var input = document.querySelector('.verify-id-manual-input[data-row-idx="' + idx + '"]');
    var finalId = String(input ? input.value : state.manualValue || '').replace(/\D+/g, '').trim();
    if(!finalId){
        state.manualOpen = true;
        state.message = 'Нужно вставить числовой Onliner ID.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
        return;
    }
    state.manualValue = finalId;
    state.manualOpen = false;
    applyVerifyAllIdCandidate(idx, finalId, '');
}

function cancelVerifyAllIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var state = getVerifyAllIdCandidateState(idx);
    state.manualOpen = false;
    state.message = '';
    renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
}

function getDuplicateIdCandidateState(rowIdx){
    var key = String(Number(rowIdx || -1));
    if(!duplicateIdCandidateState[key]){
        duplicateIdCandidateState[key] = { loading: false, applyingId: '', items: [], message: '', manualOpen: false, manualValue: '' };
    }
    return duplicateIdCandidateState[key];
}

function renderDuplicateIdCandidates(issue){
    var idx = Number((issue && issue.row_idx) || -1);
    if(idx < 0){ return ''; }
    var state = getDuplicateIdCandidateState(idx);
    var html = '<div class="verify-id-inline-box">';
    if(state.loading){
        html += '<div class="noid-inline-note">Ищу варианты замены...</div>';
    } else if(state.message){
        html += '<div class="noid-inline-note">' + escapeHtml(state.message) + '</div>';
    }
    if(state.manualOpen){
        html += '<div class="noid-inline-picker" style="margin-bottom:8px;">';
        html += '<div class="noid-inline-note">Введите правильный Onliner ID для этого товара.</div>';
        html += '<div class="noid-inline-top">';
        html += '<input type="text" class="duplicate-id-manual-input" data-row-idx="' + idx + '" value="' + escapeHtml(state.manualValue || '') + '" placeholder="Например: 123456" style="flex:1; min-width:180px; padding:7px 10px; border:1px solid #cfd8e3; border-radius:8px; font-size:12px;">';
        html += '<div style="display:flex; gap:8px;">';
        html += '<button type="button" class="noid-inline-apply duplicate-id-manual-save" data-row-idx="' + idx + '">Сохранить ID</button>';
        html += '<button type="button" class="noid-inline-close duplicate-id-manual-cancel" data-row-idx="' + idx + '">Отмена</button>';
        html += '</div>';
        html += '</div>';
        html += '</div>';
    }
    if(Array.isArray(state.items) && state.items.length){
        html += '<div class="noid-inline-list">';
        state.items.forEach(function(item){
            var candidateId = String((item && item.id) || '').trim();
            var candidateName = String((item && item.name) || '').trim();
            var candidateUrl = String((item && item.url) || '').trim();
            var scoreNum = Number((item && item.score) || 0);
            var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
            var isApplying = !!(state.applyingId && state.applyingId === candidateId);
            html += '<div class="noid-inline-item">';
            html += '<div class="noid-inline-meta">';
            html += '<div class="noid-inline-title">' + highlightCandidateName(issue.name || '', candidateName || candidateId || 'Кандидат без названия') + '</div>';
            html += renderCandidateBadges(item || {});
            html += '<div class="noid-inline-sub">ID: ' + escapeHtml(candidateId || '—') + (score ? (' · score ' + escapeHtml(score)) : '') + '</div>';
            html += '</div>';
            html += '<div class="noid-inline-actions">';
            if(candidateUrl){
                html += '<a href="' + escapeHtml(candidateUrl) + '" target="_blank" rel="noopener noreferrer" class="noid-inline-open">Открыть</a>';
            }
            html += '<button type="button" class="noid-inline-apply duplicate-id-inline-apply" data-row-idx="' + idx + '" data-oid="' + escapeHtml(candidateId) + '" data-url="' + escapeHtml(candidateUrl) + '"' + (isApplying ? ' disabled' : '') + '>' + (isApplying ? 'Сохраняю...' : 'Заменить ID') + '</button>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
    }
    html += '</div>';
    return html;
}

function renderDuplicateIdCheckStatus(data){
    var btn = document.getElementById('run-duplicate-id-check-btn');
    var note = document.getElementById('duplicate-id-note');
    var card = document.getElementById('duplicate-id-check-card');
    var summary = document.getElementById('duplicate-id-check-summary');
    var results = document.getElementById('duplicate-id-check-results');
    if(!btn || !note || !card || !summary || !results){ return; }

    var items = Array.isArray(data && data.items) ? data.items.slice() : duplicateIdIssues.slice();
    var totalIds = Number((data && data.problem_ids) || duplicateIdProblemCount || 0);
    var totalRows = Number((data && data.problem_rows) || items.length || 0);
    var message = String((data && data.message) || '').trim();
    duplicateIdIssues = items;
    duplicateIdProblemCount = totalIds;

    btn.disabled = false;
    btn.textContent = 'Одинаковые ID';
    note.textContent = duplicateIdLastActionMessage || message || (totalRows ? ('Найдено строк с одинаковыми ID: ' + String(totalRows) + '.') : 'Поиск случаев, когда один OnlinerID стоит у разных товаров.');

    if(totalRows || message){
        card.style.display = 'block';
    }
    syncDuplicateIdCheckCardCollapsed();
    summary.textContent = message || (totalRows
        ? ('Найдено проблемных OnlinerID: ' + String(totalIds) + '. Строк для проверки: ' + String(totalRows) + '.')
        : 'Одинаковых OnlinerID у разных товаров не найдено.');

    if(!items.length){
        results.innerHTML = totalRows ? '' : '<div class="markup-note" style="margin-top:10px;">Проблемных одинаковых ID не найдено.</div>';
        return;
    }

    results.innerHTML = '<div class="verify-id-list">' + items.map(function(issue){
        var rowIdx = Number((issue && issue.row_idx) || -1);
        var scoreNum = Number((issue && issue.score) || 0);
        var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
        var apiName = String((issue && issue.api_name) || '').trim();
        var apiUrl = String((issue && issue.api_url) || '').trim();
        var reason = String((issue && issue.reason_label) || (issue && issue.reason) || '').trim();
        var currentId = String((issue && issue.onliner_id) || '').trim();
        var statusLabel = String((issue && issue.status_label) || 'Одинаковый ID').trim();
        var html = '<div class="verify-id-item">';
        html += '<div class="verify-id-head">';
        html += '<div>';
        html += '<div class="verify-id-title">' + escapeHtml(String((issue && issue.name) || '')) + '</div>';
        html += '<div class="verify-id-sub">Текущий ID: <b>' + escapeHtml(currentId || '—') + '</b> | Поставщик: ' + escapeHtml(String((issue && issue.supplier) || '')) + '</div>';
        html += '<div class="verify-id-sub">Onliner по ID: ' + (apiUrl ? ('<a href="' + escapeHtml(apiUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(apiName || currentId) + '</a>') : escapeHtml(apiName || 'Не удалось получить название')) + '</div>';
        html += '<div class="verify-id-sub">Причина: ' + escapeHtml(reason || 'Одинаковый OnlinerID') + (score ? (' | score: ' + escapeHtml(score)) : '') + '</div>';
        html += '</div>';
        html += '<div class="verify-id-status">' + escapeHtml(statusLabel) + '</div>';
        html += '</div>';
        html += '<div class="verify-id-actions">';
        html += '<button type="button" class="btn btn-outline duplicate-id-load-btn" data-row-idx="' + rowIdx + '" style="padding:8px 12px;font-size:13px;">Подобрать замену</button>';
        html += '<button type="button" class="btn btn-outline duplicate-id-manual-btn" data-row-idx="' + rowIdx + '" style="padding:8px 12px;font-size:13px;">Вставить ID</button>';
        html += '</div>';
        html += renderDuplicateIdCandidates(issue || {});
        html += '</div>';
        return html;
    }).join('') + '</div>';
    compactVerifyIdCards('duplicate-id-check-results');
}

function runDuplicateIdCheck(silent){
    var btn = document.getElementById('run-duplicate-id-check-btn');
    var card = document.getElementById('duplicate-id-check-card');
    var summary = document.getElementById('duplicate-id-check-summary');
    var results = document.getElementById('duplicate-id-check-results');
    if(btn){
        btn.disabled = true;
        btn.textContent = 'Проверяю...';
    }
    if(!silent && card){ card.style.display = 'block'; }
    if(summary){ summary.textContent = 'Ищу одинаковые OnlinerID в текущем прайсе...'; }
    if(results && !silent){ results.innerHTML = ''; }
    if(!silent){ duplicateIdLastActionMessage = ''; }
    duplicateIdCardCollapsed = false;
    syncDuplicateIdCheckCardCollapsed();
    fetch('/api/check-duplicate-onliner-ids', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            throw new Error((d && d.message) || 'check_failed');
        }
        renderDuplicateIdCheckStatus(d || {});
    }).catch(function(){
        if(btn){
            btn.disabled = false;
            btn.textContent = 'Одинаковые ID';
        }
        var note = document.getElementById('duplicate-id-note');
        if(note){ note.textContent = 'Не удалось проверить одинаковые ID.'; }
        if(summary){ summary.textContent = 'Не удалось выполнить проверку одинаковых OnlinerID.'; }
    });
}

function loadDuplicateIdCandidates(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var issue = (duplicateIdIssues || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var state = getDuplicateIdCandidateState(idx);
    var basePayload = {
        name: String(issue.name || ''),
        category: String(issue.category || ''),
        onliner_id: String(issue.onliner_id || ''),
        exclude_current: true,
        query: '',
        limit: 12
    };
    state.loading = true;
    state.items = [];
    state.message = 'Ищу кандидатов для замены...';
    renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });

    var compactQuery = compactBrandModelQuery(basePayload.name);
    var modelQuery = bracketModelQuery(basePayload.name);
    var cpuQuery = processorModelQuery(basePayload.name);
    var requests = [
        fetchNoIdCandidates(basePayload).catch(function(){ return []; })
    ];
    if(compactQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            exclude_current: true,
            query: compactQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }
    if(modelQuery && modelQuery !== compactQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            exclude_current: true,
            query: modelQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }
    if(cpuQuery && cpuQuery !== compactQuery && cpuQuery !== modelQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            exclude_current: true,
            query: cpuQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }

    Promise.all(requests).then(function(results){
        state.loading = false;
        state.items = mergeVerifyIdCandidateLists(results, 12);
        state.message = state.items.length ? 'Выберите правильный ID.' : 'Подходящих кандидатов не найдено.';
        renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
    }).catch(function(){
        state.loading = false;
        state.items = [];
        state.message = 'Ошибка поиска кандидатов.';
        renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
    });
}

function promptDuplicateIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var issue = (duplicateIdIssues || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var currentId = String((issue && issue.onliner_id) || '').trim();
    var state = getDuplicateIdCandidateState(idx);
    state.manualOpen = true;
    state.manualValue = state.manualValue || currentId || '';
    state.message = 'Введите новый правильный ID для этого товара.';
    renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
}

function saveDuplicateIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var state = getDuplicateIdCandidateState(idx);
    var input = document.querySelector('.duplicate-id-manual-input[data-row-idx="' + idx + '"]');
    var finalId = String(input ? input.value : state.manualValue || '').replace(/\D+/g, '').trim();
    var issue = (duplicateIdIssues || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!finalId){
        state.manualOpen = true;
        state.message = 'Нужно вставить числовой Onliner ID.';
        renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
        return;
    }
    state.manualValue = finalId;
    state.manualOpen = false;
    applyDuplicateIdCandidate(idx, finalId, '');
}

function cancelDuplicateIdManual(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var state = getDuplicateIdCandidateState(idx);
    state.manualOpen = false;
    state.message = '';
    renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
}

function applyDuplicateIdCandidate(rowIdx, oid, url){
    var idx = Number(rowIdx || -1);
    var finalId = String(oid || '').trim();
    if(idx < 0 || !finalId){ return; }
    var issue = (duplicateIdIssues || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var state = getDuplicateIdCandidateState(idx);
    var currentId = String((issue && issue.onliner_id) || '').trim();
    state.applyingId = finalId;
    state.message = (currentId && finalId === currentId)
        ? 'Подтверждаю текущий ID и сохраняю его в вечный кеш...'
        : 'Сохраняю новый ID в постоянный кеш...';
    renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
    fetch('/api/manual-id-confirm-batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            source: 'duplicate_id_replace',
            items: [{
                row_idx: idx,
                name: String(issue.name || ''),
                onliner_id: finalId,
                url: String(url || '')
            }]
        })
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            throw new Error((d && d.message) || 'save_failed');
        }
        delete duplicateIdCandidateState[String(idx)];
        (mainTableRows || []).forEach(function(row){
            if(Number((row && row[8]) || -1) === idx){
                row[0] = finalId;
            }
        });
        if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        } else {
            redrawMainTablePreservePage();
        }
        runPreExportQualityCheck();
        duplicateIdLastActionMessage = (currentId && finalId === currentId)
            ? ('Текущий ID ' + finalId + ' подтверждён и сохранён в вечный кеш.')
            : ('ID ' + finalId + ' сохранён в прайс и вечный кеш.');
        var note = document.getElementById('duplicate-id-note');
        if(note){
            note.textContent = duplicateIdLastActionMessage + ' Обновляю список конфликтов...';
        }
        var summary = document.getElementById('duplicate-id-check-summary');
        if(summary){
            summary.textContent = 'Новый ID сохранён. Перепроверяю одинаковые OnlinerID...';
        }
        runDuplicateIdCheck(true);
    }).catch(function(){
        state.applyingId = '';
        state.message = 'Не удалось заменить ID. Попробуйте еще раз.';
        renderDuplicateIdCheckStatus({ items: duplicateIdIssues, problem_rows: duplicateIdIssues.length, problem_ids: duplicateIdProblemCount });
    });
}

function renderVerifyAllIdsReport(data){
    var wrap = document.getElementById('verify-all-ids-report-wrap');
    var summary = document.getElementById('verify-all-ids-report-summary');
    var tableWrap = document.getElementById('verify-all-ids-report-table-wrap');
    if(!wrap || !summary || !tableWrap){ return; }

    if(Array.isArray(data && data.report_items)){
        verifyAllIdsReportItems = data.report_items.slice();
    }

    if(!verifyAllIdsReportVisible){
        wrap.style.display = 'none';
        return;
    }
    wrap.style.display = 'block';

    var total = verifyAllIdsReportItems.length;
    summary.textContent = total
        ? ('Полная таблица проверки: ' + String(total) + ' строк.')
        : 'Полная таблица проверки пока пуста.';

    if(!total){
        tableWrap.innerHTML = '<div class="markup-note" style="padding:12px;">Нет данных для отображения.</div>';
        return;
    }

    tableWrap.innerHTML = '<table class="verify-id-report-table"><thead><tr>'
        + '<th>Статус</th>'
        + '<th>ID</th>'
        + '<th>Локальное название</th>'
        + '<th>Onliner</th>'
        + '<th>Причина</th>'
        + '<th>Score</th>'
        + '</tr></thead><tbody>'
        + verifyAllIdsReportItems.map(function(item){
            var status = String((item && item.status_label) || '').trim() || 'Проверить';
            var statusKey = String((item && item.status) || '').trim().toLowerCase();
            var statusCls = statusKey === 'match' ? 'ok' : (statusKey === 'mismatch' ? 'bad' : 'review');
            var oid = String((item && item.onliner_id) || '').trim();
            var localName = String((item && item.name) || '').trim();
            var apiName = String((item && item.api_name) || '').trim();
            var apiUrl = String((item && item.api_url) || '').trim();
            var reason = String((item && item.reason_label) || (item && item.reason) || '').trim();
            var scoreNum = Number((item && item.score) || 0);
            var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
            return '<tr>'
                + '<td><span class="verify-id-report-status ' + statusCls + '">' + escapeHtml(status) + '</span></td>'
                + '<td>' + escapeHtml(oid || '—') + '</td>'
                + '<td>' + escapeHtml(localName || '—') + '</td>'
                + '<td>' + (apiUrl ? ('<a href="' + escapeHtml(apiUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(apiName || oid || 'Открыть') + '</a>') : escapeHtml(apiName || '—')) + '</td>'
                + '<td>' + escapeHtml(reason || '—') + '</td>'
                + '<td>' + escapeHtml(score || '—') + '</td>'
                + '</tr>';
        }).join('')
        + '</tbody></table>';
}

function toggleVerifyAllIdsReport(forceVisible){
    if(typeof forceVisible === 'boolean'){
        verifyAllIdsReportVisible = forceVisible;
    } else {
        verifyAllIdsReportVisible = !verifyAllIdsReportVisible;
    }
    renderVerifyAllIdsReport({});
}

function syncVerifyAllIdsCardCollapsed(){
    var body = document.getElementById('verify-all-ids-card-body');
    var btn = document.getElementById('toggle-verify-all-ids-card-btn');
    if(!body || !btn){ return; }
    body.style.display = verifyAllIdsCardCollapsed ? 'none' : 'block';
    btn.textContent = verifyAllIdsCardCollapsed ? 'Показать' : 'Скрыть';
}

function toggleVerifyAllIdsCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        verifyAllIdsCardCollapsed = forceCollapsed;
    } else {
        verifyAllIdsCardCollapsed = !verifyAllIdsCardCollapsed;
    }
    syncVerifyAllIdsCardCollapsed();
}

function syncDuplicateIdCheckCardCollapsed(){
    var body = document.getElementById('duplicate-id-check-card-body');
    var btn = document.getElementById('toggle-duplicate-id-check-card-btn');
    if(!body || !btn){ return; }
    body.style.display = duplicateIdCardCollapsed ? 'none' : 'block';
    btn.textContent = duplicateIdCardCollapsed ? 'Показать' : 'Скрыть';
}

function toggleDuplicateIdCheckCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        duplicateIdCardCollapsed = forceCollapsed;
    } else {
        duplicateIdCardCollapsed = !duplicateIdCardCollapsed;
    }
    syncDuplicateIdCheckCardCollapsed();
}

function ensureQualityCheckCardUI(){
    var card = document.getElementById('quality-check-card');
    if(!card){ return; }
    var header = card.firstElementChild;
    var body = card.children.length > 1 ? card.children[1] : null;
    if(header && !header.classList.contains('quality-card-head')){
        header.classList.add('quality-card-head');
    }
    if(body && !body.id){
        body.id = 'quality-check-card-body';
    }
    if(body){
        body.style.padding = '12px 14px';
    }
    var btn = document.getElementById('toggle-quality-check-card-btn');
    if(!btn && header){
        btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'toggle-quality-check-card-btn';
        btn.className = 'btn btn-outline quality-card-toggle';
        btn.textContent = 'Скрыть';
        header.appendChild(btn);
        btn.addEventListener('click', function(){
            toggleQualityCheckCard();
        });
    }
    var reapplyBtn = document.getElementById('quality-reapply-markups-btn');
    var details = document.getElementById('quality-check-details');
    if(reapplyBtn){
        reapplyBtn.classList.add('quality-reapply-btn');
        reapplyBtn.classList.remove('btn-outline');
        reapplyBtn.style.marginTop = '12px';
    }
    if(reapplyBtn && details && reapplyBtn.parentElement !== body){
        body.appendChild(reapplyBtn);
    } else if(reapplyBtn && body && reapplyBtn.parentElement === body){
        body.appendChild(reapplyBtn);
    }
    var actionsWrap = card.querySelector('.quality-actions');
    if(actionsWrap){
        actionsWrap.style.display = 'none';
    }
    syncQualityCheckCardCollapsed();
}

function syncQualityCheckCardCollapsed(){
    var body = document.getElementById('quality-check-card-body');
    var btn = document.getElementById('toggle-quality-check-card-btn');
    if(!body || !btn){ return; }
    body.style.display = qualityCheckCardCollapsed ? 'none' : 'block';
    btn.textContent = qualityCheckCardCollapsed ? 'Показать' : 'Скрыть';
}

function toggleQualityCheckCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        qualityCheckCardCollapsed = forceCollapsed;
    } else {
        qualityCheckCardCollapsed = !qualityCheckCardCollapsed;
    }
    syncQualityCheckCardCollapsed();
}

function renderVerifyAllIdsStatus(data){
    var btn = document.getElementById('run-verify-all-ids-btn');
    var note = document.getElementById('verify-all-id-note');
    var countEl = document.getElementById('verify-all-id-count');
    var card = document.getElementById('verify-all-ids-card');
    var summary = document.getElementById('verify-all-ids-summary');
    var results = document.getElementById('verify-all-ids-results');
    if(!btn || !note || !countEl || !card || !summary || !results){ return; }

    var running = !!(data && data.running);
    var total = Number((data && data.total) || 0);
    var done = Number((data && data.done) || 0);
    var mismatched = Number((data && data.mismatched) || 0);
    var matched = Number((data && data.matched) || 0);
    var errors = Number((data && data.errors) || 0);
    var message = String((data && data.message) || '').trim();

    btn.disabled = running;
    btn.textContent = running ? 'Проверяю...' : 'Запустить';
    countEl.textContent = running ? (String(done) + '/' + String(total || 0)) : (total ? String(mismatched) : '—');
    note.textContent = running
        ? ('Проверено ' + String(done) + ' из ' + String(total || 0) + '. Несовпадений: ' + String(mismatched))
        : (message || (total ? ('Проверено: ' + String(total) + '. Несовпадений: ' + String(mismatched)) : 'Сверка текущих ID с товаром Onliner по API.'));
    note.classList.toggle('verify-id-note-link', !running && !!total);

    if(running || total || mismatched || errors){
        card.style.display = 'block';
    }
    syncVerifyAllIdsCardCollapsed();
    summary.textContent = running
        ? ('Идет проверка ID: ' + String(done) + ' / ' + String(total || 0))
        : (message || ('Проверено: ' + String(total) + ', совпало: ' + String(matched) + ', не совпало: ' + String(mismatched) + ', ошибок API: ' + String(errors)));

    if(Array.isArray(data && data.items)){
        verifyAllIdsItems = data.items.slice();
    }
    if(Array.isArray(data && data.report_items)){
        verifyAllIdsReportItems = data.report_items.slice();
    }

    renderVerifyAllIdsReport(data || {});

    if(running){
        return;
    }

    if(!verifyAllIdsItems.length){
        results.innerHTML = total ? '<div class="markup-note" style="margin-top:10px;">Проблемных ID не найдено.</div>' : '';
        return;
    }

    results.innerHTML = '<div class="verify-id-list">' + verifyAllIdsItems.map(function(issue){
        var rowIdx = Number((issue && issue.row_idx) || -1);
        var scoreNum = Number((issue && issue.score) || 0);
        var score = isNaN(scoreNum) ? '' : scoreNum.toFixed(3);
        var apiName = String((issue && issue.api_name) || '').trim();
        var apiUrl = String((issue && issue.api_url) || '').trim();
        var reason = String((issue && issue.reason_label) || (issue && issue.reason) || '').trim();
        var currentId = String((issue && issue.onliner_id) || '').trim();
        var statusLabel = String((issue && issue.status_label) || 'Проверить').trim();
        var html = '<div class="verify-id-item">';
        html += '<div class="verify-id-head">';
        html += '<div>';
        html += '<div class="verify-id-title">' + escapeHtml(String((issue && issue.name) || '')) + '</div>';
        html += '<div class="verify-id-sub">Текущий ID: <b>' + escapeHtml(currentId || '—') + '</b> | Поставщик: ' + escapeHtml(String((issue && issue.supplier) || '')) + '</div>';
        html += '<div class="verify-id-sub">Onliner по ID: ' + (apiUrl ? ('<a href="' + escapeHtml(apiUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(apiName || currentId) + '</a>') : escapeHtml(apiName || 'Не удалось получить название')) + '</div>';
        html += '<div class="verify-id-sub">Причина: ' + escapeHtml(reason || 'Несовпадение') + (score ? (' | score: ' + escapeHtml(score)) : '') + '</div>';
        html += '</div>';
        html += '<div class="verify-id-status">' + escapeHtml(statusLabel) + '</div>';
        html += '</div>';
        html += '<div class="verify-id-actions">';
        html += '<button type="button" class="btn btn-outline verify-id-load-btn" data-row-idx="' + rowIdx + '" style="padding:8px 12px;font-size:13px;">Подобрать замену</button>';
        html += '<button type="button" class="btn btn-outline verify-id-manual-btn" data-row-idx="' + rowIdx + '" style="padding:8px 12px;font-size:13px;">Вставить ID</button>';
        html += '</div>';
        html += renderVerifyAllIdCandidates(issue || {});
        html += '</div>';
        return html;
    }).join('') + '</div>';
}

function pollVerifyAllIdsStatus(){
    fetch('/api/verify-all-ids-status').then(function(r){ return r.json(); }).then(function(d){
        renderVerifyAllIdsStatus(d || {});
        if(d && d.running){
            clearTimeout(verifyAllIdsPollTimer);
            verifyAllIdsPollTimer = setTimeout(pollVerifyAllIdsStatus, 1200);
        }
    }).catch(function(){
        clearTimeout(verifyAllIdsPollTimer);
        verifyAllIdsPollTimer = null;
        var note = document.getElementById('verify-all-id-note');
        if(note){ note.textContent = 'Ошибка связи с сервером при проверке ID.'; }
        var btn = document.getElementById('run-verify-all-ids-btn');
        if(btn){ btn.disabled = false; btn.textContent = 'Запустить'; }
    });
}

function runVerifyAllIds(){
    var card = document.getElementById('verify-all-ids-card');
    var summary = document.getElementById('verify-all-ids-summary');
    var results = document.getElementById('verify-all-ids-results');
    verifyAllIdsItems = [];
    verifyAllIdsCandidateState = {};
    verifyAllIdsReportItems = [];
    verifyAllIdsReportVisible = false;
    verifyAllIdsCardCollapsed = false;
    if(card){ card.style.display = 'block'; }
    qualityCheckCardCollapsed = false;
    syncQualityCheckCardCollapsed();
    qualityCheckCardCollapsed = false;
    syncQualityCheckCardCollapsed();
    if(summary){ summary.textContent = 'Запускаю проверку всех ID...'; }
    if(results){ results.innerHTML = ''; }
    syncVerifyAllIdsCardCollapsed();
    renderVerifyAllIdsReport({});
    fetch('/api/verify-all-ids-start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || (d.status !== 'started' && d.status !== 'already_running')){
            throw new Error((d && d.message) || 'start_failed');
        }
        pollVerifyAllIdsStatus();
    }).catch(function(){
        var note = document.getElementById('verify-all-id-note');
        if(note){ note.textContent = 'Не удалось запустить проверку ID.'; }
        var btn = document.getElementById('run-verify-all-ids-btn');
        if(btn){ btn.disabled = false; btn.textContent = 'Запустить'; }
    });
}

function loadVerifyAllIdCandidates(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var issue = (verifyAllIdsItems || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var state = getVerifyAllIdCandidateState(idx);
    state.loading = true;
    state.items = [];
    state.message = 'Ищу кандидатов для замены...';
    renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    fetchNoIdCandidates({
        name: String(issue.name || ''),
        category: String(issue.category || ''),
        onliner_id: String(issue.onliner_id || ''),
        query: '',
        limit: 12
    }).then(function(items){
        state.loading = false;
        state.items = Array.isArray(items) ? items : [];
        state.message = state.items.length ? 'Выберите правильный ID.' : 'Подходящих кандидатов не найдено.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    }).catch(function(){
        state.loading = false;
        state.items = [];
        state.message = 'Ошибка поиска кандидатов.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    });
}

function applyVerifyAllIdCandidate(rowIdx, oid, url){
    var idx = Number(rowIdx || -1);
    var finalId = String(oid || '').trim();
    if(idx < 0 || !finalId){ return; }
    var issue = (verifyAllIdsItems || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var state = getVerifyAllIdCandidateState(idx);
    state.applyingId = finalId;
    state.message = 'Сохраняю новый ID в постоянный кеш...';
    renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    fetch('/api/manual-id-confirm-batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            source: 'verify_all_ids_replace',
            items: [{
                row_idx: idx,
                name: String(issue.name || ''),
                onliner_id: finalId,
                url: String(url || '')
            }]
        })
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            throw new Error((d && d.message) || 'save_failed');
        }
        verifyAllIdsItems = (verifyAllIdsItems || []).filter(function(item){
            return Number((item && item.row_idx) || -1) !== idx;
        });
        delete verifyAllIdsCandidateState[String(idx)];
        (mainTableRows || []).forEach(function(row){
            if(Number((row && row[8]) || -1) === idx){
                row[0] = finalId;
            }
        });
        renderVerifyAllIdsStatus({
            items: verifyAllIdsItems,
            total: verifyAllIdsItems.length,
            done: verifyAllIdsItems.length,
            mismatched: verifyAllIdsItems.length,
            message: 'ID обновлен и сохранен в постоянный кеш.'
        });
        if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        } else {
            redrawMainTablePreservePage();
        }
        runPreExportQualityCheck();
    }).catch(function(){
        state.applyingId = '';
        state.message = 'Не удалось заменить ID. Попробуйте еще раз.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    });
}

function mergeVerifyIdCandidateLists(lists, limit){
    var out = [];
    var seen = {};
    var maxItems = Number(limit || 12);
    (lists || []).forEach(function(items){
        (Array.isArray(items) ? items : []).forEach(function(item){
            var cid = String((item && item.id) || '').trim();
            if(!cid || seen[cid]){ return; }
            seen[cid] = true;
            out.push(item);
        });
    });
    return out.slice(0, Math.max(1, maxItems));
}

function compactVerifyIdCards(rootId){
    var root = document.getElementById(rootId || 'verify-all-ids-results');
    if(!root){ return; }
    root.querySelectorAll('.verify-id-item').forEach(function(card){
        var subs = card.querySelectorAll('.verify-id-sub');
        if(!subs || subs.length < 2){ return; }
        if(subs.length >= 3){
            var metaText = String(subs[0].textContent || '').trim();
            metaText = metaText.replace(/^Текущий ID:\s*/i, 'ID ');
            metaText = metaText.replace(/\s*\|\s*Поставщик:\s*/i, ' · ');
            var reasonText = String(subs[2].textContent || '').replace(/^Причина:\s*/i, '').trim();
            reasonText = reasonText.replace(/\s*\|\s*score:.*$/i, '').trim();
            subs[0].textContent = reasonText ? (metaText + ' · ' + reasonText) : metaText;
            subs[1].innerHTML = subs[1].innerHTML.replace('Onliner по ID:', 'Onliner:');
            for(var i = subs.length - 1; i >= 2; i--){
                subs[i].remove();
            }
        }
        card.querySelectorAll('.verify-id-load-btn, .verify-id-manual-btn, .duplicate-id-load-btn, .duplicate-id-manual-btn').forEach(function(btn){
            btn.style.padding = '5px 10px';
            btn.style.fontSize = '12px';
            btn.style.lineHeight = '1.1';
        });
    });
}

var _renderVerifyAllIdsStatusOriginal = renderVerifyAllIdsStatus;
renderVerifyAllIdsStatus = function(data){
    _renderVerifyAllIdsStatusOriginal(data);
    compactVerifyIdCards('verify-all-ids-results');
};

loadVerifyAllIdCandidates = function(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var issue = (verifyAllIdsItems || []).find(function(item){
        return Number((item && item.row_idx) || -1) === idx;
    });
    if(!issue){ return; }
    var state = getVerifyAllIdCandidateState(idx);
    var basePayload = {
        name: String(issue.name || ''),
        category: String(issue.category || ''),
        onliner_id: String(issue.onliner_id || ''),
        query: '',
        limit: 12
    };
    state.loading = true;
    state.items = [];
    state.message = 'Ищу кандидатов для замены...';
    renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });

    var compactQuery = compactBrandModelQuery(basePayload.name);
    var modelQuery = bracketModelQuery(basePayload.name);
    var cpuQuery = processorModelQuery(basePayload.name);
    var requests = [
        fetchNoIdCandidates(basePayload).catch(function(){ return []; })
    ];
    if(compactQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            query: compactQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }
    if(modelQuery && modelQuery !== compactQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            query: modelQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }
    if(cpuQuery && cpuQuery !== compactQuery && cpuQuery !== modelQuery){
        requests.push(fetchNoIdCandidates({
            name: basePayload.name,
            category: basePayload.category,
            onliner_id: basePayload.onliner_id,
            query: cpuQuery,
            limit: 12
        }).catch(function(){ return []; }));
    }

    Promise.all(requests).then(function(results){
        state.loading = false;
        state.items = mergeVerifyIdCandidateLists(results, 12);
        state.message = state.items.length ? 'Выберите правильный ID.' : 'Подходящих кандидатов не найдено.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    }).catch(function(){
        state.loading = false;
        state.items = [];
        state.message = 'Ошибка поиска кандидатов.';
        renderVerifyAllIdsStatus({ items: verifyAllIdsItems, total: verifyAllIdsItems.length, done: verifyAllIdsItems.length, mismatched: verifyAllIdsItems.length });
    });
};

function normalizeTextForAiMatch(s){
    return String(s || '')
        .toLowerCase()
        .replace(/[^a-zа-я0-9\s\-\/]/gi, ' ')
            .replace(/\s+/g, ' ')
        .trim();
}

function tokenListForAiMatch(s){
    var stop = {
        'система':1,'охлаждения':1,'водяного':1,'для':1,'и':1,'the':1,'with':1,
        'black':1,'white':1,'черный':1,'чёрный':1,'белый':1,'argb':1,'rgb':1
    };
    return normalizeTextForAiMatch(s).split(' ').filter(function(t){
        return t && t.length >= 3 && !stop[t];
    });
}

function isAiTextMatch(localName, apiName){
    var lNorm = normalizeTextForAiMatch(localName);
    var aNorm = normalizeTextForAiMatch(apiName);
    if(!lNorm || !aNorm){ return false; }
    if(aNorm.length >= 12 && lNorm.indexOf(aNorm) >= 0){ return true; }
    var lTokens = tokenListForAiMatch(localName);
    var aTokens = tokenListForAiMatch(apiName);
    if(!lTokens.length || !aTokens.length){ return false; }
    var lSet = {};
    lTokens.forEach(function(t){ lSet[t] = 1; });
    var common = 0;
    aTokens.forEach(function(t){ if(lSet[t]){ common += 1; } });
    var overlap = common / Math.max(1, aTokens.length);
    return overlap >= 0.60 && common >= 2;
}

function runPreExportQualityCheck(){
    var card = document.getElementById('quality-check-card');
    var summary = document.getElementById('quality-check-summary');
    var details = document.getElementById('quality-check-details');
    if(card){ card.style.display = 'block'; }
    if(summary){ summary.textContent = 'Проверка качества выполняется...'; }
    if(details){ details.innerHTML = ''; }
    fetch('/api/preexport-quality-check').then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            if(summary){ summary.textContent = (d && d.message) ? d.message : 'Не удалось выполнить проверку качества.'; }
            return;
        }
        if(summary){
            summary.textContent = 'Проверено строк: ' + String(d.checked || 0)
                + '. Без ID: ' + String(d.missing_id_count || 0)
                + ', подозрительные цены: ' + String(d.suspicious_price_count || 0)
                + ', дубли: ' + String(d.duplicate_count || 0) + '.';
        }
        var html = '';
        function block(title, arr){
            var items = Array.isArray(arr) ? arr : [];
            if(!items.length){ return '<div style="margin-top:6px;"><b>' + title + ':</b> нет</div>'; }
            return '<div style="margin-top:8px;"><b>' + title + ':</b><ul style="margin:6px 0 0 18px;">'
                + items.map(function(it){ return '<li>' + escapeHtml(String(it)) + '</li>'; }).join('')
                + '</ul></div>';
        }
        html += block('Примеры подозрительных цен', d.suspicious_price_samples || []);
        html += block('Примеры дублей', d.duplicate_samples || []);
        if(details){ details.innerHTML = html; }
    }).catch(function(){
        if(summary){ summary.textContent = 'Ошибка запуска проверки качества.'; }
    });
}

function reapplySavedMarkupsFromQuality(){
    var summary = document.getElementById('quality-check-summary');
    var btn = document.getElementById('quality-reapply-markups-btn');
    if(summary){ summary.textContent = 'Доприменяю сохранённые наценки по категориям...'; }
    if(btn){ btn.disabled = true; }
    fetch('/api/reapply-saved-markups', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({source: 'quality_check'})
    }).then(function(r){
        return r.json().then(function(d){ return {ok:r.ok, data:d}; });
    }).then(function(resp){
        var d = resp.data || {};
        if(!resp.ok || d.status !== 'ok'){
            if(summary){ summary.textContent = d.message || 'Не удалось доприменить наценки.'; }
            if(btn){ btn.disabled = false; }
            return;
        }
        if(summary){
            summary.textContent = 'Наценки доприменены. Обновлено строк: ' + String(d.updated_rows || 0) + '. Перепроверяю...';
        }
        if(tblMain && tblMain.ajax && tblMain.ajax.reload){ tblMain.ajax.reload(null, false); }
        runPreExportQualityCheck();
        if(btn){ btn.disabled = false; }
    }).catch(function(){
        if(summary){ summary.textContent = 'Ошибка доприменения наценок.'; }
        if(btn){ btn.disabled = false; }
    });
}

function getSelectedValues(selectId){
    var sel = document.getElementById(selectId);
    return Array.from(sel.options).filter(function(o){ return o.selected; }).map(function(o){ return o.value; });
}

function getAllValues(selectId){
    var sel = document.getElementById(selectId);
    if(!sel){ return []; }
    return Array.from(sel.options).map(function(o){ return o.value; }).filter(function(v){ return !!v; });
}

function saveUiState(){
    var state = {
        categories: getSelectedValues('markup-categories'),
        percent: document.getElementById('markup-percent').value || '10',
        threshold: document.getElementById('markup-threshold').value || '0',
        minProfit: document.getElementById('markup-min-profit').value || '0',
        noDiscountPercent: document.getElementById('markup-no-discount-percent').value || '0',
        previewPercent: document.getElementById('preview-percent').value || '10',
        previewThreshold: document.getElementById('preview-threshold').value || '0',
        previewMinProfit: document.getElementById('preview-min-profit').value || '0',
        previewNoDiscountPercent: document.getElementById('preview-no-discount-percent').value || '0',
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

function formatRelativeSeconds(sec){
    var s = Math.max(0, Number(sec || 0));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    if(h > 0){ return h + 'ч ' + m + 'м'; }
    if(m > 0){ return m + 'м'; }
    return 'менее минуты';
}

function formatTs(ts){
    var n = Number(ts || 0);
    if(!n){ return '—'; }
    var d = new Date(n * 1000);
    if(isNaN(d.getTime())){ return '—'; }
    return d.toLocaleString('ru-RU');
}

function setAutoRefreshPoll(active){
    if(autoRefreshPollTimer){
        clearInterval(autoRefreshPollTimer);
        autoRefreshPollTimer = null;
    }
    if(active){
        autoRefreshPollTimer = setInterval(loadAutoRefreshSettings, 10000);
    }
}

function loadAutoRefreshSettings(){
    fetch('/api/auto-refresh-settings').then(function(r){ return r.json(); }).then(function(d){
        autoRefreshUiLock = true;
        var enabledEl = document.getElementById('auto-refresh-enabled');
        var intervalEl = document.getElementById('auto-refresh-interval');
        var noteEl = document.getElementById('auto-refresh-note');
        if(enabledEl){ enabledEl.checked = !!d.enabled; }
        if(intervalEl){ intervalEl.value = String(d.interval_hours || 12); }
        var statusMap = {
            'running': 'в работе',
            'ok': 'выполнено',
            'error': 'ошибка',
            'idle': 'ожидание'
        };
        var statusTxt = statusMap[String(d.last_status || 'idle')] || String(d.last_status || 'idle');
        var nextTxt = d.enabled ? ('следующий запуск через ' + formatRelativeSeconds(d.next_in_sec || 0)) : 'выключено';
        var lastTxt = formatTs(d.last_run_ts || 0);
        var cnt = Number(d.last_count || 0);
        var msg = String(d.last_message || '').trim();
        if(noteEl){
            noteEl.textContent = 'Статус: ' + statusTxt + '. Последний запуск: ' + lastTxt
                + '. Обновлено ID: ' + cnt + '. ' + nextTxt + (msg ? ('. ' + msg) : '');
        }
        autoRefreshUiLock = false;
    }).catch(function(){
        autoRefreshUiLock = false;
        var noteEl = document.getElementById('auto-refresh-note');
        if(noteEl){ noteEl.textContent = 'Не удалось получить статус автообновления.'; }
    });
}

function saveAutoRefreshSettings(){
    if(autoRefreshUiLock){ return; }
    var enabledEl = document.getElementById('auto-refresh-enabled');
    var intervalEl = document.getElementById('auto-refresh-interval');
    var enabled = !!(enabledEl && enabledEl.checked);
    var interval = Number((intervalEl && intervalEl.value) || 12);
    fetch('/api/auto-refresh-settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: enabled, interval_hours: interval})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status !== 'ok'){
            var noteEl = document.getElementById('auto-refresh-note');
            if(noteEl){ noteEl.textContent = d.message || 'Не удалось сохранить настройки автообновления.'; }
            return;
        }
        loadAutoRefreshSettings();
    }).catch(function(){
        var noteEl = document.getElementById('auto-refresh-note');
        if(noteEl){ noteEl.textContent = 'Ошибка сохранения настроек автообновления.'; }
    });
}

function initMarkupUI(){
    var state = loadUiState();
    if(state.percent){ document.getElementById('markup-percent').value = state.percent; }
    if(state.threshold){ document.getElementById('markup-threshold').value = state.threshold; }
    if(state.minProfit){ document.getElementById('markup-min-profit').value = state.minProfit; }
    if(state.noDiscountPercent){ document.getElementById('markup-no-discount-percent').value = state.noDiscountPercent; }
    if(state.previewPercent){ document.getElementById('preview-percent').value = state.previewPercent; }
    if(state.previewThreshold){ document.getElementById('preview-threshold').value = state.previewThreshold; }
    if(state.previewMinProfit){ document.getElementById('preview-min-profit').value = state.previewMinProfit; }
    if(state.previewNoDiscountPercent){ document.getElementById('preview-no-discount-percent').value = state.previewNoDiscountPercent; }
    if(state.previewBaseMode){ document.getElementById('preview-base-mode').value = state.previewBaseMode; }
    loadCategoryMarkups();
    loadCategories(state.categories || []);
    loadSuppliers();
    loadAutoRefreshSettings();
    document.getElementById('open-pricing-btn').addEventListener('click', function(){
        document.getElementById('pricing-modal').classList.add('active');
        loadAutoRefreshSettings();
        setAutoRefreshPoll(true);
    });
    ensureQualityCheckCardUI();
    document.getElementById('run-quality-check-btn').addEventListener('click', runPreExportQualityCheck);
    var qualityToggleBtn = document.getElementById('toggle-quality-check-card-btn');
    if(qualityToggleBtn){
        qualityToggleBtn.onclick = function(){
            toggleQualityCheckCard();
        };
    }
    document.getElementById('quality-reapply-markups-btn').addEventListener('click', reapplySavedMarkupsFromQuality);
    document.getElementById('close-pricing-btn').addEventListener('click', function(){
        document.getElementById('pricing-modal').classList.remove('active');
        setAutoRefreshPoll(false);
    });
    document.getElementById('pricing-modal').addEventListener('click', function(e){
        if(e.target.id === 'pricing-modal'){
            this.classList.remove('active');
            setAutoRefreshPoll(false);
        }
    });
    document.getElementById('auto-refresh-enabled').addEventListener('change', saveAutoRefreshSettings);
    document.getElementById('auto-refresh-interval').addEventListener('change', saveAutoRefreshSettings);
    document.getElementById('apply-markup-btn').addEventListener('click', applyMarkup);
    document.getElementById('supplier-select').addEventListener('change', loadSupplierCategories);
    document.getElementById('hide-cats-btn').addEventListener('click', function(){ setCategoryVisibility(true); });
    document.getElementById('show-cats-btn').addEventListener('click', function(){ setCategoryVisibility(false); });
    document.getElementById('markup-categories').addEventListener('change', function(){ applyStoredPercentForSelection(); syncPreviewModalCategorySelector(); saveUiState(); requestPreview(); });
    document.getElementById('markup-percent').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-threshold').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-min-profit').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-no-discount-percent').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('preview-move-btn').addEventListener('click', moveSelectedItemsToCategory);
    document.getElementById('preview-target-category').addEventListener('change', saveUiState);
    document.getElementById('target-category-search').addEventListener('input', function(){ filterTargetCategories('preview-target-category', this.value); });
    document.getElementById('close-full-list-btn').addEventListener('click', closeFullListModal);
    document.getElementById('full-list-modal').addEventListener('click', function(e){
        if(e.target.id === 'full-list-modal'){ closeFullListModal(); }
    });
    document.getElementById('open-autosort-btn').addEventListener('click', openAutoSortModal);
    document.getElementById('close-autosort-btn').addEventListener('click', closeAutoSortModal);
    document.getElementById('autosort-modal').addEventListener('click', function(e){
        if(e.target.id === 'autosort-modal'){ closeAutoSortModal(); }
    });
    document.getElementById('autosort-select-all-btn').addEventListener('click', function(){
        autoSortItems.forEach(function(it){
            var key = String((it || {}).item_key || '');
            if(key){ autoSortSelectedKeys[key] = true; }
        });
        renderAutoSortRows();
    });
    document.getElementById('autosort-clear-btn').addEventListener('click', function(){
        autoSortSelectedKeys = {};
        renderAutoSortRows();
    });
    document.getElementById('autosort-apply-btn').addEventListener('click', applyAutoSortSelection);
    document.getElementById('autosort-body').addEventListener('click', function(e){
        var tr = e.target.closest('tr[data-key]');
        if(!tr){ return; }
        var key = String(tr.getAttribute('data-key') || '');
        if(!key){ return; }
        if(e.target && e.target.matches('input[type="checkbox"]')){
            if(e.target.checked){ autoSortSelectedKeys[key] = true; }
            else { delete autoSortSelectedKeys[key]; }
            renderAutoSortRows();
            return;
        }
        if(autoSortSelectedKeys[key]){ delete autoSortSelectedKeys[key]; }
        else { autoSortSelectedKeys[key] = true; }
        renderAutoSortRows();
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
    document.getElementById('preview-threshold').addEventListener('input', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-min-profit').addEventListener('input', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-no-discount-percent').addEventListener('input', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-base-mode').addEventListener('change', function(){
        saveUiState();
        renderPreviewModalRows();
    });
    document.getElementById('preview-apply-btn').addEventListener('click', function(){
        var previewSelected = getSelectedValues('preview-modal-categories');
        if(previewSelected.length){
            applySelection('markup-categories', previewSelected);
            syncPreviewModalCategorySelector();
        }
        document.getElementById('markup-percent').value = document.getElementById('preview-percent').value || '0';
        document.getElementById('markup-threshold').value = document.getElementById('preview-threshold').value || '0';
        document.getElementById('markup-min-profit').value = document.getElementById('preview-min-profit').value || '0';
        document.getElementById('markup-no-discount-percent').value = document.getElementById('preview-no-discount-percent').value || '0';
        applyMarkup();
    });
    document.getElementById('refresh-market-btn').addEventListener('click', startMarketRefresh);
    document.getElementById('open-offers-btn').addEventListener('click', openOffersModal);
    document.getElementById('close-offers-btn').addEventListener('click', closeOffersModal);
    document.getElementById('offers-modal').addEventListener('click', function(e){
        if(e.target.id === 'offers-modal'){ closeOffersModal(); }
    });
    document.querySelector('#preview-full-table tbody').addEventListener('click', function(e){
        var tr = e.target.closest('tr[data-row-idx]');
        if(!tr){ return; }
        setSelectedPreviewRow(parseInt(tr.getAttribute('data-row-idx') || '-1', 10));
    });
    document.getElementById('preview-modal-categories').addEventListener('change', function(){
        applyStoredPercentForPreviewSelection();
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

function getCategoryMarkupConfigJs(category){
    var raw = (categoryMarkups || {})[category];
    if(raw && typeof raw === 'object' && !Array.isArray(raw)){
        var percent = Number(raw.percent);
        var threshold = Number(raw.threshold);
        var minProfit = Number(raw.min_profit);
        var noDiscountPercent = Number(raw.no_discount_percent);
        return {
            percent: isNaN(percent) ? null : percent,
            threshold: isNaN(threshold) ? 0 : threshold,
            min_profit: isNaN(minProfit) ? 0 : minProfit,
            no_discount_percent: isNaN(noDiscountPercent) ? 0 : noDiscountPercent,
            base_mode: String(raw.base_mode || 'wholesale')
        };
    }
    var percentLegacy = Number(raw);
    return {
        percent: isNaN(percentLegacy) ? null : percentLegacy,
        threshold: 0,
        min_profit: 0,
        no_discount_percent: 0,
        base_mode: 'wholesale'
    };
}

function renderCategoryMarkupTable(){
    var tbody = document.querySelector('#category-markup-table tbody');
    if(!tbody){ return; }
    var names = Object.keys(categoryMarkups || {}).sort(compareCategoriesByUiOrder);
    tbody.innerHTML = '';
    if(!names.length){
        var trEmpty = document.createElement('tr');
        trEmpty.innerHTML = '<td colspan="6" style="color:#6b7280;">Наценки по категориям пока не заданы.</td>';
        tbody.appendChild(trEmpty);
        return;
    }
    names.forEach(function(name){
        var tr = document.createElement('tr');
        var cfg = getCategoryMarkupConfigJs(name);
        var val = Number(cfg.percent);
        var baseMap = {
            wholesale: 'Опт',
            onliner_min: 'Onliner Мин',
            onliner_avg: 'Onliner Ср',
            onliner_max: 'Onliner Макс'
        };
        tr.innerHTML = '<td>' + name + '</td>'
            + '<td>' + (isNaN(val) ? '' : val.toFixed(2)) + '</td>'
            + '<td>' + Number(cfg.threshold || 0).toFixed(2) + '</td>'
            + '<td>' + Number(cfg.min_profit || 0).toFixed(2) + '</td>'
            + '<td>' + Number(cfg.no_discount_percent || 0).toFixed(2) + '</td>'
            + '<td>' + escapeHtml(baseMap[cfg.base_mode] || 'Опт') + '</td>';
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
    var configs = selected.map(getCategoryMarkupConfigJs).filter(function(v){ return v && v.percent !== null; });
    var vals = configs.map(function(v){ return v.percent; });
    if(!vals.length){ return; }
    var allSame = vals.every(function(v){ return Number(v) === Number(vals[0]); });
    if(allSame){
        var value = Number(vals[0]);
        document.getElementById('markup-percent').value = value;
        document.getElementById('preview-percent').value = value;
    }
    var profits = configs.map(function(v){ return Number(v.min_profit || 0); });
    var thresholds = configs.map(function(v){ return Number(v.threshold || 0); });
    var noDiscountPercents = configs.map(function(v){ return Number(v.no_discount_percent || 0); });
    if(thresholds.length && thresholds.every(function(v){ return Number(v) === Number(thresholds[0]); })){
        document.getElementById('markup-threshold').value = Number(thresholds[0]);
        document.getElementById('preview-threshold').value = Number(thresholds[0]);
    }
    if(profits.length && profits.every(function(v){ return Number(v) === Number(profits[0]); })){
        document.getElementById('markup-min-profit').value = Number(profits[0]);
        document.getElementById('preview-min-profit').value = Number(profits[0]);
    }
    if(noDiscountPercents.length && noDiscountPercents.every(function(v){ return Number(v) === Number(noDiscountPercents[0]); })){
        document.getElementById('markup-no-discount-percent').value = Number(noDiscountPercents[0]);
        document.getElementById('preview-no-discount-percent').value = Number(noDiscountPercents[0]);
    }
    var modes = configs.map(function(v){ return v.base_mode || 'wholesale'; });
    if(modes.length && modes.every(function(v){ return v === modes[0]; })){
        document.getElementById('preview-base-mode').value = modes[0];
    }
}

function applyStoredPercentForPreviewSelection(){
    var selected = getSelectedValues('preview-modal-categories');
    if(!selected.length){ selected = getSelectedValues('markup-categories'); }
    if(!selected.length){ return; }
    var configs = selected.map(getCategoryMarkupConfigJs).filter(function(v){ return v && v.percent !== null; });
    var vals = configs.map(function(v){ return v.percent; });
    if(!vals.length){ return; }
    var allSame = vals.every(function(v){ return Number(v) === Number(vals[0]); });
    if(allSame){
        document.getElementById('preview-percent').value = Number(vals[0]);
    }
    var thresholds = configs.map(function(v){ return Number(v.threshold || 0); });
    if(thresholds.length && thresholds.every(function(v){ return Number(v) === Number(thresholds[0]); })){
        document.getElementById('preview-threshold').value = Number(thresholds[0]);
    }
    var profits = configs.map(function(v){ return Number(v.min_profit || 0); });
    var noDiscountPercents = configs.map(function(v){ return Number(v.no_discount_percent || 0); });
    if(profits.length && profits.every(function(v){ return Number(v) === Number(profits[0]); })){
        document.getElementById('preview-min-profit').value = Number(profits[0]);
    }
    if(noDiscountPercents.length && noDiscountPercents.every(function(v){ return Number(v) === Number(noDiscountPercents[0]); })){
        document.getElementById('preview-no-discount-percent').value = Number(noDiscountPercents[0]);
    }
    var modes = configs.map(function(v){ return v.base_mode || 'wholesale'; });
    if(modes.length && modes.every(function(v){ return v === modes[0]; })){
        document.getElementById('preview-base-mode').value = modes[0];
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
        var available = new Set(categories.map(function(c){ return c.name; }));
        var desired = (preselected && preselected.length) ? preselected : (loadUiState().categories || []);
        desired = desired.filter(function(name){ return available.has(name); });
        applySelection('markup-categories', desired);
        syncPreviewModalCategorySelector();
        applyStoredPercentForSelection();
        saveUiState();
        document.getElementById('markup-note').textContent = categories.length
            ? 'Выберите категории и процент. Будут пересчитаны колонки "РРЦ" и "Цена без скидки".'
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
    var threshold = parseFloat(document.getElementById('markup-threshold').value);
    var minProfit = parseFloat(document.getElementById('markup-min-profit').value);
    var noDiscountPercent = parseFloat(document.getElementById('markup-no-discount-percent').value);
    if(isNaN(percent) || percent < 0){
        document.getElementById('markup-note').textContent = 'Укажите корректный процент наценки (>= 0).';
        return;
    }
    if(isNaN(threshold) || threshold < 0){ threshold = 0; }
    if(isNaN(minProfit) || minProfit < 0){ minProfit = 0; }
    if(isNaN(noDiscountPercent) || noDiscountPercent < 0){ noDiscountPercent = 0; }
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
        body: JSON.stringify({categories: selected, percent: percent, threshold: threshold, min_profit: minProfit, no_discount_percent: noDiscountPercent, base_mode: baseMode})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'ok'){
            document.getElementById('markup-note').textContent =
                'Готово. Обновлено: ' + d.updated + ' из ' + (d.eligible || 0) +
                ' подходящих (всего в прайсе: ' + (d.total || 0) + '). База: ' + (d.base_mode || 'wholesale')
                + '. Порог опта: ' + Number(d.threshold || 0).toFixed(2)
                + '. Мин. прибыль: ' + Number(d.min_profit || 0).toFixed(2)
                + '. Без скидки: ' + Number(d.no_discount_percent || 0).toFixed(2) + '%.';
            selected.forEach(function(c){
                categoryMarkups[c] = {
                    percent: d.percent,
                    threshold: d.threshold || 0,
                    min_profit: d.min_profit || 0,
                    no_discount_percent: d.no_discount_percent || 0,
                    base_mode: d.base_mode || 'wholesale'
                };
            });
            document.getElementById('preview-percent').value = d.percent;
            document.getElementById('preview-threshold').value = d.threshold || 0;
            document.getElementById('preview-min-profit').value = d.min_profit || 0;
            document.getElementById('preview-no-discount-percent').value = d.no_discount_percent || 0;
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

function openAutoSortModal(){
    document.getElementById('autosort-modal').classList.add('active');
    loadAutoSortPreview();
}

function closeAutoSortModal(){
    document.getElementById('autosort-modal').classList.remove('active');
}

function loadAutoSortPreview(){
    var note = document.getElementById('autosort-note');
    var tbody = document.getElementById('autosort-body');
    var categories = getSelectedValues('markup-categories');
    autoSortItems = [];
    autoSortSelectedKeys = {};
    if(tbody){
        tbody.innerHTML = '<tr><td colspan="7" style="color:#64748b;">Собираю предложения...</td></tr>';
    }
    if(note){ note.textContent = 'Собираю AI-предложения по категориям...'; }
    fetch('/api/category-autosort-preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories})
    }).then(function(r){ return r.json(); }).then(function(d){
        autoSortItems = Array.isArray(d.items) ? d.items : [];
        autoSortItems.forEach(function(it){
            var key = String((it || {}).item_key || '');
            if(key){ autoSortSelectedKeys[key] = true; }
        });
        renderAutoSortRows();
        if(note){
            note.textContent = 'Найдено предложений: ' + autoSortItems.length
                + '. Проверено строк: ' + Number(d.checked || 0)
                + '. Пропущено (ручные/скрытые/без ID): ' + Number(d.skipped || 0)
                + '. AI проверил: ' + Number(d.ai_checked || 0)
                + ', AI предложил: ' + Number(d.ai_suggested || 0)
                + (Number(d.ai_unavailable || 0) > 0 ? ', AI ключ не задан.' : '')
                + '.';
        }
    }).catch(function(){
        autoSortItems = [];
        autoSortSelectedKeys = {};
        renderAutoSortRows();
        if(note){ note.textContent = 'Не удалось собрать предложения автосортировки.'; }
    });
}

function renderAutoSortRows(){
    var tbody = document.getElementById('autosort-body');
    if(!tbody){ return; }
    tbody.innerHTML = '';
    if(!autoSortItems.length){
        tbody.innerHTML = '<tr><td colspan="7" style="color:#64748b;">Нет предложений. Либо все уже отсортировано, либо для выбранных категорий нет совпадений по ID.</td></tr>';
        return;
    }
    autoSortItems.forEach(function(it){
        var key = String((it || {}).item_key || '');
        var checked = !!autoSortSelectedKeys[key];
        var tr = document.createElement('tr');
        tr.setAttribute('data-key', key);
        if(checked){ tr.classList.add('autosort-row-selected'); }
        var source = String(it.source || 'id');
        var affectedRows = Number(it.affected_rows || 1);
        tr.innerHTML = ''
            + '<td class="autosort-check-cell"><input type="checkbox" ' + (checked ? 'checked' : '') + '></td>'
            + '<td>' + escapeHtml(String(it.onliner_id || '')) + '</td>'
            + '<td>' + escapeHtml(String(it.name || ''))
            + '<div style="color:#64748b;font-size:12px;margin-top:3px;">строк: ' + affectedRows + '</div></td>'
            + '<td>' + escapeHtml(String(it.supplier || '')) + '</td>'
            + '<td>' + escapeHtml(String(it.current_category || '')) + '</td>'
            + '<td>' + escapeHtml(String(it.target_category || '')) + '</td>'
            + '<td>' + escapeHtml(source) + '</td>';
        tbody.appendChild(tr);
    });
}

function applyAutoSortSelection(){
    var note = document.getElementById('autosort-note');
    var btn = document.getElementById('autosort-apply-btn');
    var selected = [];
    autoSortItems.forEach(function(it){
        var key = String((it || {}).item_key || '');
        if(!key || !autoSortSelectedKeys[key]){ return; }
        selected.push({
            item_key: key,
            target_category: String(it.target_category || '')
        });
    });
    if(!selected.length){
        if(note){ note.textContent = 'Выберите хотя бы одно предложение для применения.'; }
        return;
    }
    var preserveCats = getSelectedValues('markup-categories');
    if(btn){
        btn.disabled = true;
        btn.textContent = 'Применение...';
    }
    if(note){ note.textContent = 'Применяю автосортировку...'; }
    fetch('/api/category-autosort-apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({items: selected})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status !== 'ok'){
            if(note){ note.textContent = d.message || 'Не удалось применить автосортировку.'; }
            return;
        }
        if(note){
            note.textContent = 'Готово. Обновлено ключей: ' + Number(d.updated_keys || 0)
                + ', строк в прайсе: ' + Number(d.updated_rows || 0) + '.';
        }
        loadAutoSortPreview();
        loadCategories(preserveCats);
        loadSupplierCategories();
        loadTargetCategoryCatalog();
        requestPreview();
        if(document.getElementById('preview-modal').classList.contains('active')){
            loadPreviewModalItems();
        }
        if(document.getElementById('full-list-modal').classList.contains('active')){
            loadFullListItems();
        }
        if(tblMain){ tblMain.ajax.reload(null, false); }
    }).catch(function(){
        if(note){ note.textContent = 'Ошибка связи с сервером при автосортировке.'; }
    }).finally(function(){
        if(btn){
            btn.disabled = false;
            btn.textContent = 'Применить Выбранные';
        }
    });
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
    if(v <= 0){ return 0.00; }
    return Math.floor(v);
}

function ensurePreviewTableLayout(){
    var table = document.getElementById('preview-full-table');
    if(!table){ return; }
    var thead = table.querySelector('thead');
    if(!thead){ return; }
    thead.innerHTML = '<tr>'
        + '<th>OnlinerID</th>'
        + '<th>Категория</th>'
        + '<th>Товар</th>'
        + '<th>Поставщик</th>'
        + '<th>Опт</th>'
        + '<th>Onliner Мин</th>'
        + '<th>Onliner Ср</th>'
        + '<th>Onliner Макс</th>'
        + '<th>РРЦ</th>'
        + '<th>Цена без скидки</th>'
        + '<th>Маржа, %</th>'
        + '<th>Правило</th>'
        + '</tr>';
    var tbody = table.querySelector('tbody');
    if(tbody){
        Array.from(tbody.rows).forEach(function(row){
            while(row.cells.length > 12){
                row.deleteCell(9);
            }
        });
    }
}

function openPreviewModal(){
    var categories = getSelectedValues('markup-categories');
    if(!categories.length){
        document.getElementById('markup-note').textContent = 'Сначала выберите хотя бы одну категорию.';
        return;
    }
    ensurePreviewTableLayout();
    document.getElementById('preview-percent').value = document.getElementById('markup-percent').value || '0';
    document.getElementById('preview-threshold').value = document.getElementById('markup-threshold').value || '0';
    document.getElementById('preview-min-profit').value = document.getElementById('markup-min-profit').value || '0';
    document.getElementById('preview-no-discount-percent').value = document.getElementById('markup-no-discount-percent').value || '0';
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

function setSelectedPreviewRow(idx){
    selectedPreviewRowIdx = idx;
    document.querySelectorAll('#preview-full-table tbody tr[data-row-idx]').forEach(function(tr){
        tr.classList.toggle('preview-row-selected', Number(tr.getAttribute('data-row-idx')) === idx);
    });
}

function closeOffersModal(){
    document.getElementById('offers-modal').classList.remove('active');
}

function setPreviewModalLoading(isLoading){
    var sheet = document.querySelector('#preview-modal .preview-sheet');
    if(!sheet){ return; }
    sheet.classList.toggle('preview-loading', !!isLoading);
}

function openOffersModal(){
    var note = document.getElementById('offers-note');
    var current = document.getElementById('offers-current-note');
    var tbody = document.getElementById('offers-body');
    var summary = document.getElementById('offers-summary');
    if(selectedPreviewRowIdx < 0 || selectedPreviewRowIdx >= previewModalItems.length){
        note.textContent = 'Сначала выберите товар в таблице предпросмотра.';
        document.getElementById('offers-modal').classList.add('active');
        return;
    }
    var item = previewModalItems[selectedPreviewRowIdx] || {};
    var oid = String(item.onliner_id || '').trim();
    current.textContent = 'Товар: ' + String(item.name || '') + ' | OnlinerID: ' + (oid || 'нет');
    if(!oid){
        note.textContent = 'У выбранного товара нет OnlinerID.';
        tbody.innerHTML = '<tr><td colspan="7" style="color:#64748b;">Нет данных</td></tr>';
        document.getElementById('offers-modal').classList.add('active');
        return;
    }
    note.textContent = 'Загружаю офферы Onliner...';
    tbody.innerHTML = '<tr><td colspan="7" style="color:#64748b;">Загрузка...</td></tr>';
    summary.innerHTML = ''
        + '<div class="offers-stat"><div class="k">OnlinerID</div><div class="v">' + escapeHtml(oid) + '</div></div>'
        + '<div class="offers-stat"><div class="k">API offers.count</div><div class="v">—</div></div>'
        + '<div class="offers-stat"><div class="k">Позиции в API</div><div class="v">—</div></div>'
        + '<div class="offers-stat"><div class="k">Уникальные магазины</div><div class="v">—</div></div>';
    document.getElementById('offers-modal').classList.add('active');
    fetch('/api/onliner-offers/' + encodeURIComponent(oid))
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.status !== 'ok'){ throw new Error(d.message || 'offer load failed'); }
            summary.innerHTML = ''
                + '<div class="offers-stat"><div class="k">OnlinerID</div><div class="v">' + escapeHtml(oid) + '</div></div>'
                + '<div class="offers-stat"><div class="k">API offers.count</div><div class="v">' + Number(d.offers_count || 0) + '</div></div>'
                + '<div class="offers-stat"><div class="k">Позиции в API</div><div class="v">' + Number(d.positions_count || 0) + '</div></div>'
                + '<div class="offers-stat"><div class="k">Уникальные магазины</div><div class="v">' + Number(d.unique_sellers_count || 0) + '</div></div>';
            note.textContent = d.note || 'Проверка офферов выполнена.';
            var rows = Array.isArray(d.offers) ? d.offers : [];
            if(!rows.length){
                tbody.innerHTML = '<tr><td colspan="7" style="color:#64748b;">API не вернул детализацию офферов.</td></tr>';
                return;
            }
            var html = '';
            rows.forEach(function(it){
                var sellerCell = escapeHtml(it.seller_name || '—');
                if(it.seller_url){
                    sellerCell = '<a href="' + escapeHtml(it.seller_url) + '" target="_blank" rel="noopener noreferrer">' + sellerCell + '</a>';
                }
                html += '<tr>'
                    + '<td>' + sellerCell + '</td>'
                    + '<td>' + escapeHtml(it.seller_id || '') + '</td>'
                    + '<td>' + escapeHtml((it.price || it.price === 0) ? Number(it.price).toFixed(2) : '') + '</td>'
                    + '<td>' + escapeHtml(it.warranty || '') + '</td>'
                    + '<td>' + escapeHtml(it.stock || '') + '</td>'
                    + '<td>' + escapeHtml((it.updated_at || '').replace('T', ' ').replace('+03:00', '')) + '</td>'
                    + '<td>' + (it.url ? ('<a href="' + escapeHtml(it.url) + '" target="_blank" rel="noopener noreferrer">Открыть</a>') : '') + '</td>'
                    + '</tr>';
            });
            tbody.innerHTML = html;
        })
        .catch(function(err){
            note.textContent = 'Не удалось загрузить офферы: ' + (err && err.message ? err.message : 'ошибка');
            tbody.innerHTML = '<tr><td colspan="7" style="color:#b91c1c;">Ошибка загрузки офферов.</td></tr>';
        });
}

function loadPreviewModalItems(options){
    options = options || {};
    var marketOnly = !!options.marketOnly;
    var categories = getSelectedValues('preview-modal-categories');
    if(!categories.length){ categories = getSelectedValues('markup-categories'); }
    var note = document.getElementById('preview-modal-note');
    var requestSeq = ++previewModalRequestSeq;
    var previousMarketMap = buildPreviewMarketMap(previewModalItems);
    if(!categories.length){
        previewModalItems = [];
        selectedPreviewRowIdx = -1;
        renderPreviewModalRows();
        note.textContent = 'Выберите хотя бы одну категорию в основном блоке.';
        setPreviewModalLoading(false);
        return;
    }
    setPreviewModalLoading(true);
    note.textContent = marketOnly ? 'Обновляю цены Onliner...' : 'Переключаю категории...';
    var catsPreview = categories.slice(0, 4).join(', ') + (categories.length > 4 ? '...' : '');
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, limit: 10000, with_market: true, allow_stale_market: true, max_market_checks: 400})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(requestSeq !== previewModalRequestSeq){ return; }
        previewModalItems = applyPreviewMarketTrend((d.items || []), previousMarketMap);
        selectedPreviewRowIdx = -1;
        renderPreviewModalRows();
        var allMissing = previewModalItems.length > 0 && previewModalItems.every(function(it){
            return !it.market_min && !it.market_avg && !it.market_max;
        });
        note.textContent = 'Категории: ' + catsPreview + '. Показано товаров: ' + previewModalItems.length
            + '. Onliner проверено: ' + (d.market_checked || 0)
            + ', без данных по ID: ' + (d.missing_market_ids || 0)
            + ', без OnlinerID: ' + (d.no_onliner_id || 0)
            + '. Цены Onliner показаны если есть хотя бы 1 конкурент.'
            + (allMissing ? ' Сейчас API/кэш не вернули рыночные цены ни по одному товару.' : '');
        setPreviewModalLoading(false);
    }).catch(function(){
        if(requestSeq !== previewModalRequestSeq){ return; }
        note.textContent = 'Не удалось загрузить данные для предпросмотра.';
        setPreviewModalLoading(false);
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

function formatMarketCell(value, trend, competitors, wholesale){
    var marketValue = Number(value);
    if(!isFinite(marketValue)){ return ''; }
    var txt = String(value);
    var cnt = Number(competitors || 0);
    var baseWholesale = Number(wholesale);
    var pctClass = 'preview-market-pct-neutral';
    var pctText = '';
    if(isFinite(marketValue) && isFinite(baseWholesale) && baseWholesale > 0){
        var pct = ((marketValue - baseWholesale) / baseWholesale) * 100;
        pctText = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        if(pct > 0.01){ pctClass = 'preview-market-pct-positive'; }
        else if(pct < -0.01){ pctClass = 'preview-market-pct-negative'; }
    }
    var meta = '';
    if(cnt > 0){
        meta += '<span class="preview-market-badge">' + cnt + '</span>';
    }
    if(pctText){
        meta += '<span class="preview-market-pct ' + pctClass + '">' + pctText + '</span>';
    }
    return '<div class="preview-market-cell">'
        + '<div class="preview-market-value">' + txt + formatMarketTrend(trend) + '</div>'
        + (meta ? '<div class="preview-market-meta">' + meta + '</div>' : '')
        + '</div>';
}

function startMarketRefresh(){
    var categories = getAllValues('preview-modal-categories');
    if(!categories.length){ categories = getAllValues('markup-categories'); }
    var note = document.getElementById('market-refresh-note');
    var btn = document.getElementById('refresh-market-btn');
    if(!categories.length){
        note.textContent = 'Сначала выберите категории для обновления цен.';
        return;
    }
    btn.disabled = true;
    btn.classList.add('is-updating');
    btn.style.setProperty('--progress', '0%');
    btn.textContent = 'Обновление 0%';
    fetch('/api/market-refresh-start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(d.status === 'started' || d.status === 'already_running'){
            renderMarketRefreshTable({categories:{}});
            pollMarketRefreshStatus();
        } else {
            note.textContent = d.message || 'Не удалось запустить обновление цен.';
            btn.disabled = false;
            btn.classList.remove('is-updating');
            btn.style.setProperty('--progress', '0%');
            btn.textContent = 'Обновить Цены Onliner';
        }
    }).catch(function(){
        note.textContent = 'Ошибка запуска обновления цен.';
        btn.disabled = false;
        btn.classList.remove('is-updating');
        btn.style.setProperty('--progress', '0%');
        btn.textContent = 'Обновить Цены Onliner';
    });
}

function renderMarketRefreshTable(d){
    return;
}

function pollMarketRefreshStatus(){
    if(marketRefreshPollTimer){ clearTimeout(marketRefreshPollTimer); }
    var note = document.getElementById('market-refresh-note');
    var btn = document.getElementById('refresh-market-btn');
    fetch('/api/market-refresh-status').then(function(r){ return r.json(); }).then(function(d){
        var cats = d.categories || {};
        renderMarketRefreshTable(d);
        btn.classList.add('is-updating');
        btn.style.setProperty('--progress', String(d.overall_percent || 0) + '%');
        btn.textContent = 'Обновление ' + String(d.overall_percent || 0) + '%';
        var lines = Object.keys(cats).sort(compareCategoriesByUiOrder).map(function(name){
            var s = cats[name];
            var part = name + ': ' + (s.percent || 0) + '% (' + (s.done || 0) + '/' + (s.total || 0) + ')';
            if((s.errors || 0) > 0){
                part += ', ошибок: ' + (s.errors || 0);
            }
            return part;
        });
        var recentErrors = (d.recent_errors || []).slice(-6);
        var html = 'Обновление кэша Onliner: ' + (d.overall_percent || 0) + '% (' + (d.done || 0) + '/' + (d.total || 0) + '), успешно: ' + (d.success || 0) + ', ошибок: ' + (d.errors || 0) + '.';
        if(lines.length){
            html += '<br>Категории: ' + lines.join(' | ');
        }
        if(recentErrors.length){
            html += '<br>Лог ошибок: ' + recentErrors.map(escapeHtml).join(' | ');
        }
        note.innerHTML = html;
        if(d.running){
            marketRefreshPollTimer = setTimeout(pollMarketRefreshStatus, 1200);
            return;
        }
        btn.disabled = false;
        btn.classList.remove('is-updating');
        btn.style.setProperty('--progress', '100%');
        btn.textContent = 'Обновить Цены Onliner';
        var doneHtml = 'Кэш Onliner обработан: ' + (d.done || 0) + ' товаров, успешно: ' + (d.success || 0) + ', ошибок: ' + (d.errors || 0) + '. Обновляю предпросмотр...';
        if(lines.length){
            doneHtml += '<br>Категории: ' + lines.join(' | ');
        }
        if(recentErrors.length){
            doneHtml += '<br>Лог ошибок: ' + recentErrors.map(escapeHtml).join(' | ');
        }
        note.innerHTML = doneHtml;
        loadPreviewModalItems({marketOnly:true});
    }).catch(function(){
        btn.disabled = false;
        btn.classList.remove('is-updating');
        btn.style.setProperty('--progress', '0%');
        btn.textContent = 'Обновить Цены Onliner';
        note.textContent = 'Ошибка чтения прогресса обновления.';
    });
}

function renderPreviewModalRows(){
    ensurePreviewTableLayout();
    var tbody = document.querySelector('#preview-full-table tbody');
    var percent = Number(document.getElementById('preview-percent').value);
    var threshold = Number(document.getElementById('preview-threshold').value);
    var minProfit = Number(document.getElementById('preview-min-profit').value);
    var noDiscountPercent = Number(document.getElementById('preview-no-discount-percent').value);
    var baseMode = document.getElementById('preview-base-mode').value || 'wholesale';
    if(!isFinite(percent) || percent < 0){ percent = 0; }
    if(!isFinite(threshold) || threshold < 0){ threshold = 0; }
    if(!isFinite(minProfit) || minProfit < 0){ minProfit = 0; }
    if(!isFinite(noDiscountPercent) || noDiscountPercent < 0){ noDiscountPercent = 0; }
    tbody.innerHTML = '';
    var sortedItems = (previewModalItems || []).slice().sort(function(a, b){
        var av = Number(a && a.price);
        var bv = Number(b && b.price);
        var aOk = isFinite(av);
        var bOk = isFinite(bv);
        if(aOk && bOk && av !== bv){ return av - bv; }
        if(aOk && !bOk){ return -1; }
        if(!aOk && bOk){ return 1; }
        return String((a && a.name) || '').localeCompare(String((b && b.name) || ''), 'ru');
    });
    sortedItems.forEach(function(it){
        var wholesale = Number(it.price);
        var marketMin = Number(it.market_min);
        var marketAvg = Number(it.market_avg);
        var marketMax = Number(it.market_max);
        var hasMarketMin = isFinite(marketMin);
        var hasMarketAvg = isFinite(marketAvg);
        var hasMarketMax = isFinite(marketMax);
        var hasWholesale = isFinite(wholesale);
        var basePrice = hasWholesale ? wholesale : NaN;
        if(baseMode === 'onliner_min'){
            basePrice = hasMarketMin ? marketMin : NaN;
        } else if(baseMode === 'onliner_avg'){
            basePrice = hasMarketAvg ? marketAvg : NaN;
        } else if(baseMode === 'onliner_max'){
            basePrice = hasMarketMax ? marketMax : NaN;
        }
        var newRrc = '';
        var noDiscountPrice = '';
        var appliedRule = '%';
        if(isFinite(basePrice)){
            var priceByPercent = basePrice * (1 + percent / 100);
            var finalCandidate = priceByPercent;
            if(hasWholesale && threshold > 0 && wholesale <= threshold){
                var priceByMinProfit = wholesale + minProfit;
                if(isFinite(priceByMinProfit) && priceByMinProfit > finalCandidate){
                    finalCandidate = priceByMinProfit;
                    appliedRule = 'Мин. прибыль';
                }
            }
            newRrc = roundPriceTo90(finalCandidate);
            if(isFinite(newRrc)){
                noDiscountPrice = roundPriceTo90(newRrc * (1 + noDiscountPercent / 100));
            }
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
        tr.setAttribute('data-row-idx', String(tbody.children.length));
        var minTxt = formatMarketCell(it.market_min, it.market_trend_min, it.min_competitors, wholesale);
        var avgTxt = formatMarketCell(it.market_avg, it.market_trend_avg, it.avg_competitors, wholesale);
        var maxTxt = formatMarketCell(it.market_max, it.market_trend_max, it.market_offers, wholesale);
        tr.innerHTML = '<td>' + (it.onliner_id || '') + '</td>'
            + '<td>' + it.category + '</td>'
            + '<td>' + it.name + '</td>'
            + '<td>' + it.supplier + '</td>'
            + '<td class="preview-price-cell">' + (it.price || '') + '</td>'
            + '<td>' + minTxt + '</td>'
            + '<td>' + avgTxt + '</td>'
            + '<td>' + maxTxt + '</td>'
            + '<td class="preview-price-cell"><b style="color:' + rrcColor + '">' + (newRrc === '' ? '—' : Number(newRrc).toFixed(2)) + '</b></td>'
            + '<td class="preview-price-cell">' + (noDiscountPrice === '' ? '—' : Number(noDiscountPrice).toFixed(2)) + '</td>'
            + '<td class="preview-price-cell">' + (marginPct === '' ? '' : Number(marginPct).toFixed(2)) + '</td>'
            + '<td class="preview-price-cell">' + escapeHtml(appliedRule) + '</td>';
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

// ============================================================
// ─── Проверка ID через API ────────────────────────────────────────────────
(function(){
    var startBtn    = document.getElementById('validate-ids-start-btn');
    var startDbBtn  = document.getElementById('validate-ids-db-start-btn');
    var reportBtn   = document.getElementById('validate-ids-report-btn');
    var progressWrap= document.getElementById('validate-ids-progress-wrap');
    var progressBar = document.getElementById('validate-ids-progress-bar');
    var msgEl       = document.getElementById('validate-ids-msg');
    var modal       = document.getElementById('validate-ids-modal');
    var closeBtn1   = document.getElementById('validate-ids-modal-close');
    var closeBtn2   = document.getElementById('validate-ids-modal-close2');
    var tbody       = document.getElementById('validate-modal-tbody');
    var showConfEl  = document.getElementById('vld-show-confirmed');

    var vldStatus   = null;
    var pollTimer   = null;
    var activeValidateMode = 'api';

    function openModal(){ if(modal){ modal.style.display='block'; document.body.style.overflow='hidden'; } }
    function closeModal(){ if(modal){ modal.style.display='none'; document.body.style.overflow=''; } }
    if(closeBtn1) closeBtn1.addEventListener('click', closeModal);
    if(closeBtn2) closeBtn2.addEventListener('click', closeModal);
    if(modal) modal.addEventListener('click', function(e){ if(e.target===modal) closeModal(); });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeModal(); });

    function scoreBadge(sc){
        var bg = sc>=0.95?'#dcfce7':sc>=0.75?'#dbeafe':sc>=0.60?'#fef9c3':'#fee2e2';
        var col= sc>=0.95?'#166534':sc>=0.75?'#1d4ed8':sc>=0.60?'#92400e':'#b91c1c';
        return '<span style="display:inline-block;padding:2px 7px;border-radius:20px;font-weight:700;font-size:12px;background:'+bg+';color:'+col+';">'+(sc||'—')+'</span>';
    }

    function renderModal(){
        var st = vldStatus;
        if(!st || !tbody) return;
        var allRows   = (st.cleared_rows  || []);
        var confRows  = (st.confirmed_rows || []);
        var showConf  = showConfEl && showConfEl.checked;

        var el = function(id){ return document.getElementById(id); };
        var setTxt = function(id,v){ var e=el(id); if(e) e.textContent=v; };
        setTxt('vld-stat-checked',  (st.done||0));
        setTxt('vld-stat-confirmed',(st.confirmed||0));
        setTxt('vld-stat-cleared',  (st.cleared||0));
        setTxt('vld-stat-skipped',  (st.skipped_api||0));
        setTxt('vld-stat-errors',   (st.errors||0));
        var sub = el('validate-modal-subtitle');
        var modeLabel = st.mode_label || 'Onliner API';
        var skippedLabel = st.skipped_label || 'Пропуск = API не ответил, ID не меняли.';
        if(sub) sub.textContent = 'Режим: ' + modeLabel + '. Проверено: ' + (st.done||0) + ' из ' + (st.total||0) + ' товаров с ID (ПЭВМ TGPC пропущены). ' + skippedLabel;

        tbody.innerHTML = '';

        var skipRows = (st.skipped_rows || []);
        if(skipRows.length > 0){
            var hdrS = document.createElement('tr');
            hdrS.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fef9c3;color:#854d0e;font-size:12px;font-weight:700;border-top:2px solid #fde047;">Пропущено без изменений — ' + skipRows.length + ':</td>';
            tbody.appendChild(hdrS);
            skipRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#fefce8')+';border-bottom:1px solid #fef9c3;vertical-align:top;';
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td colspan="2" style="padding:7px 14px;color:#92400e;font-size:11px;">'+(r.reason||'api_unreachable')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#ca8a04;font-weight:700;font-size:12px;">— пропуск</span></td>';
                tbody.appendChild(tr);
            });
        }

        // Cleared / wrong IDs section
        if(allRows.length > 0){
            var hdr = document.createElement('tr');
            hdr.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fee2e2;color:#991b1b;font-size:12px;font-weight:700;border-top:2px solid #fca5a5;">Очищено (неверный ID) — ' + allRows.length + ':</td>';
            tbody.appendChild(hdr);
            allRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#fff7f7')+';border-bottom:1px solid #fee2e2;vertical-align:top;';
                var sc = parseFloat(r.score)||0;
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#dc2626;text-decoration:line-through;font-size:11px;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td style="padding:7px 14px;color:#6b7280;font-size:12px;">'+(r.api_name||'—')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+scoreBadge(sc)+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#dc2626;font-weight:700;font-size:12px;">✗ Очищен</span></td>';
                tbody.appendChild(tr);
            });
        }

        // Confirmed section (optional)
        if(showConf && confRows.length > 0){
            var hdr2 = document.createElement('tr');
            hdr2.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#dcfce7;color:#166534;font-size:12px;font-weight:700;border-top:2px solid #86efac;">Подтверждено — ' + confRows.length + ':</td>';
            tbody.appendChild(hdr2);
            confRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#f0fdf4')+';border-bottom:1px solid #dcfce7;vertical-align:top;';
                var sc = parseFloat(r.score)||0;
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td style="padding:7px 14px;color:#374151;font-size:12px;">'+(r.api_name||'')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+scoreBadge(sc)+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#16a34a;font-weight:700;font-size:12px;">✓ Верно</span></td>';
                tbody.appendChild(tr);
            });
        }

        if(allRows.length === 0 && skipRows.length === 0 && (!showConf || confRows.length === 0)){
            var empty = document.createElement('tr');
            empty.innerHTML = '<td colspan="5" style="padding:20px;text-align:center;color:#9ca3af;font-size:13px;">'+(st.running?'Идёт проверка...':'Нет строк для отчёта (всё подтверждено или нет изменений)')+'</td>';
            tbody.appendChild(empty);
        }
    }

    if(showConfEl) showConfEl.addEventListener('change', renderModal);

    function stopPoll(){ if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; } }

    function pollValidate(){
        fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            vldStatus = st;
            var pct = st.total>0 ? Math.round((st.done||0)/st.total*100) : 0;
            if(progressBar) progressBar.style.width = pct + '%';
            if(msgEl) msgEl.textContent = st.message || '';
            if(st.running){
                if(progressWrap) progressWrap.style.display='block';
                if(startBtn){ startBtn.disabled=true; startBtn.textContent='Проверяю API...'; }
                if(startDbBtn){ startDbBtn.disabled=true; startDbBtn.textContent='Проверяю БД...'; }
                pollTimer = setTimeout(pollValidate, 2000);
            } else {
                if(progressWrap) progressWrap.style.display='block';
                if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
                if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
                if(st.done > 0 && reportBtn){
                    reportBtn.style.display='inline-flex';
                    stopPoll();
                }
                // После валидации сервер уже перезаписал consolidated — перезагружаем таблицу,
                // иначе в DataTables остаются старые OnlinerID («очищен», а в таблице есть).
                if(st.finished_at && (Number(st.cleared||0) > 0 || Number(st.confirmed||0) > 0 || Number(st.skipped_api||0) > 0)){
                    if(typeof tblMain !== 'undefined' && tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                        tblMain.ajax.reload(null, false);
                    }
                    fetch('/api/stats?_ts='+Date.now(), {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(s){
                        var w = document.getElementById('without-id-count');
                        if(w && s && s.without_id !== undefined) w.textContent = s.without_id;
                    }).catch(function(){});
                }
            }
        }).catch(function(){ pollTimer = setTimeout(pollValidate, 4000); });
    }

    function launchValidate(mode){
        var isDb = mode === 'db';
        var btn = isDb ? startDbBtn : startBtn;
        var endpoint = isDb ? '/api/validate-clean-ids-db-start' : '/api/validate-clean-ids-start';
        if(!btn || btn.disabled) return;
        activeValidateMode = mode;
        btn.disabled = true;
        btn.textContent = 'Запускаю...';
        if(!isDb && startDbBtn){ startDbBtn.disabled = true; }
        if(isDb && startBtn){ startBtn.disabled = true; }
        if(progressWrap) progressWrap.style.display='block';
        if(progressBar) progressBar.style.width='0%';
        if(msgEl) msgEl.textContent = isDb ? 'Подготовка локальной сверки...' : 'Подготовка API-проверки...';
        if(reportBtn) reportBtn.style.display='none';
        fetch(endpoint, {method:'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.status==='already_running' || d.status==='started'){
                stopPoll();
                pollValidate();
            } else {
                if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
                if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
                alert('Ошибка запуска: '+(d.message||d.status||'?'));
            }
        }).catch(function(err){
            if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
            if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
            alert('Ошибка: '+err);
        });
    }

    if(startBtn){
        startBtn.addEventListener('click', function(){
            launchValidate('api');
        });
    }

    if(startDbBtn){
        startDbBtn.addEventListener('click', function(){
            launchValidate('db');
        });
    }

    if(reportBtn){
        reportBtn.addEventListener('click', function(){
            renderModal();
            openModal();
        });
    }

    // Check if validation was running on page load
    fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(st){
        vldStatus = st;
        if(st.running){
            if(progressWrap) progressWrap.style.display='block';
            if(startBtn){ startBtn.disabled=true; startBtn.textContent='Проверяю API...'; }
            if(startDbBtn){ startDbBtn.disabled=true; startDbBtn.textContent='Проверяю БД...'; }
            pollValidate();
        } else if(st.done > 0){
            if(progressWrap) progressWrap.style.display='block';
            if(progressBar) progressBar.style.width='100%';
            if(msgEl) msgEl.textContent = st.message || '';
            if(reportBtn) reportBtn.style.display='inline-flex';
            if(startBtn){ startBtn.textContent='🔍 Проверить ID'; }
            if(startDbBtn){ startDbBtn.textContent='⚡ Проверить по БД'; }
        }
    }).catch(function(){});
})();
// ============================================================
(function(){
    var validatePollTimer = null;
    var validateLabel = 'Запустить';

    function stopValidatePoll(){
        if(validatePollTimer){ clearInterval(validatePollTimer); validatePollTimer = null; }
    }

    function renderValidateChips(st){
        var chips = document.getElementById('validate-clean-chips');
        if(!chips) return;
        var confirmed = Number(st.confirmed||0);
        var cleared   = Number(st.cleared||0);
        var queued    = Number(st.queued||0);
        var errors    = Number(st.errors||0);
        var html = '';
        if(confirmed > 0) html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#dcfce7;color:#15803d;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✓ '+confirmed+' подтверждено</span>';
        if(cleared > 0)   html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fee2e2;color:#dc2626;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✕ '+cleared+' очищено</span>';
        if(queued > 0)    html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#ede9fe;color:#5b21b6;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">⋯ '+queued+' в очереди</span>';
        if(errors > 0)    html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fef3c7;color:#b45309;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">! '+errors+' ошибок</span>';
        chips.innerHTML = html;
        chips.style.display = html ? 'flex' : 'none';
    }

    function pollValidateStatus(){
        fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var btn  = document.getElementById('run-validate-clean-btn');
            var note = document.getElementById('validate-clean-note');
            var bar  = document.getElementById('validate-clean-progress-bar');
            var wrap = document.getElementById('validate-clean-progress-wrap');
            var total = Number(st.total||0);
            var done  = Number(st.done||0);
            var pct   = total > 0 ? Math.round(done/total*100) : 0;
            if(wrap) wrap.style.display = 'block';
            if(bar)  bar.style.width = pct + '%';
            if(note && st.message) note.textContent = st.message;
            renderValidateChips(st);
            if(btn && st.running){
                var phase2 = st.message && String(st.message).indexOf('Фаза 2') === 0;
                btn.textContent = phase2 ? 'Кандидаты...' : ('Проверяю ' + pct + '%');
            }
            if(!st.running){
                stopValidatePoll();
                if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
                hideBusyOverlay();
                // Обновляем таблицу и счётчик
                if(st.finished_at && Number(st.cleared||0) > 0){
                    if(tblMain && typeof tblMain.ajax !== 'undefined'){
                        tblMain.ajax.reload(null, false);
                    } else {
                        fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(resp){
                            mainTableRows = (resp && resp.data) ? resp.data : [];
                            updateWithoutIdCount(mainTableRows);
                            renderMainTableFallback();
                        });
                    }
                }
                if(st.finished_at && Number(st.queued||0) > 0){
                    // Показываем кнопку очереди подсвеченной
                    var qBtn = document.getElementById('show-review-queue-btn');
                    if(qBtn) qBtn.style.background = '#ede9fe';
                    loadReviewQueue();
                }
                if(bar && st.finished_at){
                    bar.style.background = Number(st.cleared||0) > 0 ? 'linear-gradient(90deg,#f87171,#dc2626)' : 'linear-gradient(90deg,#6366f1,#4f46e5)';
                }
                runPreExportQualityCheck();
            } else {
                updateBusyOverlay('Валидация ID', st.message || ('Проверено ' + done + ' из ' + total + '...'));
            }
        }).catch(function(){
            stopValidatePoll();
            var btn = document.getElementById('run-validate-clean-btn');
            if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
            hideBusyOverlay();
        });
    }

    window.startValidateClean = function(){
        var btn = document.getElementById('run-validate-clean-btn');
        if(btn && btn.disabled) return;
        if(btn){ btn.disabled = true; btn.textContent = 'Проверяю 0%'; }
        var chips = document.getElementById('validate-clean-chips');
        if(chips){ chips.innerHTML = ''; chips.style.display = 'none'; }
        var bar = document.getElementById('validate-clean-progress-bar');
        var wrap = document.getElementById('validate-clean-progress-wrap');
        if(wrap) wrap.style.display = 'block';
        if(bar){ bar.style.width = '2%'; bar.style.background = 'linear-gradient(90deg,#6366f1,#4f46e5)'; }
        var note = document.getElementById('validate-clean-note');
        if(note) note.textContent = 'Запускаем валидацию...';
        showBusyOverlay('Валидация ID', 'Проверяем каждый OnlinerID по Onliner API...');
        fetch('/api/validate-clean-ids-start', {method:'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(!d || (d.status !== 'started' && d.status !== 'already_running')){
                throw new Error((d&&d.message)||'start_failed');
            }
            stopValidatePoll();
            validatePollTimer = setInterval(pollValidateStatus, 1500);
            pollValidateStatus();
        }).catch(function(err){
            if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
            hideBusyOverlay();
            if(note) note.textContent = 'Не удалось запустить валидацию.';
        });
    };
})();

// ============================================================
// ОЧЕРЕДЬ РУЧНОЙ ПРОВЕРКИ ID
// ============================================================
var _reviewQueueData = {};

function highlightCpuModelMatch(candidateName, cpuModel){
    var text = String(candidateName || '');
    var model = String(cpuModel || '').trim();
    if(!model){
        return escapeHtml(text);
    }
    var escapedText = escapeHtml(text);
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(!compactModel){
        return escapedText;
    }
    var patterns = [
        model,
        model.replace(/\s+/g, ''),
        model.replace(/([a-z]+)(\d)/ig, '$1 $2'),
        model.replace(/([a-z]+)\s*(\d)/ig, '$1-$2')
    ].filter(function(v, idx, arr){
        return v && arr.indexOf(v) === idx;
    });
    for(var i = 0; i < patterns.length; i++){
        var raw = String(patterns[i] || '');
        if(!raw){ continue; }
        var escapedPattern = raw.replace(/[.*+?^${}()|[\]\]/g, '\$&').replace(/\s+/g, '\s*');
        var re = new RegExp('(' + escapedPattern + ')', 'i');
        if(re.test(text)){
            return escapedText.replace(re, '<span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 4px;font-weight:700;">$1</span>');
        }
    }
    var compactText = text.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(compactText.indexOf(compactModel) >= 0){
        return escapedText + ' <span style="display:inline-flex;align-items:center;gap:4px;background:#dcfce7;color:#166534;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:700;vertical-align:middle;">модель совпала</span>';
    }
    return escapedText;
}

function parseCpuBrandModel(candidateName){
    var text = String(candidateName || '').toLowerCase();
    var brand = '';
    if(/intel|xeon|pentium|celeron/.test(text)){ brand = 'INTEL'; }
    else if(/amd|ryzen|athlon/.test(text)){ brand = 'AMD'; }
    var patterns = [
        /(?:^|[^a-z0-9])(i[3579]-\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(pentium\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(celeron\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(athlon\s+\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(xeon\s+[ew]?-?\d{1,2}-?\d{4,5}\s*v?\d?)(?=$|[^a-z0-9])/i
    ];
    var model = '';
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            model = String(m[1]).toUpperCase().replace(/\s+/g, ' ').trim();
            break;
        }
    }
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    return { brand: brand, model: model, compactModel: compactModel };
}

function cpuCandidateTone(item, candidate){
    var expectedBrand = String((item && item.cpu_brand) || '').trim().toUpperCase();
    var expectedModel = String((item && item.cpu_model) || '').trim().toUpperCase();
    var parsed = parseCpuBrandModel(String((candidate && candidate.name) || ''));
    var sameBrand = !!expectedBrand && parsed.brand === expectedBrand;
    var sameModel = !!expectedModel && !!parsed.compactModel && parsed.compactModel === expectedModel.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(sameBrand && sameModel){
        return {
            bg: '#dcfce7',
            color: '#166534',
            border: '#86efac',
            label: 'точное CPU'
        };
    }
    if(sameModel){
        return {
            bg: '#fef3c7',
            color: '#92400e',
            border: '#fcd34d',
            label: 'модель ок'
        };
    }
    return {
        bg: '#fee2e2',
        color: '#991b1b',
        border: '#fca5a5',
        label: 'проверить'
    };
}

function cpuCandidatePriority(item, candidate){
    var tone = cpuCandidateTone(item, candidate);
    if(tone.label === 'точное CPU'){ return 0; }
    if(tone.label === 'модель ок'){ return 1; }
    return 2;
}

window.loadReviewQueue = function(){
    fetch('/api/review-queue?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(data){
        var items = Array.isArray(data.items) ? data.items : [];
        var card  = document.getElementById('review-queue-card');
        var badge = document.getElementById('review-queue-count-badge');
        var list  = document.getElementById('review-queue-list');
        var note  = document.getElementById('review-queue-note');
        var qBtn  = document.getElementById('show-review-queue-btn');

        if(badge){
            if(items.length > 0){ badge.textContent = items.length; badge.style.display = 'inline-block'; }
            else { badge.style.display = 'none'; }
        }
        if(qBtn){ qBtn.style.background = items.length > 0 ? '#ede9fe' : ''; }
        if(!list) return;

        if(!items.length){
            list.innerHTML = '<div class="markup-note" style="color:#6b7280;">Очередь пуста — нет товаров ожидающих ручной проверки.</div>';
            if(note) note.textContent = 'Запустите «Валидация и очистка ID» — неверно сопоставленные товары появятся здесь с кандидатами на выбор.';
            return;
        }
        if(card) card.style.display = 'block';
        if(note) note.textContent = 'Выберите правильный ID из кандидатов или нажмите «Пропустить». После выбора — запустите автоподбор снова.';

        // Сохраняем данные в глобальный map по индексу — без небезопасных inline-аргументов
        _reviewQueueData = {};
        items.forEach(function(item, idx){ _reviewQueueData[idx] = item; });

        var html = '';
        items.forEach(function(item, idx){
            var name      = escapeHtml(item.name||'');
            var cpuBrand  = escapeHtml(String(item.cpu_brand||'').trim());
            var cpuModel  = escapeHtml(String(item.cpu_model||'').trim());
            var clearedId = escapeHtml(String(item.cleared_id||''));
            var clearedSc = item.cleared_score !== undefined ? String(Math.round(Number(item.cleared_score)*100))+'%' : '';
            var onlName   = escapeHtml(item.onliner_name||'');
            var cands     = Array.isArray(item.candidates) ? item.candidates : [];

            html += '<div class="review-queue-item" data-rqi="'+idx+'" style="border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#fafaf9;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;margin-bottom:10px;">';
            html += '<div style="font-size:13px;font-weight:700;color:#111827;flex:1;min-width:0;">'+ name +'</div>';
            html += '<button data-rqi-skip="'+idx+'" style="padding:4px 12px;font-size:11px;border:1px solid #d1d5db;border-radius:6px;background:#fff;cursor:pointer;color:#6b7280;white-space:nowrap;">Пропустить</button>';
            html += '</div>';

            if(cpuBrand || cpuModel){
                html += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">';
                if(cpuBrand){
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:#eef2ff;color:#4338ca;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;">Производитель: '+cpuBrand+'</span>';
                }
                if(cpuModel){
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:#f5f3ff;color:#6d28d9;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;font-family:monospace;">Модель: '+cpuModel+'</span>';
                }
                html += '</div>';
            }

            if(clearedId){
                html += '<div style="font-size:11px;color:#9ca3af;margin-bottom:8px;">Был ID: <span style="font-family:monospace;color:#dc2626;">'+clearedId+'</span>';
                if(clearedSc) html += ' <span style="color:#b45309;">(совпадение '+clearedSc+')</span>';
                if(onlName)   html += ' — Onliner: <em>'+onlName+'</em>';
                html += '</div>';
            }

            if(cands.length){
                cands = cands.slice().sort(function(a, b){
                    var pa = cpuCandidatePriority(item, a);
                    var pb = cpuCandidatePriority(item, b);
                    if(pa !== pb){ return pa - pb; }
                    var sa = Number((a && a.score) || 0);
                    var sb = Number((b && b.score) || 0);
                    if(sa !== sb){ return sb - sa; }
                    return String((a && a.name) || '').localeCompare(String((b && b.name) || ''), 'ru');
                });
                html += '<div style="font-size:11px;color:#374151;font-weight:600;margin-bottom:6px;">Кандидаты:</div>';
                html += '<div style="display:flex;flex-direction:column;gap:6px;">';
                cands.forEach(function(c, ci){
                    var cId    = escapeHtml(String(c.id||''));
                    var cName  = highlightCpuModelMatch(String(c.name||''), String(item.cpu_model||''));
                    var cSc    = c.score !== undefined ? Math.round(Number(c.score)*100) : 0;
                    var scCol  = cSc >= 90 ? '#15803d' : cSc >= 70 ? '#b45309' : '#dc2626';
                    var cUrl   = escapeHtml(String(c.url||''));
                    var tone   = cpuCandidateTone(item, c);
                    html += '<div style="display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px;">';
                    html += '<span style="background:#ede9fe;color:#5b21b6;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;font-family:monospace;white-space:nowrap;">'+cId+'</span>';
                    html += '<span style="flex:1;font-size:12px;color:#1f2937;">'+cName+'</span>';
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:'+tone.bg+';color:'+tone.color+';border:1px solid '+tone.border+';border-radius:999px;padding:2px 7px;font-size:10px;font-weight:700;white-space:nowrap;">'+escapeHtml(tone.label)+'</span>';
                    html += '<span style="font-size:11px;color:'+scCol+';font-weight:600;white-space:nowrap;">'+cSc+'%</span>';
                    if(cUrl){ html += '<a href="'+cUrl+'" target="_blank" style="font-size:11px;color:#6366f1;text-decoration:none;white-space:nowrap;">↗</a>'; }
                    html += '<button data-rqi-pick="'+idx+'" data-rqi-ci="'+ci+'" style="padding:4px 12px;font-size:11px;border:none;border-radius:6px;background:#6366f1;color:#fff;cursor:pointer;white-space:nowrap;">Выбрать</button>';
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html += '<div class="markup-note">Кандидатов не найдено — запустите автоподбор после валидации.</div>';
            }
            html += '</div>';
        });
        list.innerHTML = html;

        // Навешиваем обработчики один раз через делегирование
        list.onclick = function(e){
            var skipBtn = e.target.closest('[data-rqi-skip]');
            var pickBtn = e.target.closest('[data-rqi-pick]');
            if(skipBtn){
                var idx = Number(skipBtn.getAttribute('data-rqi-skip'));
                var item = _reviewQueueData[idx];
                if(item) _doReviewPick(item.name_key||'', '', '', '', item.name||'');
                var wrap = skipBtn.closest('[data-rqi]');
                if(wrap){ wrap.style.opacity='0.4'; wrap.style.pointerEvents='none'; }
            } else if(pickBtn){
                var idx = Number(pickBtn.getAttribute('data-rqi-pick'));
                var ci  = Number(pickBtn.getAttribute('data-rqi-ci'));
                var item = _reviewQueueData[idx];
                if(item){
                    var cand = (item.candidates||[])[ci] || {};
                    _doReviewPick(item.name_key||'', cand.id||'', cand.name||'', cand.url||'', item.name||'');
                    var wrap = pickBtn.closest('[data-rqi]');
                    if(wrap){ wrap.style.opacity='0.4'; wrap.style.pointerEvents='none'; }
                }
            }
        };
    }).catch(function(){
        var list = document.getElementById('review-queue-list');
        if(list) list.innerHTML = '<div class="markup-note" style="color:#dc2626;">Не удалось загрузить очередь.</div>';
    });
};

function _doReviewPick(nameKey, oid, candName, url, itemName){
    fetch('/api/review-queue-pick', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name_key: nameKey, onliner_id: oid, url: url, name: itemName||''})
    }).then(function(r){ return r.json(); }).then(function(d){
        var badge = document.getElementById('review-queue-count-badge');
        var remaining = Number((d&&d.remaining)||0);
        if(badge){ badge.textContent = remaining; if(!remaining) badge.style.display='none'; }
        if(oid && tblMain && typeof tblMain.ajax !== 'undefined'){
            tblMain.ajax.reload(null, false);
        }
        var list = document.getElementById('review-queue-list');
        if(list){
            var done = list.querySelectorAll('[data-rqi]');
            var allFaded = true;
            done.forEach(function(el){ if(el.style.opacity !== '0.4') allFaded = false; });
            if(allFaded) list.innerHTML = '<div class="markup-note" style="color:#6b7280;">Очередь пуста.</div>';
        }
    }).catch(function(){});
}

window.pickReviewCandidate = _doReviewPick;

