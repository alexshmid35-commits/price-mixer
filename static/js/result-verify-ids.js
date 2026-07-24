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
    compactVerifyIdCards('verify-all-ids-results');
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
                supplier: String(issue.supplier || ''),
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
        if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
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
