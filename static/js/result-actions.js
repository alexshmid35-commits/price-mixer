function initNoIdFilterUI(){
    var btn = document.getElementById('toggle-noid-btn');
    var duplicateBtn = document.getElementById('toggle-duplicate-id-btn');
    var exportBtn = document.getElementById('export-category-analytics-btn');
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
    // ── IVEN Bridge autofill ──────────────────────────────────────────────────
    (function(){
        var clearNonPcBtn = document.getElementById('clear-nonpc-ids-btn');
        var clearDuplicateIdsBtn = document.getElementById('clear-duplicate-ids-btn');
        var ivenLaptopReviewBtn = document.getElementById('iven-laptop-review-btn');
        var ivenZakazLaptopReviewBtn = document.getElementById('iven-zakaz-laptop-review-btn');
        var tradexLaptopReviewBtn = document.getElementById('tradex-laptop-review-btn');
        var lastStatus    = null;
        var unifiedIdReportTabs = {};
        var unifiedIdReportOrder = [];

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

        function confirmDangerAction(message, keyword){
            if(!window.confirm(message)){
                return false;
            }
            var expected = String(keyword || 'ОЧИСТИТЬ');
            var typed = window.prompt('Подтверждение: введите "' + expected + '"');
            if(String(typed || '').trim().toUpperCase() !== expected.toUpperCase()){
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
            fetch('/api/clear-all-nonpc-onliner-ids', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'clear_nonpc_failed');
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
                console.warn('clear non-PC IDs failed', err);
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
            fetch('/api/clear-ntech-duplicate-onliner-ids', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || 'clear_ntech_duplicates_failed');
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
                console.warn('clear duplicate N-Tech IDs failed', err);
            }).finally(function(){
                if(clearDuplicateIdsBtn){ clearDuplicateIdsBtn.disabled = false; clearDuplicateIdsBtn.textContent = 'Очистить дубли ID N-Tech'; }
            });
        }

        function startSupplierLaptopReviewQueue(options){
            options = options || {};
            var button = options.button;
            if(!button || button.disabled){ return; }
            var label = options.label || 'Ноутбуки';
            var endpoint = options.endpoint;
            var errorCode = options.errorCode || 'laptop_review_failed';
            var restoreHtml = button.innerHTML;
            button.disabled = true;
            button.textContent = 'Собираю ноутбуки...';
            showBusyOverlay(label, 'Ищем кандидатов в локальной базе. ID будет применен только после ручного подтверждения.');
            fetch(endpoint, {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(!d || d.status !== 'ok'){
                    throw new Error((d && d.message) || errorCode);
                }
                lastStatus = d;
                var hasData = (d.matches && d.matches.length > 0) || (d.no_match && d.no_match.length > 0);
                loadReviewQueue();
                var qBtn = document.getElementById('show-review-queue-btn');
                if(qBtn && Number(d.queued || 0) > 0){ qBtn.style.background = '#dbeafe'; }
                if(hasData){
                    setTimeout(function(){ renderIvenModal(lastStatus); }, 120);
                }
            }).catch(function(err){
                console.warn('laptop review failed', label, err);
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
                endpoint: '/api/iven-laptop-review-queue-start',
                errorCode: 'iven_laptop_review_failed'
            });
        }

        function startIvenZakazLaptopReviewQueue(){
            startSupplierLaptopReviewQueue({
                button: ivenZakazLaptopReviewBtn,
                label: 'Ноутбуки IVEN_zakaz',
                endpoint: '/api/iven-zakaz-laptop-review-queue-start',
                errorCode: 'iven_zakaz_laptop_review_failed'
            });
        }

        function startTradexLaptopReviewQueue(){
            startSupplierLaptopReviewQueue({
                button: tradexLaptopReviewBtn,
                label: 'Ноутбуки Tradex',
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

        if(clearNonPcBtn){
            clearNonPcBtn.addEventListener('click', clearNonPcIdsForRematch);
        }
        if(clearDuplicateIdsBtn){
            clearDuplicateIdsBtn.addEventListener('click', clearDuplicateIdsForNtech);
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
    })();
    // ─────────────────────────────────────────────────────────────────────────

    var tableEl = document.getElementById('tbl-main');
    if(tableEl){
        tableEl.addEventListener('click', handleNoIdTableClick);
    }
}
