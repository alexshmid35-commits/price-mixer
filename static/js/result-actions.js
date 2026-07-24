function initNoIdFilterUI(){
    var btn = document.getElementById('toggle-noid-btn');
    var duplicateBtn = document.getElementById('toggle-duplicate-id-btn');
    var exportBtn = document.getElementById('export-category-analytics-btn');
    var autoBtn = document.getElementById('autofill-tgpc-pc-btn');
    var autoNtechPcBtn = document.getElementById('autofill-ntech-pc-btn');
    var autoIvenPcBtn = document.getElementById('autofill-iven-pc-btn');
    var autoNote = document.getElementById('autofill-tgpc-pc-note');
    var autoPollTimer = null;
    var autoVisualTimer = null;
    var autoVisualPercent = 0;
    var autoRunLabel = 'Авто TGPC ПЭВМ';
    var activeAutoBtn = autoBtn;
    var activeAutoStartUrl = '/api/autofill-tgpc-pc-ids';
    var activeAutoStatusUrl = '/api/autofill-tgpc-pc-status';
    var activeAutoPcLabel = 'TGPC ПЭВМ';
    var autoRunResolve = null;
    var autoOpenPcUnifiedReport = true;
    function setPcAutofillButtonsDisabled(disabled){
        [autoBtn, autoNtechPcBtn, autoIvenPcBtn].forEach(function(button){
            if(button){ button.disabled = !!disabled; }
        });
    }
    function restorePcAutofillButtonLabels(){
        if(autoBtn){ autoBtn.textContent = 'Авто TGPC ПЭВМ'; }
        if(autoNtechPcBtn){
            autoNtechPcBtn.innerHTML = 'Авто N-Tech ПЭВМ <span class="ntech-check-badge" id="ntech-pc-review-badge"></span>';
        }
        if(autoIvenPcBtn){
            autoIvenPcBtn.innerHTML = 'Авто IVEN ПЭВМ <span class="ntech-check-badge" id="iven-pc-review-badge"></span>';
        }
        updateNtechCheckCategoryBadges(mainTableRows || []);
    }
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
        var compactMisses = String(activeAutoPcLabel || '').toLowerCase().indexOf('iven') >= 0
            || String(activeAutoPcLabel || '').toLowerCase().indexOf('tgpc') >= 0
            || String(activeAutoPcLabel || '').toLowerCase().indexOf('n-tech') >= 0
            || String(activeAutoPcLabel || '').toLowerCase().indexOf('ntech') >= 0;

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
        if(others.length && !compactMisses){
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
        if(activeAutoBtn){
            activeAutoBtn.textContent = 'Подбираю ' + autoVisualPercent + '%';
        }
        autoVisualTimer = setInterval(function(){
            if(autoVisualPercent < 95){
                autoVisualPercent = Math.min(95, autoVisualPercent + (autoVisualPercent < 20 ? 3 : 2));
                if(activeAutoBtn){
                    activeAutoBtn.textContent = 'Подбираю ' + autoVisualPercent + '%';
                }
            }
        }, 1200);
    }
    function finishAutoRun(result){
        if(autoRunResolve){
            var resolve = autoRunResolve;
            autoRunResolve = null;
            resolve(result || null);
        }
    }
    function buildPcAutofillUnifiedStatus(st){
        st = st || {};
        var items = Array.isArray(st.items) ? st.items : [];
        var matches = [];
        var noMatch = [];
        items.forEach(function(item){
            if(!item) return;
            var name = String(item.name || '').trim();
            var oid = String(item.onliner_id || '').trim();
            var onlinerName = String(item.onliner_name || '').trim();
            var score = Number(item.score || 0);
            if(item.status === 'matched'){
                matches.push({
                    row_idx: item.row_idx,
                    name: name,
                    matched_name: onlinerName || name,
                    id: oid,
                    score: score ? score.toFixed(3) : '1.000',
                    source: 'pc_autofill'
                });
            } else {
                var candidates = [];
                if(oid){
                    candidates.push({
                        id: oid,
                        name: onlinerName || name,
                        score: score ? score.toFixed(3) : '0.000',
                        source: 'pc_autofill'
                    });
                }
                noMatch.push({
                    row_idx: item.row_idx,
                    name: name,
                    candidates: candidates,
                    best_id: oid,
                    best_source: oid ? 'pc_autofill' : '',
                    source: 'pc_autofill'
                });
            }
        });
        var label = activeAutoPcLabel || 'ПЭВМ';
        var total = Number(st.total || 0);
        var done = Number(st.done || 0);
        var applied = Number(st.applied || 0);
        var skipped = Number(st.skipped || 0);
        return {
            status: 'ok',
            report_mode: 'iven',
            report_key: 'pc_autofill_' + label.toLowerCase().replace(/[^a-zа-я0-9]+/gi, '_'),
            report_tab_label: label,
            report_title: 'Отчёт ' + label,
            report_subtitle: 'Обработано ПЭВМ: ' + done + ' из ' + total + '. Подставлено: ' + applied + ', на ручную проверку: ' + skipped + '.',
            matches: matches,
            no_match: noMatch
        };
    }
    function pollAutoStatus(){
        fetch(activeAutoStatusUrl + '?_ts=' + Date.now(), {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(st){
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
            if(activeAutoBtn){
                activeAutoBtn.textContent = st.running ? ('Подбираю ' + Math.max(percent, autoVisualPercent) + '%') : (autoRunLabel + (st.finished_at ? (' ' + percent + '%') : ''));
                if(!st.running && !st.finished_at){
                    activeAutoBtn.textContent = autoRunLabel;
                }
            }
            if(autoNote){
                if(st.running){
                    autoNote.textContent = 'Обработано ' + done + ' из ' + total + ' ' + activeAutoPcLabel + '. Подставлено: ' + applied + '.';
                } else if(st.message && String(st.message).toLowerCase().indexOf('ошибка') === 0){
                    autoNote.textContent = st.message;
                } else if(st.finished_at){
                    autoNote.textContent = 'Автоподбор завершён: подставлено ' + applied + ' из ' + total + ' ' + activeAutoPcLabel + ' (' + percent + '%). Пропущено: ' + skipped + '.';
                } else if(st.message){
                    autoNote.textContent = st.message;
                }
            }
            renderAutoReport(items, st);
            if(st.finished_at && (items.length || total > 0)){
                var unifiedStatus = buildPcAutofillUnifiedStatus(st);
                if(autoOpenPcUnifiedReport && typeof window.renderUnifiedIdReportModal === 'function'){
                    window.renderUnifiedIdReportModal(unifiedStatus);
                } else if(typeof window.storeUnifiedIdReport === 'function'){
                    window.storeUnifiedIdReport(unifiedStatus);
                }
            }
            if(st.running){
                updateBusyOverlay('Автоподбор ' + activeAutoPcLabel, 'Обработано ' + done + ' из ' + total + '. Подставлено: ' + applied + '.');
                return;
            }
            stopAutoPoll();
            stopAutoVisual();
            setPcAutofillButtonsDisabled(false);
            restorePcAutofillButtonLabels();
            hideBusyOverlay();
            if(st.finished_at){
                closeNoIdInlinePicker(false);
                if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                    tblMain.ajax.reload(null, false);
                } else {
                    fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(resp){
                        mainTableRows = (resp && resp.data) ? resp.data : [];
                        updateWithoutIdCount(mainTableRows);
                        updateNtechCheckCategoryBadges(mainTableRows);
                        renderMainTableFallback();
                    });
                }
                runPreExportQualityCheck();
            }
            finishAutoRun(st);
        }).catch(function(){
            stopAutoPoll();
            stopAutoVisual();
            setPcAutofillButtonsDisabled(false);
            restorePcAutofillButtonLabels();
            if(autoNote){
                autoNote.textContent = 'Не удалось получить прогресс автоподбора ' + activeAutoPcLabel + '.';
            }
            renderAutoReport([]);
            hideBusyOverlay();
            finishAutoRun({status:'error', message:'Не удалось получить прогресс автоподбора ' + activeAutoPcLabel + '.'});
        });
    }
    function startAutoFill(limitValue, labelText, options){
        options = options || {};
        activeAutoBtn = options.button || autoBtn;
        activeAutoStartUrl = options.startUrl || '/api/autofill-tgpc-pc-ids';
        activeAutoStatusUrl = options.statusUrl || '/api/autofill-tgpc-pc-status';
        activeAutoPcLabel = options.pcLabel || 'TGPC ПЭВМ';
        if(activeAutoBtn && activeAutoBtn.disabled){ return Promise.resolve(null); }
        autoRunLabel = labelText || 'Авто TGPC ПЭВМ';
        var autoRunPromise = new Promise(function(resolve){ autoRunResolve = resolve; });
        setPcAutofillButtonsDisabled(true);
        if(activeAutoBtn){
            activeAutoBtn.textContent = 'Подбираю 1%';
        }
        if(autoNote){
            autoNote.textContent = 'Запустили подбор ' + activeAutoPcLabel + '. Сейчас начнём проверку первых позиций...';
        }
        renderAutoReport([], null);
        var progWrap2 = document.getElementById('autofill-tgpc-progress-wrap');
        var progBar2  = document.getElementById('autofill-tgpc-progress-bar');
        var chips2    = document.getElementById('autofill-tgpc-chips');
        if(progWrap2){ progWrap2.style.display = 'block'; }
        if(progBar2){ progBar2.style.width = '2%'; progBar2.style.background = 'linear-gradient(90deg,#f59e0b,#d56e0c)'; }
        if(chips2){ chips2.innerHTML = ''; chips2.style.display = 'none'; }
        startAutoVisual();
        showBusyOverlay('Автоподбор ' + activeAutoPcLabel, 'Ищем совпадения в локальной SQLite-базе и сохраняем найденные ID...');
        fetch(activeAutoStartUrl, {
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
                autoNote.textContent = 'Не удалось завершить автоподбор ' + activeAutoPcLabel + '.';
            }
            stopAutoVisual();
            setPcAutofillButtonsDisabled(false);
            restorePcAutofillButtonLabels();
            hideBusyOverlay();
            finishAutoRun({status:'error', message:'Не удалось завершить автоподбор ' + activeAutoPcLabel + '.'});
        });
        return autoRunPromise;
    }
    function setExportFilterButtonLabel(){
        if(exportBtn){
            exportBtn.textContent = showOnlyExportRows ? 'Показать все' : 'Показать';
        }
    }
    function setNoIdFilterButtonLabel(){
        if(btn){
            btn.textContent = showOnlyNoIdRows ? 'Показать все' : 'Показать';
        }
        setNoIdCategoryFilterVisible(showOnlyNoIdRows);
    }
    function setDuplicateFilterButtonLabel(){
        if(duplicateBtn){
            duplicateBtn.textContent = showOnlyDuplicateIdRows ? 'Показать все' : 'Показать дубли ID';
        }
    }
    function redrawMainFilterTable(order){
        if(tblMain){
            if(typeof tblMain.draw === 'function'){
                if(order && typeof tblMain.order === 'function'){
                    tblMain.order(order);
                }
                tblMain.draw(false);
            } else if(tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                tblMain.ajax.reload(null, false);
            }
        } else {
            renderMainTableFallback();
        }
    }
    function requestExportRowIndexes(){
        var url = '/api/export-row-indexes?_ts=' + Date.now();
        if(window.jQuery && typeof $.ajax === 'function'){
            return new Promise(function(resolve, reject){
                $.ajax({
                    url: url,
                    method: 'GET',
                    cache: false,
                    dataType: 'json',
                    success: resolve,
                    error: function(xhr){
                        reject(new Error('export_indexes_' + (xhr && xhr.status ? xhr.status : 'ajax')));
                    }
                });
            });
        }
        if(typeof fetch === 'function'){
            return fetch(url, {cache:'no-store', credentials:'same-origin'})
                .then(function(r){
                    if(!r.ok){ throw new Error('export_indexes_' + r.status); }
                    return r.json();
                });
        }
        return Promise.reject(new Error('export_indexes_no_transport'));
    }
    function loadExportRowIndexes(){
        if(exportRowIndexLoading){
            return Promise.resolve(false);
        }
        if(exportRowIndexSet && Object.keys(exportRowIndexSet).length){
            return Promise.resolve(true);
        }
        exportRowIndexLoading = true;
        if(exportBtn){
            exportBtn.disabled = true;
            exportBtn.textContent = 'Загрузка...';
        }
        return requestExportRowIndexes()
            .then(function(d){
                var next = {};
                var indexes = (d && Array.isArray(d.indexes)) ? d.indexes : [];
                indexes.forEach(function(idx){
                    var value = String(idx == null ? '' : idx).trim();
                    if(value){ next[value] = true; }
                });
                exportRowIndexSet = next;
                if(window){ window.exportRowIndexSet = exportRowIndexSet; }
                return Object.keys(exportRowIndexSet).length > 0 || Number((d && d.count) || 0) === 0;
            })
            .catch(function(){
                exportRowIndexSet = {};
                if(window){ window.exportRowIndexSet = exportRowIndexSet; }
                if(exportBtn){
                    exportBtn.title = 'Не удалось загрузить список строк для Google';
                }
                return false;
            })
            .finally(function(){
                exportRowIndexLoading = false;
                if(exportBtn){
                    exportBtn.disabled = false;
                }
                setExportFilterButtonLabel();
            });
    }
    // Не делаем ранний return, если кнопки фильтра нет: ниже инициализируются IVEN / N-Tech — иначе «ломаются» все кнопки блока.
    if(exportBtn){
        exportBtn.addEventListener('click', function(){
            if(showOnlyExportRows){
                showOnlyExportRows = false;
                setExportFilterButtonLabel();
                redrawMainFilterTable([[1, 'asc']]);
                return;
            }
            loadExportRowIndexes().then(function(){
                if(!exportRowIndexSet || !Object.keys(exportRowIndexSet).length){
                    setExportFilterButtonLabel();
                    return;
                }
                showOnlyExportRows = true;
                showOnlyNoIdRows = false;
                showOnlyDuplicateIdRows = false;
                selectedNoIdCategory = '';
                closeNoIdInlinePicker(false);
                setExportFilterButtonLabel();
                setNoIdFilterButtonLabel();
                setDuplicateFilterButtonLabel();
                redrawMainFilterTable([[1, 'asc']]);
            });
        });
    }
    if(btn){
        btn.addEventListener('click', function(){
            showOnlyNoIdRows = !showOnlyNoIdRows;
            if(showOnlyNoIdRows){
                showOnlyDuplicateIdRows = false;
                showOnlyExportRows = false;
                setDuplicateFilterButtonLabel();
                setExportFilterButtonLabel();
            }
            if(!showOnlyNoIdRows){
                selectedNoIdCategory = '';
                closeNoIdInlinePicker(false);
            }
            setNoIdFilterButtonLabel();
            redrawMainFilterTable(showOnlyNoIdRows ? [[1, 'asc']] : null);
        });
    }
    if(duplicateBtn){
        duplicateBtn.addEventListener('click', function(){
            showOnlyDuplicateIdRows = !showOnlyDuplicateIdRows;
            if(showOnlyDuplicateIdRows){
                showOnlyNoIdRows = false;
                showOnlyExportRows = false;
                selectedNoIdCategory = '';
                setNoIdFilterButtonLabel();
                setExportFilterButtonLabel();
                setDuplicateFilterButtonLabel();
                runDuplicateIdCheck(false);
                var duplicateCard = document.getElementById('duplicate-id-check-card');
                if(duplicateCard){
                    duplicateCard.style.display = 'block';
                    duplicateCard.scrollIntoView({behavior:'smooth', block:'start'});
                }
            } else {
                setDuplicateFilterButtonLabel();
            }
            redrawMainFilterTable(showOnlyDuplicateIdRows ? [[0, 'asc'], [2, 'asc']] : [[1, 'asc']]);
        });
    }
    if(autoBtn){
        autoBtn.addEventListener('click', function(){
            startAutoFill(0, 'Авто TGPC ПЭВМ', {
                button: autoBtn,
                startUrl: '/api/autofill-tgpc-pc-ids',
                statusUrl: '/api/autofill-tgpc-pc-status',
                pcLabel: 'TGPC ПЭВМ'
            });
        });
    }
    if(autoNtechPcBtn){
        autoNtechPcBtn.addEventListener('click', function(){
            startAutoFill(0, 'Авто N-Tech ПЭВМ', {
                button: autoNtechPcBtn,
                startUrl: '/api/autofill-ntech-pc-ids',
                statusUrl: '/api/autofill-ntech-pc-status',
                pcLabel: 'N-Tech ПЭВМ'
            });
        });
    }
    if(autoIvenPcBtn){
        autoIvenPcBtn.addEventListener('click', function(){
            startAutoFill(0, 'Авто IVEN ПЭВМ', {
                button: autoIvenPcBtn,
                startUrl: '/api/autofill-iven-pc-ids',
                statusUrl: '/api/autofill-iven-pc-status',
                pcLabel: 'IVEN ПЭВМ'
            });
        });
    }

    // ── IVEN Bridge autofill ──────────────────────────────────────────────────
    (function(){
        var runAllChecksBtn = document.getElementById('run-all-id-checks-btn');
        var runAllChecksNote = document.getElementById('run-all-id-checks-note');
        var clearNonPcBtn = document.getElementById('clear-nonpc-ids-btn');
        var clearDuplicateIdsBtn = document.getElementById('clear-duplicate-ids-btn');
        var cpuReviewBtn = document.getElementById('cpu-review-btn');
        var boardReviewBtn = document.getElementById('board-review-btn');
        var monitorReviewBtn = document.getElementById('monitor-review-btn');
        var gpuReviewBtn = document.getElementById('gpu-review-btn');
        var ramReviewBtn = document.getElementById('ram-review-btn');
        var ssdReviewBtn = document.getElementById('ssd-review-btn');
        var psuReviewBtn = document.getElementById('psu-review-btn');
        var caseReviewBtn = document.getElementById('case-review-btn');
        var hddReviewBtn = document.getElementById('hdd-review-btn');
        var coolerReviewBtn = document.getElementById('cooler-review-btn');
        var printerReviewBtn = document.getElementById('printer-review-btn');
        var peripheralReviewBtn = document.getElementById('peripheral-review-btn');
        var ivenLaptopReviewBtn = document.getElementById('iven-laptop-review-btn');
        var ivenZakazLaptopReviewBtn = document.getElementById('iven-zakaz-laptop-review-btn');
        var tradexLaptopReviewBtn = document.getElementById('tradex-laptop-review-btn');
        var ivenReportBtn = document.getElementById('autofill-iven-report-btn');
        var ivenWrap      = null;
        var ivenBar       = null;
        var ivenMsg       = null;
        var lastStatus    = null;
        var unifiedIdReportTabs = {};
        var unifiedIdReportOrder = [];
        var allChecksRunning = false;

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

        function renderInlineDbSearch(host, query, manualInput){
            if(!host) return;
            var q = String(query || '').trim();
            if(!q){
                host.style.display = 'none';
                host.innerHTML = '';
                return;
            }
            host.style.display = 'block';
            host.innerHTML = '<div style="font-size:11px;color:#64748b;">Ищу в базе...</div>';
            fetch('/api/onliner-db-search?q=' + encodeURIComponent(q), {cache:'no-store'})
            .then(function(r){ return r.json(); })
            .then(function(resp){
                var items = (resp && resp.items) || [];
                if(!items.length){
                    host.innerHTML = '<div style="font-size:11px;color:#64748b;">В базе ничего не найдено по этому запросу.</div>';
                    return;
                }
                var html = '';
                items.slice(0, 8).forEach(function(item){
                    var oid = String((item && item.id) || '').trim();
                    var nm = escapeHtml(String((item && item.name) || '').trim());
                    html += '<div style="padding:4px 0;border-bottom:1px solid #f1f5f9;">';
                    html += '<div style="font-size:11px;color:#334155;line-height:1.3;">' + nm + '</div>';
                    html += '<div style="margin-top:3px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">';
                    html += '<span style="font-family:monospace;font-size:11px;font-weight:700;color:#2563eb;">' + escapeHtml(oid) + '</span>';
                    html += '<button class="iven-inline-db-apply-btn" data-id="' + escapeHtml(oid) + '" type="button" style="margin-left:auto;padding:2px 7px;border:1px solid #2563eb;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:10px;font-weight:700;cursor:pointer;">Подставить</button>';
                    html += '</div></div>';
                });
                host.innerHTML = html;
                host.querySelectorAll('.iven-inline-db-apply-btn').forEach(function(btn){
                    btn.addEventListener('click', function(){
                        if(!manualInput) return;
                        var oid = String(btn.getAttribute('data-id') || '').trim();
                        if(!oid) return;
                        manualInput.value = oid;
                        try{
                            manualInput.dispatchEvent(new Event('input', {bubbles:true}));
                            manualInput.dispatchEvent(new Event('change', {bubbles:true}));
                        }catch(_e){}
                        manualInput.focus();
                    });
                });
            })
            .catch(function(){
                host.innerHTML = '<div style="font-size:11px;color:#dc2626;">Ошибка поиска в базе.</div>';
            });
        }

        // Track confirmed/rejected rows: name → state ('confirmed'|'rejected')
        var ivenRowStates = {};

        function syncLastStatusAfterManualSave(name, rowIdx, oid){
            if(!lastStatus || !Array.isArray(lastStatus.no_match)) return;
            var targetName = String(name || '').trim();
            var targetOid = String(oid || '').trim();
            lastStatus.no_match = lastStatus.no_match.filter(function(item){
                var sameName = String((item && item.name) || '').trim() === targetName;
                var sameRow = String((item && item.row_idx) || '') === String(rowIdx == null ? '' : rowIdx);
                return !(sameName && (sameRow || rowIdx == null));
            });
            if(String((lastStatus.report_mode || '')).toLowerCase() !== 'cpu' && targetOid){
                lastStatus.matches = Array.isArray(lastStatus.matches) ? lastStatus.matches : [];
                var exists = lastStatus.matches.some(function(item){
                    return String((item && item.name) || '').trim() === targetName && String((item && item.id) || '').trim() === targetOid;
                });
                if(!exists){
                    lastStatus.matches.push({name: targetName, id: targetOid, score: '1.000', matched_name: targetName, source: 'manual'});
                }
            }
        }

        function reportIssueKey(item){
            return String(((item && item.cpu_issue) || (item && item.board_issue) || (item && item.monitor_issue) || (item && item.gpu_issue) || (item && item.ram_issue) || (item && item.ssd_issue) || (item && item.psu_issue) || (item && item.case_issue) || (item && item.hdd_issue) || (item && item.cooler_issue) || (item && item.printer_issue) || (item && item.generic_issue) || '')).trim();
        }

        function ivenConfirmRow(tr, m){
            // Save to manual bindings via existing batch endpoint
            var items = [{name: m.name, supplier: m.supplier || '', onliner_id: m.id, url: m.url || '', row_idx: m.row_idx}];
            fetch('/api/manual-id-confirm-batch', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({source:'iven_report', items: items})
            }).then(function(r){
                return r.json().catch(function(){ return {}; }).then(function(d){
                    if(!r.ok || !d || d.status !== 'ok'){
                        throw new Error((d && d.message) || ('save_failed_' + r.status));
                    }
                    return d;
                });
            }).then(function(){
                ivenRowStates[m.name] = 'confirmed';
                ivenRowStates[(m.name||'') + '_' + (m.id||'')] = 'confirmed';
                syncLastStatusAfterManualSave(m.name, m.row_idx, m.id);
                tr.style.background = '#f0fdf4';
                var actCell = tr.querySelector('.iven-act-cell');
                if(actCell) actCell.innerHTML = '<span style="color:#16a34a;font-weight:600;font-size:12px;">✓ Сохранено</span>';
                if(typeof loadReviewQueue === 'function') loadReviewQueue();
                if(typeof reloadMainTable === 'function') reloadMainTable();
                if(typeof refreshActionBadges === 'function') refreshActionBadges();
            }).catch(function(err){
                var actCell = tr.querySelector('.iven-act-cell');
                if(actCell){
                    actCell.innerHTML = '<span style="color:#dc2626;font-weight:600;font-size:12px;">Ошибка: ' + escapeHtml(String((err && err.message) || 'save_failed')) + '</span>';
                }
            });
        }

        function ivenRejectRow(tr, m){
            fetch('/api/iven-reject-match', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({name: m.name, supplier: m.supplier || '', row_idx: m.row_idx})
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

        function renderManualPickSaved(btn, candidateName, candidateId){
            var host = btn && (btn.parentElement || (btn.closest ? btn.closest('div') : null));
            if(!host){ return; }
            host.innerHTML = '<span style="color:#16a34a;font-weight:700;font-size:11px;">✓ Сохранено</span>' +
                '<span style="font-size:11px;color:#374151;margin-left:6px;">' + escapeHtml(candidateName || '') + '</span>' +
                '<a href="https://catalog.onliner.by/p/' + encodeURIComponent(candidateId || '') + '" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;margin-left:6px;">' + escapeHtml(candidateId || '') + '</a>';
        }

        function ivenSaveManualId(name, rowIdx, rawId, btn, input, caption, supplier){
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
                    items:[{name:name, supplier:supplier || '', onliner_id:finalId, row_idx: rowIdx}]
                })
            }).then(function(r){
                return r.json().catch(function(){ return {}; }).then(function(d){
                    if(!r.ok || !d || d.status !== 'ok'){
                        throw new Error((d && d.message) || ('save_failed_' + r.status));
                    }
                    return d;
                });
            }).then(function(d){
                if(d && d.status === 'ok'){
                    ivenRowStates[(name||'') + '_' + finalId] = 'confirmed';
                    ivenRowStates[name] = 'confirmed';
                    syncLastStatusAfterManualSave(name, rowIdx, finalId);
                    if(caption) caption.innerHTML = '<span style="color:#16a34a;font-weight:700;">✓ Сохранено в ручные привязки</span>';
                    if(input) input.value = finalId;
                    if(typeof loadReviewQueue === 'function') loadReviewQueue();
                    if(typeof reloadMainTable === 'function') reloadMainTable();
                    if(typeof refreshActionBadges === 'function') refreshActionBadges();
                } else {
                    if(caption) caption.textContent = (d && d.message) || 'Не удалось сохранить';
                }
            }).catch(function(err){
                if(caption) caption.textContent = 'Ошибка сохранения: ' + String((err && err.message) || 'save_failed');
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

        function unifiedReportKey(st){
            var explicit = String((st && st.report_key) || '').trim();
            if(explicit) return explicit;
            var mode = String((st && st.report_mode) || '').trim();
            var title = String((st && st.report_title) || '').trim();
            return (mode || title || 'report').toLowerCase().replace(/[^a-zа-я0-9]+/gi, '_');
        }

        function unifiedReportLabel(st){
            var explicit = String((st && st.report_tab_label) || '').trim();
            if(explicit) return explicit;
            var title = String((st && st.report_title) || '').trim();
            if(title){
                return title.replace(/^Отч[её]т\s+/i, '').replace(/^подбора\s+/i, '').trim() || title;
            }
            return String((st && st.report_mode) || 'Отчёт').trim();
        }

        function unifiedReportCount(st){
            var noMatch = Array.isArray(st && st.no_match) ? st.no_match.length : 0;
            var matches = Array.isArray(st && st.matches) ? st.matches.length : 0;
            return noMatch || Number((st && st.queued) || 0) || matches || Number((st && st.applied) || 0) || 0;
        }

        function rememberUnifiedReport(st){
            if(!st) return '';
            var key = unifiedReportKey(st);
            if(!unifiedIdReportTabs[key]){
                unifiedIdReportOrder.push(key);
            }
            unifiedIdReportTabs[key] = {
                key: key,
                label: unifiedReportLabel(st),
                count: unifiedReportCount(st),
                status: st
            };
            return key;
        }

        function renderUnifiedReportTabs(activeKey){
            var host = document.getElementById('unified-id-report-tabs');
            if(!host) return;
            var keys = unifiedIdReportOrder.filter(function(key){ return !!unifiedIdReportTabs[key]; });
            if(!keys.length){
                host.style.display = 'none';
                host.innerHTML = '';
                return;
            }
            host.style.display = 'flex';
            host.innerHTML = keys.map(function(key){
                var tab = unifiedIdReportTabs[key];
                var active = key === activeKey ? ' active' : '';
                return '<button type="button" class="unified-id-report-tab' + active + '" data-report-key="' + escapeHtml(key) + '">' +
                    '<span>' + escapeHtml(tab.label) + '</span>' +
                    '<span class="unified-id-report-tab-count">' + escapeHtml(String(tab.count || 0)) + '</span>' +
                    '</button>';
            }).join('');
            Array.prototype.forEach.call(host.querySelectorAll('.unified-id-report-tab'), function(button){
                button.addEventListener('click', function(){
                    var key = String(button.getAttribute('data-report-key') || '').trim();
                    var tab = unifiedIdReportTabs[key];
                    if(tab && tab.status){
                        renderIvenModal(tab.status, {skipRemember:true});
                    }
                });
            });
        }

        function renderIvenModal(st, options){
            options = options || {};
            var modal  = document.getElementById('iven-report-modal');
            var tbody  = document.getElementById('iven-modal-tbody');
            var showNM = document.getElementById('iven-modal-show-nomatch');
            if(!modal || !tbody) return;
            if(!st) return;
            lastStatus = st;
            var activeReportKey = options.skipRemember ? unifiedReportKey(st) : rememberUnifiedReport(st);
            renderUnifiedReportTabs(activeReportKey);

            var reportMode = String((st && st.report_mode) || 'iven').toLowerCase();
            var matches = (st && st.matches)  || [];
            var noMatch = (st && st.no_match) || [];
            // For SSD tuning sessions, show "no candidates" list immediately.
            if(showNM && (reportMode === 'ssd' || reportMode === 'hdd' || reportMode === 'cooler' || reportMode === 'printer') && !showNM.checked){
                showNM.checked = true;
            }
            var showNoMatch = showNM && showNM.checked;
            var queuedCpu = noMatch.filter(function(m){ return reportIssueKey(m) === 'queued'; });
            var noModelCpu = noMatch.filter(function(m){ return reportIssueKey(m) === 'no_model'; });
            var noCandCpu = noMatch.filter(function(m){ return reportIssueKey(m) === 'no_candidates'; });

            // Update summary stats
            var el = function(id){ return document.getElementById(id); };
            if(el('iven-modal-title')) el('iven-modal-title').textContent = (st && st.report_title) || (reportMode === 'cpu' ? 'Отчёт CPU N-Tech' : (reportMode === 'cooler' ? 'Отчёт охлаждения N-Tech' : (reportMode === 'printer' ? 'Отчёт принтеров и МФУ N-Tech' : 'Отчёт подбора IVEN-бридж')));
            if(el('iven-modal-subtitle')){
                el('iven-modal-subtitle').textContent =
                    (st && st.report_subtitle)
                    || (reportMode === 'cpu'
                        ? ('Обработано CPU: ' + (queuedCpu.length + noModelCpu.length + noCandCpu.length) + ' товаров N-Tech')
                        : ('Обработано: ' + (matches.length + noMatch.length) + ' товаров N-Tech'));
            }
            if(reportMode !== 'iven'){
                if(el('iven-modal-stat-matched')) el('iven-modal-stat-matched').textContent = queuedCpu.length;
                if(el('iven-modal-stat-nomatch')) el('iven-modal-stat-nomatch').textContent = noModelCpu.length;
                if(el('iven-modal-stat-avgsc')) el('iven-modal-stat-avgsc').textContent = noCandCpu.length;
                if(el('iven-modal-label-matched')) el('iven-modal-label-matched').textContent = 'В очереди';
                if(el('iven-modal-label-nomatch')) el('iven-modal-label-nomatch').textContent = 'Без модели';
                if(el('iven-modal-label-avgsc')) el('iven-modal-label-avgsc').textContent = 'Без кандидатов';
                if(el('iven-modal-show-nomatch-label')) el('iven-modal-show-nomatch-label').textContent = 'Показать проблемные';
            } else {
                if(el('iven-modal-stat-matched')) el('iven-modal-stat-matched').textContent = matches.length;
                if(el('iven-modal-stat-nomatch')) el('iven-modal-stat-nomatch').textContent = noMatch.length;
                if(el('iven-modal-stat-avgsc')){
                    var avgSc = matches.length > 0
                        ? (matches.reduce(function(s,m){ return s + (parseFloat(m.score)||0); }, 0) / matches.length).toFixed(2)
                        : '—';
                    el('iven-modal-stat-avgsc').textContent = avgSc;
                }
                if(el('iven-modal-label-matched')) el('iven-modal-label-matched').textContent = 'Совпало';
                if(el('iven-modal-label-nomatch')) el('iven-modal-label-nomatch').textContent = 'Не найдено';
                if(el('iven-modal-label-avgsc')) el('iven-modal-label-avgsc').textContent = 'Средний Score';
                if(el('iven-modal-show-nomatch-label')) el('iven-modal-show-nomatch-label').textContent = 'Показать без совпадения';
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
            var withoutNoCandidates = withoutCands.filter(function(m){ return reportIssueKey(m) === 'no_candidates'; });
            var withoutNoModel = withoutCands.filter(function(m){ return reportIssueKey(m) === 'no_model'; });
            var noCandForRender = (reportMode === 'ssd' || reportMode === 'hdd' || reportMode === 'cooler' || reportMode === 'printer') ? withoutNoCandidates : withoutCands;

            function cpuMetaHtml(item){
                if(reportMode === 'iven') return '';
                var parts = [];
                var brandValue = String((item && (item.cpu_brand || item.board_brand || item.monitor_brand || item.gpu_vendor || item.ram_brand || item.ssd_brand || item.psu_brand || item.case_brand || item.hdd_brand || item.cooler_brand || item.printer_brand)) || '').trim();
                var modelValue = String((item && (item.cpu_model || item.board_model || item.monitor_model || item.gpu_model || item.gpu_sku || item.ram_sku || item.ssd_model || item.ssd_code || item.psu_model || item.psu_code || item.psu_watt || item.case_model || item.case_code || item.hdd_code || item.hdd_capacity || item.cooler_code || item.cooler_tdp || item.printer_model || item.printer_article)) || '').trim();
                var issueValue = String((item && (item.cpu_issue_label || item.board_issue_label || item.monitor_issue_label || item.gpu_issue_label || item.ram_issue_label || item.ssd_issue_label || item.psu_issue_label || item.case_issue_label || item.hdd_issue_label || item.cooler_issue_label || item.printer_issue_label || item.generic_issue_label)) || '').trim();
                if(brandValue){
                    parts.push('Производитель: <b>' + escapeHtml(brandValue) + '</b>');
                }
                if(modelValue){
                    parts.push('Модель: <b>' + escapeHtml(modelValue) + '</b>');
                }
                if(issueValue){
                    parts.push('Статус: <b>' + escapeHtml(issueValue) + '</b>');
                }
                if(parts.length <= 0) return '';
                return '<div style="margin-top:4px;font-size:11px;color:#64748b;display:flex;gap:10px;flex-wrap:wrap;">' + parts.join('<span style="color:#cbd5e1;">•</span>') + '</div>';
            }

            if(withCands.length > 0){
                var sepC = document.createElement('tr');
                sepC.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:700;border-top:2px solid #bfdbfe;">' +
                    (reportMode !== 'iven'
                        ? ('Подбор для ручного подтверждения (' + withCands.length + '):')
                        : ('Ручная модерация — автоподстановка запрещена для score &lt; 1 (' + withCands.length + '):'))
                    + '</td>';
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
                                '<button class="iven-manual-pick" data-name="' + (m.name||'').replace(/"/g,'&quot;') + '" data-supplier="' + (m.supplier||'').replace(/"/g,'&quot;') + '" data-row="' + (m.row_idx||'') + '" data-id="' + c.id + '" data-cname="' + c.name.replace(/"/g,'&quot;') + '"' +
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
                    var inlineQueryId = 'iven-inline-query-' + (m.row_idx || i);
                    var inlineResultsId = 'iven-inline-results-' + (m.row_idx || i);
                    candsHtml += '<div style="display:flex;align-items:center;gap:6px;padding-top:8px;margin-top:6px;border-top:1px dashed #bfdbfe;flex-wrap:wrap;">' +
                        '<input id="' + manualRowId + '" class="iven-manual-id-input" data-item-name="' + escapeHtml(m.name || '') + '" type="text" inputmode="numeric" placeholder="Вставить Onliner ID вручную" ' +
                        'style="width:210px;padding:4px 8px;border:1px solid #93c5fd;border-radius:4px;font-size:11px;">' +
                        '<button id="' + manualBtnId + '" type="button" style="padding:3px 8px;border:1px solid #2563eb;border-radius:4px;background:#2563eb;color:#fff;font-size:11px;font-weight:600;cursor:pointer;">Сохранить ID</button>' +
                        '<span id="' + manualNoteId + '" style="font-size:11px;color:#64748b;">Сохранится в вечный кеш</span>' +
                        '</div>';
                    candsHtml += '</div>';
                    tr.innerHTML =
                        '<td colspan="2" style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:280px;">' + (m.name || '') + cpuMetaHtml(m) +
                        '<div style="margin-top:6px;padding:6px 7px;border:1px solid #e2e8f0;border-radius:8px;background:#fafafa;">' +
                        '<div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Поиск по БД для этой позиции</div>' +
                        '<input id="' + inlineQueryId + '" type="text" value="' + escapeHtml(m.name || '') + '" placeholder="Уточнить запрос..." style="margin-top:4px;width:100%;padding:4px 7px;border:1px solid #cbd5e1;border-radius:6px;font-size:11px;color:#334155;">' +
                        '<div id="' + inlineResultsId + '" style="margin-top:6px;display:none;border:1px solid #fde68a;border-radius:6px;background:#fffbeb;padding:5px 7px;max-height:150px;overflow:auto;"></div>' +
                        '</div>' +
                        '</td>' +
                        '<td colspan="3" style="padding:7px 14px;">' + candsHtml + '</td>';
                    tbody.appendChild(tr);
                    // Wire pick buttons
                    tr.querySelectorAll('.iven-manual-pick').forEach(function(btn){
                        btn.addEventListener('click', function(){
                            var payload = [{name: btn.dataset.name, supplier: btn.dataset.supplier || '', onliner_id: btn.dataset.id,
                                            url: '', row_idx: btn.dataset.row ? parseInt(btn.dataset.row) : null}];
                            fetch('/api/manual-id-confirm-batch', {
                                method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify({source:'iven_manual_pick', items: payload})
                            }).then(function(r){
                                return r.json().catch(function(){ return {}; }).then(function(d){
                                    if(!r.ok || !d || d.status !== 'ok'){
                                        throw new Error((d && d.message) || ('save_failed_' + r.status));
                                    }
                                    return d;
                                });
                            }).then(function(){
                                ivenRowStates[(btn.dataset.name||'') + '_' + btn.dataset.id] = 'confirmed';
                                ivenRowStates[btn.dataset.name||''] = 'confirmed';
                                syncLastStatusAfterManualSave(btn.dataset.name||'', btn.dataset.row ? parseInt(btn.dataset.row) : null, btn.dataset.id||'');
                                renderManualPickSaved(btn, btn.dataset.cname || '', btn.dataset.id || '');
                                if(typeof loadReviewQueue === 'function') loadReviewQueue();
                                if(typeof reloadMainTable === 'function') reloadMainTable();
                                if(typeof refreshActionBadges === 'function') refreshActionBadges();
                            }).catch(function(err){
                                if(manualNote){
                                    manualNote.textContent = 'Ошибка сохранения: ' + String((err && err.message) || 'save_failed');
                                    manualNote.style.color = '#dc2626';
                                }
                            });
                        });
                    });
                    var manualInput = document.getElementById(manualRowId);
                    var manualBtn = document.getElementById(manualBtnId);
                    var manualNote = document.getElementById(manualNoteId);
                    var inlineQueryInput = document.getElementById(inlineQueryId);
                    var inlineResultsEl = document.getElementById(inlineResultsId);
                    if(manualBtn){
                        manualBtn.addEventListener('click', function(){
                            ivenSaveManualId(m.name || '', m.row_idx, manualInput ? manualInput.value : '', manualBtn, manualInput, manualNote, m.supplier || '');
                        });
                    }
                    if(inlineQueryInput && inlineResultsEl){
                        var timer1 = null;
                        var booted1 = false;
                        inlineQueryInput.addEventListener('focus', function(){
                            if(booted1) return;
                            booted1 = true;
                            renderInlineDbSearch(inlineResultsEl, inlineQueryInput.value || (m.name || ''), manualInput);
                        });
                        inlineQueryInput.addEventListener('input', function(){
                            if(timer1){ clearTimeout(timer1); }
                            timer1 = setTimeout(function(){
                                booted1 = true;
                                var q1 = String(inlineQueryInput.value || '').trim();
                                if(q1.length < 3){
                                    inlineResultsEl.style.display = 'none';
                                    inlineResultsEl.innerHTML = '';
                                    return;
                                }
                                renderInlineDbSearch(inlineResultsEl, q1, manualInput);
                            }, 260);
                        });
                    }
                });
            }

            if(showNoMatch && noCandForRender.length > 0 && reportMode !== 'iven'){
                var compactSep = document.createElement('tr');
                compactSep.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#f8fafc;color:#475569;font-size:12px;font-weight:700;border-top:2px solid #e2e8f0;">' +
                    'Проблемные позиции без кандидатов скрыты из лога: ' + noCandForRender.length +
                    (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') +
                    '</td>';
                tbody.appendChild(compactSep);
            }

            if(showNoMatch && noCandForRender.length > 0 && reportMode === 'iven'){
                var sep = document.createElement('tr');
                sep.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fef9c3;color:#92400e;font-size:12px;font-weight:700;border-top:2px solid #fde68a;">' +
                    (reportMode !== 'iven'
                        ? (reportMode === 'ssd'
                            ? ('Проблемные SSD — без кандидатов (' + noCandForRender.length + ')' + (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') + ':')
                            : (reportMode === 'hdd'
                            ? ('Проблемные HDD — без кандидатов (' + noCandForRender.length + ')' + (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') + ':')
                            : (reportMode === 'cooler'
                            ? ('Проблемное охлаждение — без кандидатов (' + noCandForRender.length + ')' + (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') + ':')
                            : (reportMode === 'printer'
                            ? ('Принтеры / МФУ — без кандидатов (' + noCandForRender.length + ')' + (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') + ':')
                            : ('Проблемные позиции — без модели или без кандидатов (' + noCandForRender.length + ')' + (withoutNoModel.length ? (', без модели: ' + withoutNoModel.length) : '') + ':') ))))
                        : ('Без кандидатов из базы — можно вставить ID вручную (' + withoutCands.length + '):'))
                    + '</td>';
                tbody.appendChild(sep);
                noCandForRender.forEach(function(m, i){
                    var tr = document.createElement('tr');
                    tr.style.cssText = 'background:' + (i%2===0?'#fff':'#fafafa') + ';border-bottom:1px solid #f5f5f5;';
                    var manualRowId = 'iven-nomatch-id-' + (m.row_idx || i);
                    var manualBtnId = 'iven-nomatch-btn-' + (m.row_idx || i);
                    var manualNoteId = 'iven-nomatch-note-' + (m.row_idx || i);
                    var inlineQueryId = 'iven-nomatch-inline-query-' + (m.row_idx || i);
                    var inlineResultsId = 'iven-nomatch-inline-results-' + (m.row_idx || i);
                    tr.innerHTML =
                        '<td colspan="2" style="padding:7px 14px;color:#6b7280;font-size:12px;">' + (m.name || '') + cpuMetaHtml(m) +
                        '<div style="margin-top:6px;padding:6px 7px;border:1px solid #e2e8f0;border-radius:8px;background:#fafafa;">' +
                        '<div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">Поиск по БД для этой позиции</div>' +
                        '<input id="' + inlineQueryId + '" type="text" value="' + escapeHtml(m.name || '') + '" placeholder="Уточнить запрос..." style="margin-top:4px;width:100%;padding:4px 7px;border:1px solid #cbd5e1;border-radius:6px;font-size:11px;color:#334155;">' +
                        '<div id="' + inlineResultsId + '" style="margin-top:6px;display:none;border:1px solid #fde68a;border-radius:6px;background:#fffbeb;padding:5px 7px;max-height:150px;overflow:auto;"></div>' +
                        '</div>' +
                        '</td>' +
                        '<td style="padding:7px;text-align:center;color:#9ca3af;font-size:12px;">—</td>' +
                        '<td style="padding:7px;text-align:center;color:#9ca3af;font-size:12px;">—</td>' +
                        '<td style="padding:7px;">' +
                            '<div style="display:flex;flex-direction:column;gap:6px;align-items:flex-start;">' +
                                '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
                                    '<input id="' + manualRowId + '" class="iven-manual-id-input" data-item-name="' + escapeHtml(m.name || '') + '" type="text" inputmode="numeric" placeholder="Onliner ID вручную" style="width:170px;padding:4px 8px;border:1px solid #d6d3d1;border-radius:4px;font-size:11px;">' +
                                    '<button id="' + manualBtnId + '" type="button" style="padding:3px 8px;border:1px solid #a16207;border-radius:4px;background:#f59e0b;color:#fff;font-size:11px;font-weight:600;cursor:pointer;">Сохранить ID</button>' +
                                '</div>' +
                                '<span id="' + manualNoteId + '" style="font-size:11px;color:#78716c;">Сохранится в вечный кеш</span>' +
                            '</div>' +
                        '</td>';
                    tbody.appendChild(tr);
                    var manualInput = document.getElementById(manualRowId);
                    var manualBtn = document.getElementById(manualBtnId);
                    var manualNote = document.getElementById(manualNoteId);
                    var inlineQueryInput = document.getElementById(inlineQueryId);
                    var inlineResultsEl = document.getElementById(inlineResultsId);
                    if(manualBtn){
                        manualBtn.addEventListener('click', function(){
                            ivenSaveManualId(m.name || '', m.row_idx, manualInput ? manualInput.value : '', manualBtn, manualInput, manualNote, m.supplier || '');
                        });
                    }
                    if(inlineQueryInput && inlineResultsEl){
                        var timer2 = null;
                        var booted2 = false;
                        inlineQueryInput.addEventListener('focus', function(){
                            if(booted2) return;
                            booted2 = true;
                            renderInlineDbSearch(inlineResultsEl, inlineQueryInput.value || (m.name || ''), manualInput);
                        });
                        inlineQueryInput.addEventListener('input', function(){
                            if(timer2){ clearTimeout(timer2); }
                            timer2 = setTimeout(function(){
                                booted2 = true;
                                var q2 = String(inlineQueryInput.value || '').trim();
                                if(q2.length < 3){
                                    inlineResultsEl.style.display = 'none';
                                    inlineResultsEl.innerHTML = '';
                                    return;
                                }
                                renderInlineDbSearch(inlineResultsEl, q2, manualInput);
                            }, 260);
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

        function storeUnifiedReport(st){
            if(!st) return;
            lastStatus = st;
            rememberUnifiedReport(st);
        }

        window.storeUnifiedIdReport = function(status){
            storeUnifiedReport(status);
        };

        window.renderUnifiedIdReportModal = function(status){
            renderIvenModal(status);
        };

        function setAllChecksNote(text, color){
            if(!runAllChecksNote) return;
            runAllChecksNote.textContent = text || '';
            runAllChecksNote.style.color = color || '#64748b';
        }

        function buttonBadgeCount(button){
            if(!button) return 0;
            var badge = button.querySelector('.ntech-check-badge');
            if(!badge) return 0;
            var raw = String(badge.textContent || '').replace(/[^\d]/g, '');
            return raw ? Number(raw) : 0;
        }

        function collectAllCheckTasks(){
            var tasks = [
                {
                    type: 'pc',
                    label: 'TGPC ПЭВМ',
                    button: autoBtn,
                    startUrl: '/api/autofill-tgpc-pc-ids',
                    statusUrl: '/api/autofill-tgpc-pc-status',
                    pcLabel: 'TGPC ПЭВМ',
                    runAlways: false
                },
                {
                    type: 'pc',
                    label: 'N-Tech ПЭВМ',
                    button: autoNtechPcBtn,
                    startUrl: '/api/autofill-ntech-pc-ids',
                    statusUrl: '/api/autofill-ntech-pc-status',
                    pcLabel: 'N-Tech ПЭВМ',
                    runAlways: true
                },
                {
                    type: 'pc',
                    label: 'IVEN ПЭВМ',
                    button: autoIvenPcBtn,
                    startUrl: '/api/autofill-iven-pc-ids',
                    statusUrl: '/api/autofill-iven-pc-status',
                    pcLabel: 'IVEN ПЭВМ',
                    runAlways: true
                },
                {type:'review', label:'Процессоры N-Tech', button:cpuReviewBtn, endpoint:'/api/cpu-review-queue-start'},
                {type:'review', label:'Материнки N-Tech', button:boardReviewBtn, endpoint:'/api/motherboard-review-queue-start'},
                {type:'review', label:'Мониторы N-Tech', button:monitorReviewBtn, endpoint:'/api/monitor-review-queue-start'},
                {type:'review', label:'Видеокарты N-Tech', button:gpuReviewBtn, endpoint:'/api/gpu-review-queue-start'},
                {type:'review', label:'Оперативка N-Tech', button:ramReviewBtn, endpoint:'/api/ram-review-queue-start'},
                {type:'review', label:'SSD N-Tech', button:ssdReviewBtn, endpoint:'/api/ssd-review-queue-start'},
                {type:'review', label:'Блоки питания N-Tech', button:psuReviewBtn, endpoint:'/api/psu-review-queue-start'},
                {type:'review', label:'Корпуса N-Tech', button:caseReviewBtn, endpoint:'/api/case-review-queue-start'},
                {type:'review', label:'HDD N-Tech', button:hddReviewBtn, endpoint:'/api/hdd-review-queue-start'},
                {type:'review', label:'Охлаждение N-Tech', button:coolerReviewBtn, endpoint:'/api/cooler-review-queue-start'},
                {type:'review', label:'Принтеры / МФУ N-Tech', button:printerReviewBtn, endpoint:'/api/printer-review-queue-start'},
                {type:'review', label:'Периферия N-Tech', button:peripheralReviewBtn, endpoint:'/api/peripheral-review-queue-start'},
                {type:'review', label:'Ноутбуки IVEN', button:ivenLaptopReviewBtn, endpoint:'/api/iven-laptop-review-queue-start'},
                {type:'review', label:'Ноутбуки IVEN_zakaz', button:ivenZakazLaptopReviewBtn, endpoint:'/api/iven-zakaz-laptop-review-queue-start'},
                {type:'review', label:'Ноутбуки Tradex', button:tradexLaptopReviewBtn, endpoint:'/api/tradex-laptop-review-queue-start'}
            ];
            Array.prototype.forEach.call(document.querySelectorAll('[data-generic-review-key]'), function(button){
                tasks.push({
                    type: 'generic',
                    label: String(button.getAttribute('data-review-label') || button.textContent || 'Категория N-Tech').trim(),
                    button: button,
                    endpoint: '/api/ntech-category-review-queue-start',
                    key: String(button.getAttribute('data-generic-review-key') || '').trim()
                });
            });
            return tasks.filter(function(task){
                if(!task || !task.button) return false;
                if(task.type === 'pc') return !!task.runAlways || buttonBadgeCount(task.button) > 0;
                return buttonBadgeCount(task.button) > 0;
            });
        }

        function runReviewTaskForAll(task){
            var payload = null;
            var fetchOptions = {method:'POST'};
            if(task.type === 'generic'){
                payload = {key: task.key};
                fetchOptions.headers = {'Content-Type':'application/json'};
                fetchOptions.body = JSON.stringify(payload);
            }
            return fetch(task.endpoint, fetchOptions)
            .then(function(r){
                return r.json().catch(function(){ return {}; }).then(function(d){
                    if(!r.ok || !d || d.status !== 'ok'){
                        throw new Error((d && d.message) || ('HTTP ' + String(r.status || 500)));
                    }
                    return d;
                });
            })
            .then(function(d){
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(hasData){
                    storeUnifiedReport(d);
                    if(ivenReportBtn) ivenReportBtn.style.display = 'inline-block';
                }
                if(Number(d.queued || 0) > 0){
                    var qBtn = document.getElementById('show-review-queue-btn');
                    if(qBtn) qBtn.style.background = '#dbeafe';
                }
                if(typeof loadReviewQueue === 'function') loadReviewQueue();
                return d;
            });
        }

        function runAllIdChecks(){
            if(allChecksRunning) return;
            var tasks = collectAllCheckTasks();
            if(!tasks.length){
                setAllChecksNote('Нет категорий со счётчиками для автопроверки.', '#b45309');
                return;
            }
            allChecksRunning = true;
            var originalBtnHtml = runAllChecksBtn ? runAllChecksBtn.innerHTML : '';
            if(runAllChecksBtn){
                runAllChecksBtn.disabled = true;
                runAllChecksBtn.textContent = 'Запускаю проверки...';
            }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '2%'; ivenBar.style.background = 'linear-gradient(90deg,#2563eb,#06b6d4)'; }
            showBusyOverlay('Все проверки ID', 'Запускаем проверки по очереди...');
            var completed = 0;
            var failed = 0;
            var previousAutoOpen = autoOpenPcUnifiedReport;
            autoOpenPcUnifiedReport = false;

            tasks.reduce(function(chain, task){
                return chain.then(function(){
                    var idx = completed + failed + 1;
                    var pct = Math.max(2, Math.round(((idx - 1) / tasks.length) * 100));
                    if(ivenBar){ ivenBar.style.width = pct + '%'; }
                    if(runAllChecksBtn){ runAllChecksBtn.textContent = 'Проверка ' + idx + '/' + tasks.length; }
                    if(ivenMsg){ ivenMsg.textContent = 'Идёт проверка: ' + task.label + ' (' + idx + ' из ' + tasks.length + ')'; ivenMsg.style.color = '#2563eb'; }
                    setAllChecksNote('Идёт проверка: ' + task.label + ' (' + idx + ' из ' + tasks.length + ')', '#2563eb');
                    if(task.type === 'pc'){
                        return startAutoFill(0, 'Авто ' + task.pcLabel, {
                            button: task.button,
                            startUrl: task.startUrl,
                            statusUrl: task.statusUrl,
                            pcLabel: task.pcLabel
                        }).then(function(result){
                            if(result && result.status === 'error'){
                                failed += 1;
                            } else {
                                completed += 1;
                            }
                        });
                    }
                    return runReviewTaskForAll(task)
                        .then(function(){ completed += 1; })
                        .catch(function(err){
                            failed += 1;
                            console.warn('all id check failed', task.label, err);
                        });
                });
            }, Promise.resolve())
            .then(function(){
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = failed ? 'linear-gradient(90deg,#f59e0b,#d97706)' : 'linear-gradient(90deg,#22c55e,#16a34a)'; }
                var msg = 'Готово: проверок выполнено ' + completed + ' из ' + tasks.length + (failed ? (', ошибок: ' + failed) : '') + '. Отчёты собраны во вкладках.';
                if(ivenMsg){ ivenMsg.textContent = msg; ivenMsg.style.color = failed ? '#b45309' : '#16a34a'; }
                setAllChecksNote(msg, failed ? '#b45309' : '#16a34a');
                if(lastStatus){
                    renderIvenModal(lastStatus);
                }
                if(typeof reloadMainTable === 'function') reloadMainTable();
                if(typeof refreshActionBadges === 'function') refreshActionBadges();
            })
            .finally(function(){
                autoOpenPcUnifiedReport = previousAutoOpen;
                hideBusyOverlay();
                allChecksRunning = false;
                if(runAllChecksBtn){
                    runAllChecksBtn.disabled = false;
                    runAllChecksBtn.innerHTML = originalBtnHtml || 'Запустить все проверки';
                }
                updateNtechCheckCategoryBadges(mainTableRows || []);
            });
        }

        function confirmDangerAction(message, keyword){
            if(!window.confirm(message)){
                return false;
            }
            var expected = String(keyword || 'ОЧИСТИТЬ');
            var typed = window.prompt('Подтверждение: введите "' + expected + '"');
            if(String(typed || '').trim().toUpperCase() !== expected.toUpperCase()){
                if(ivenMsg){
                    ivenMsg.textContent = 'Действие отменено: подтверждение не введено.';
                    ivenMsg.style.color = '#b45309';
                }
                return false;
            }
            return true;
        }

        function clearNonPcIdsForRematch(){
            if(!confirmDangerAction(
                'Опасное действие: очистить все OnlinerID у товаров N-Tech, кроме ПЭВМ? Это массовое изменение.',
                'ОЧИСТИТЬ'
            )){
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
                    updateStatsCounters(s);
                    refreshActionBadges();
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

        function clearDuplicateIdsForNtech(){
            if(!confirmDangerAction(
                'Опасное действие: очистить все дублирующиеся OnlinerID только у товаров N-Tech? ID будет снят у всех строк-дублей N-Tech, включая минимальную цену.',
                'ОЧИСТИТЬ'
            )){
                return;
            }
            if(clearDuplicateIdsBtn){ clearDuplicateIdsBtn.disabled = true; clearDuplicateIdsBtn.textContent = 'Очищаю дубли...'; }
            if(ivenMsg){ ivenMsg.textContent = 'Очищаю дублирующиеся ID у N-Tech...'; ivenMsg.style.color = '#b91c1c'; }
            fetch('/api/clear-ntech-duplicate-onliner-ids', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'clear_ntech_duplicates_failed');
                }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Очищено строк N-Tech: ' + String(d.cleared || 0));
                    ivenMsg.style.color = '#16a34a';
                }
                fetch('/api/stats?_ts=' + Date.now(), {cache:'no-store'})
                .then(function(r){ return r.json(); })
                .then(function(s){
                    updateStatsCounters(s);
                    refreshActionBadges();
                    if(typeof reloadMainTable === 'function'){
                        reloadMainTable();
                    }
                }).catch(function(){});
            }).catch(function(err){
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка очистки дублей N-Tech: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                if(clearDuplicateIdsBtn){ clearDuplicateIdsBtn.disabled = false; clearDuplicateIdsBtn.textContent = 'Очистить дубли ID N-Tech'; }
            });
        }

        function startCpuReviewQueue(){
            var cpuBtn = document.getElementById('cpu-review-btn');
            if(cpuBtn){ cpuBtn.disabled = true; cpuBtn.textContent = 'Собираю CPU...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#8b5cf6,#7c3aed)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу процессоры N-Tech по производителю и модели...'; ivenMsg.style.color = '#7c3aed'; }
            showBusyOverlay('Процессоры N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/cpu-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'cpu_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Процессоров добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ede9fe'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка CPU-подбора: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(cpuBtn){ cpuBtn.disabled = false; cpuBtn.textContent = 'Процессоры N-Tech'; }
            });
        }

        function startBoardReviewQueue(){
            var boardBtn = document.getElementById('board-review-btn');
            if(boardBtn){ boardBtn.disabled = true; boardBtn.textContent = 'Собираю платы...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#14b8a6,#0f766e)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу материнки N-Tech по бренду и модели...'; ivenMsg.style.color = '#0f766e'; }
            showBusyOverlay('Материнки N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/motherboard-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'board_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Материнок добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ccfbf1'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора материнок: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(boardBtn){ boardBtn.disabled = false; boardBtn.textContent = 'Материнки N-Tech'; }
            });
        }

        function startMonitorReviewQueue(){
            var monitorBtn = document.getElementById('monitor-review-btn');
            if(monitorBtn){ monitorBtn.disabled = true; monitorBtn.textContent = 'Собираю мониторы...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#f97316,#c2410c)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу мониторы N-Tech по бренду и модели...'; ivenMsg.style.color = '#c2410c'; }
            showBusyOverlay('Мониторы N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/monitor-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'monitor_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Мониторов добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ffedd5'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора мониторов: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(monitorBtn){ monitorBtn.disabled = false; monitorBtn.textContent = 'Мониторы N-Tech'; }
            });
        }

        function startGpuReviewQueue(){
            var gpuBtn = document.getElementById('gpu-review-btn');
            if(gpuBtn){ gpuBtn.disabled = true; gpuBtn.textContent = 'Собираю GPU...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#ec4899,#be185d)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу видеокарты N-Tech по бренду, GPU и серии...'; ivenMsg.style.color = '#be185d'; }
            showBusyOverlay('Видеокарты N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/gpu-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'gpu_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Видеокарт добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#fce7f3'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора видеокарт: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(gpuBtn){ gpuBtn.disabled = false; gpuBtn.textContent = 'Видеокарты N-Tech'; }
            });
        }

        function startRamReviewQueue(){
            var ramBtn = document.getElementById('ram-review-btn');
            if(ramBtn){ ramBtn.disabled = true; ramBtn.textContent = 'Собираю RAM...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#0ea5e9,#0369a1)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу оперативную память N-Tech по коду и модели...'; ivenMsg.style.color = '#0369a1'; }
            showBusyOverlay('Оперативка N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/ram-review-queue-start', {method:'POST'})
            .then(function(r){
                var contentType = String((r && r.headers && r.headers.get('content-type')) || '').toLowerCase();
                if(!contentType.includes('application/json')){
                    return r.text().then(function(text){
                        var snippet = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 180);
                        throw new Error('Сервер вернул не JSON' + (snippet ? ': ' + snippet : ''));
                    });
                }
                return r.json().then(function(d){
                    if(!r.ok){
                        throw new Error((d && d.message) || ('HTTP ' + String(r.status || '500')));
                    }
                    return d;
                });
            })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'ram_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Оперативки добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#e0f2fe'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора RAM: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(ramBtn){ ramBtn.disabled = false; ramBtn.textContent = 'Оперативка N-Tech'; }
            });
        }

        function startSsdReviewQueue(){
            var ssdBtn = document.getElementById('ssd-review-btn');
            if(ssdBtn){ ssdBtn.disabled = true; ssdBtn.textContent = 'Собираю SSD...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#14b8a6,#0f766e)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу SSD N-Tech по точному коду модели в скобках...'; ivenMsg.style.color = '#0f766e'; }
            showBusyOverlay('SSD N-Tech', 'Собираем кандидатов из локальной базы. Ключ матчинга: точный код модели в скобках.');
            fetch('/api/ssd-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'ssd_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('SSD добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ccfbf1'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора SSD: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(ssdBtn){ ssdBtn.disabled = false; ssdBtn.textContent = 'SSD N-Tech'; }
            });
        }

        function startPsuReviewQueue(){
            var psuBtn = document.getElementById('psu-review-btn');
            if(psuBtn){ psuBtn.disabled = true; psuBtn.textContent = 'Собираю БП...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#10b981,#047857)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу блоки питания N-Tech по бренду, мощности и серии...'; ivenMsg.style.color = '#047857'; }
            showBusyOverlay('Блоки питания N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/psu-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'psu_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Блоков питания добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#d1fae5'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора БП: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(psuBtn){ psuBtn.disabled = false; psuBtn.textContent = 'Блоки питания N-Tech'; }
            });
        }

        function startCaseReviewQueue(){
            var caseBtn = document.getElementById('case-review-btn');
            if(caseBtn){ caseBtn.disabled = true; caseBtn.textContent = 'Собираю корпуса...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#f59e0b,#b45309)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу корпуса N-Tech по бренду, серии и коду...'; ivenMsg.style.color = '#b45309'; }
            showBusyOverlay('Корпуса N-Tech', 'Собираем кандидатов из локальной базы и отправляем в ручную очередь...');
            fetch('/api/case-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'case_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Корпусов добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#fef3c7'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора корпусов: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(caseBtn){ caseBtn.disabled = false; caseBtn.textContent = 'Корпуса N-Tech'; }
            });
        }

        function startHddReviewQueue(){
            var hddBtn = document.getElementById('hdd-review-btn');
            if(hddBtn){ hddBtn.disabled = true; hddBtn.textContent = 'Собираю HDD...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#0e7490,#155e75)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу HDD N-Tech по артикулу в скобках и бренду...'; ivenMsg.style.color = '#155e75'; }
            showBusyOverlay('HDD N-Tech', 'Собираем кандидатов из локальной базы (внутренние и внешние диски)...');
            fetch('/api/hdd-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'hdd_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('HDD добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#cffafe'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора HDD: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(hddBtn){ hddBtn.disabled = false; hddBtn.textContent = 'HDD N-Tech'; }
            });
        }

        function startCoolerReviewQueue(){
            var cBtn = document.getElementById('cooler-review-btn');
            if(cBtn){ cBtn.disabled = true; cBtn.textContent = 'Собираю охлаждение...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#9a3412,#7c2d12)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу охлаждение N-Tech (кулер / СЖО) по бренду и коду...'; ivenMsg.style.color = '#7c2d12'; }
            showBusyOverlay('Охлаждение N-Tech', 'Собираем кандидатов из локальной базы...');
            fetch('/api/cooler-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'cooler_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Позиций охлаждения в очереди: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ffedd5'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора охлаждения: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(cBtn){ cBtn.disabled = false; cBtn.textContent = 'Охлаждение N-Tech'; }
            });
        }

        function startPrinterReviewQueue(){
            var pBtn = document.getElementById('printer-review-btn');
            if(pBtn){ pBtn.disabled = true; pBtn.textContent = 'Собираю принтеры / МФУ...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#7e22ce,#6b21a8)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу принтеры и МФУ N-Tech по бренду и артикулу...'; ivenMsg.style.color = '#6b21a8'; }
            showBusyOverlay('Принтеры / МФУ N-Tech', 'Собираем кандидатов из локальной базы...');
            fetch('/api/printer-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'printer_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Принтеров / МФУ в очереди: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#f3e8ff'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора принтеров / МФУ: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(pBtn){ pBtn.disabled = false; pBtn.textContent = 'Принтеры / МФУ N-Tech'; }
            });
        }

        function startPeripheralReviewQueue(){
            var pBtn = document.getElementById('peripheral-review-btn');
            if(pBtn){ pBtn.disabled = true; pBtn.textContent = 'Собираю периферию...'; }
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#0f766e,#115e59)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Ищу периферию N-Tech (клавиатуры, мыши, гарнитуры, акустика)...'; ivenMsg.style.color = '#115e59'; }
            showBusyOverlay('Периферия N-Tech', 'Собираем кандидатов из локальной базы...');
            fetch('/api/peripheral-review-queue-start', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'peripheral_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Периферии в очереди: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#ccfbf1'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора периферии: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                if(pBtn){ pBtn.disabled = false; pBtn.textContent = 'Периферия N-Tech'; }
            });
        }

        function startGenericNtechReviewQueue(button){
            if(!button || button.disabled){ return; }
            var key = String(button.getAttribute('data-generic-review-key') || '').trim();
            var label = String(button.getAttribute('data-review-label') || button.textContent || 'Категория N-Tech').trim();
            if(!key){ return; }
            var restoreHtml = button.innerHTML;
            button.disabled = true;
            button.textContent = 'Собираю...';
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#64748b,#334155)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Собираю ' + label + ' в ручную очередь...'; ivenMsg.style.color = '#334155'; }
            showBusyOverlay(label, 'Собираем кандидатов из локальной базы и отправляем товары без ID в ручную очередь...');
            fetch('/api/ntech-category-review-queue-start', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({key:key})
            })
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'ntech_category_review_failed');
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || (label + ': добавлено в очередь ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#e2e8f0'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора: ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                button.disabled = false;
                button.innerHTML = restoreHtml;
                updateNtechCheckCategoryBadges(mainTableRows || []);
            });
        }

        function startSupplierLaptopReviewQueue(options){
            options = options || {};
            var button = options.button;
            if(!button || button.disabled){ return; }
            var label = options.label || 'Ноутбуки';
            var supplier = options.supplier || '';
            var endpoint = options.endpoint;
            var errorCode = options.errorCode || 'laptop_review_failed';
            var restoreHtml = button.innerHTML;
            button.disabled = true;
            button.textContent = 'Собираю ноутбуки...';
            if(ivenWrap){ ivenWrap.style.display = 'block'; }
            if(ivenBar){ ivenBar.style.width = '18%'; ivenBar.style.background = 'linear-gradient(90deg,#2563eb,#1d4ed8)'; }
            if(ivenMsg){ ivenMsg.textContent = 'Собираю ' + label + ' в ручную очередь кандидатов...'; ivenMsg.style.color = '#1d4ed8'; }
            showBusyOverlay(label, 'Ищем кандидатов в локальной базе. ID будет применен только после ручного подтверждения.');
            fetch(endpoint, {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || errorCode);
                }
                lastStatus = d;
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = Number(d.queued || 0) > 0 ? 'linear-gradient(90deg,#22c55e,#16a34a)' : 'linear-gradient(90deg,#94a3b8,#64748b)'; }
                if(ivenMsg){
                    ivenMsg.textContent = d.message || ('Ноутбуков ' + supplier + ' добавлено в очередь: ' + String(d.queued || 0));
                    ivenMsg.style.color = Number(d.queued || 0) > 0 ? '#16a34a' : '#475569';
                }
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                if(ivenReportBtn) ivenReportBtn.style.display = hasData ? 'inline-block' : 'none';
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#dbeafe'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                if(ivenWrap){ ivenWrap.style.display = 'block'; }
                if(ivenBar){ ivenBar.style.width = '100%'; ivenBar.style.background = 'linear-gradient(90deg,#f87171,#dc2626)'; }
                if(ivenMsg){
                    ivenMsg.textContent = 'Ошибка подбора ' + label.toLowerCase() + ': ' + String((err && err.message) || err || 'unknown');
                    ivenMsg.style.color = '#dc2626';
                }
            }).finally(function(){
                hideBusyOverlay();
                button.disabled = false;
                button.innerHTML = restoreHtml;
                updateNtechCheckCategoryBadges(mainTableRows || []);
            });
        }

        function startIvenLaptopReviewQueue(){
            startSupplierLaptopReviewQueue({
                button: ivenLaptopReviewBtn,
                label: 'Ноутбуки IVEN',
                supplier: 'IVEN',
                endpoint: '/api/iven-laptop-review-queue-start',
                errorCode: 'iven_laptop_review_failed'
            });
        }

        function startIvenZakazLaptopReviewQueue(){
            startSupplierLaptopReviewQueue({
                button: ivenZakazLaptopReviewBtn,
                label: 'Ноутбуки IVEN_zakaz',
                supplier: 'IVEN_zakaz',
                endpoint: '/api/iven-zakaz-laptop-review-queue-start',
                errorCode: 'iven_zakaz_laptop_review_failed'
            });
        }

        function startTradexLaptopReviewQueue(){
            startSupplierLaptopReviewQueue({
                button: tradexLaptopReviewBtn,
                label: 'Ноутбуки Tradex',
                supplier: 'Tradex',
                endpoint: '/api/tradex-laptop-review-queue-start',
                errorCode: 'tradex_laptop_review_failed'
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

        if(runAllChecksBtn){
            runAllChecksBtn.addEventListener('click', runAllIdChecks);
        }
        if(clearNonPcBtn){
            clearNonPcBtn.addEventListener('click', clearNonPcIdsForRematch);
        }
        if(clearDuplicateIdsBtn){
            clearDuplicateIdsBtn.addEventListener('click', clearDuplicateIdsForNtech);
        }
        if(cpuReviewBtn){
            cpuReviewBtn.addEventListener('click', startCpuReviewQueue);
        }
        if(boardReviewBtn){
            boardReviewBtn.addEventListener('click', startBoardReviewQueue);
        }
        if(monitorReviewBtn){
            monitorReviewBtn.addEventListener('click', startMonitorReviewQueue);
        }
        if(gpuReviewBtn){
            gpuReviewBtn.addEventListener('click', startGpuReviewQueue);
        }
        if(ramReviewBtn){
            ramReviewBtn.addEventListener('click', startRamReviewQueue);
        }
        if(ssdReviewBtn){
            ssdReviewBtn.addEventListener('click', startSsdReviewQueue);
        }
        if(psuReviewBtn){
            psuReviewBtn.addEventListener('click', startPsuReviewQueue);
        }
        if(caseReviewBtn){
            caseReviewBtn.addEventListener('click', startCaseReviewQueue);
        }
        if(hddReviewBtn){
            hddReviewBtn.addEventListener('click', startHddReviewQueue);
        }
        if(coolerReviewBtn){
            coolerReviewBtn.addEventListener('click', startCoolerReviewQueue);
        }
        if(printerReviewBtn){
            printerReviewBtn.addEventListener('click', startPrinterReviewQueue);
        }
        if(peripheralReviewBtn){
            peripheralReviewBtn.addEventListener('click', startPeripheralReviewQueue);
        }
        if(ivenLaptopReviewBtn){
            ivenLaptopReviewBtn.addEventListener('click', startIvenLaptopReviewQueue);
        }
        if(ivenZakazLaptopReviewBtn){
            ivenZakazLaptopReviewBtn.addEventListener('click', startIvenZakazLaptopReviewQueue);
        }
        if(tradexLaptopReviewBtn){
            tradexLaptopReviewBtn.addEventListener('click', startTradexLaptopReviewQueue);
        }
        Array.prototype.forEach.call(document.querySelectorAll('[data-generic-review-key]'), function(button){
            button.addEventListener('click', function(){
                startGenericNtechReviewQueue(button);
            });
        });

        if(ivenReportBtn){
            ivenReportBtn.addEventListener('click', function(){
                renderIvenModal(lastStatus);
            });
        }

    })();
    // ─────────────────────────────────────────────────────────────────────────

    var tableEl = document.getElementById('tbl-main');
    if(tableEl){
        tableEl.addEventListener('click', handleNoIdTableClick);
    }
}
