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
                supplier: String(issue.supplier || ''),
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
        if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
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
