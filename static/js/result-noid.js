function getNoIdInlineState(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx >= 0 && noIdInlinePickerState && Number(noIdInlinePickerState.rowIdx) === idx){
        return noIdInlinePickerState;
    }
    return null;
}

function renderNoIdInlineDbSearch(rowIdx, state){
    var dbQuery = String((state && state.dbQuery) || (state && state.queryName) || '').trim();
    var dbItems = Array.isArray(state && state.dbItems) ? state.dbItems : [];
    var dbLoading = !!(state && state.dbLoading);
    var html = '<div class="noid-inline-db">';
    html += '<div style="font-size:10px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px;">Поиск в моей базе Onliner</div>';
    html += '<div class="noid-inline-db-row">';
    html += '<input class="noid-inline-db-input" data-db-row-idx="' + rowIdx + '" type="text" value="' + escapeHtml(dbQuery) + '" placeholder="Уточнить запрос: бренд, модель, OnlinerID">';
    html += '<button type="button" class="noid-pick-btn noid-inline-db-run" data-db-row-idx="' + rowIdx + '" style="margin-top:0;">Найти</button>';
    html += '</div>';
    if(dbLoading){
        html += '<div class="noid-inline-note" style="margin-top:6px;">Ищу в локальной базе...</div>';
    } else if(dbItems.length){
        html += '<div class="noid-inline-db-results">';
        dbItems.slice(0, 10).forEach(function(item){
            var candidateId = String((item && item.id) || '').trim();
            var candidateName = String((item && item.name) || '').trim();
            var candidateUrl = String((item && item.url) || '').trim();
            var source = String((item && item.source) || 'local_db').trim();
            html += '<div class="noid-inline-db-result">';
            html += '<div style="min-width:0;">';
            html += '<div class="noid-inline-db-title">' + highlightCandidateName(dbQuery, candidateName || candidateId || 'Кандидат без названия') + '</div>';
            html += '<div class="noid-inline-db-sub">ID: ' + escapeHtml(candidateId || '—') + ' · ' + escapeHtml(source) + '</div>';
            html += '</div>';
            html += '<div class="noid-inline-actions">';
            if(candidateUrl){
                html += '<a href="' + escapeHtml(candidateUrl) + '" target="_blank" rel="noopener noreferrer" class="noid-inline-open">Открыть</a>';
            }
            html += '<button type="button" class="noid-inline-apply noid-inline-db-apply" data-row-idx="' + rowIdx + '" data-oid="' + escapeHtml(candidateId) + '" data-url="' + escapeHtml(candidateUrl) + '">Подставить ID</button>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
    } else if(dbQuery){
        html += '<div class="noid-inline-note" style="margin-top:6px;">В базе ничего не найдено. Попробуй укоротить запрос до модели или артикула.</div>';
    }
    html += '</div>';
    return html;
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
        html += renderNoIdInlineDbSearch(rowIdx, state);
    }
    html += '</div>';
    return html;
}

function renderMainTableIdCell(oid, row){
    var hasId = !!String(oid || '').trim();
    var rowIdx = Number((row && row[8]) || -1);
    if(hasId){
        var canClear = loadedSupplierCount <= 1;
        return '<b style="color:#2e7d32">' + escapeHtml(oid) + '</b>'
            + (canClear
                ? ('<div><button type="button" class="noid-pick-btn id-clear-btn" data-row-idx="' + rowIdx + '" style="border-color:#ef4444;color:#b91c1c;">Снять ID</button></div>')
                : '');
    }
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
    noIdInlinePickerState = { rowIdx: -1, loading: false, applyingId: '', message: '', items: [], queryName: '', dbQuery: '', dbItems: [], dbLoading: false };
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
        queryName: String(row[1] || ''),
        dbQuery: compactBrandModelQuery(String(row[1] || '')) || String(row[1] || ''),
        dbItems: [],
        dbLoading: false
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
        if(!noIdInlinePickerState.items.length){
            runNoIdInlineDbSearch(idx, noIdInlinePickerState.dbQuery, false);
        }
    }).catch(function(){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.loading = false;
        noIdInlinePickerState.items = [];
        noIdInlinePickerState.message = 'Ошибка поиска кандидатов Onliner.';
        redrawMainTablePreservePage();
        runNoIdInlineDbSearch(idx, noIdInlinePickerState.dbQuery, false);
    });
}

function runNoIdInlineDbSearch(rowIdx, query, forceDraw){
    var idx = Number(rowIdx || -1);
    if(idx < 0 || Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
    var q = String(query || '').trim();
    noIdInlinePickerState.dbQuery = q;
    if(q.length < 2){
        noIdInlinePickerState.dbItems = [];
        noIdInlinePickerState.dbLoading = false;
        if(forceDraw !== false){ redrawMainTablePreservePage(); }
        return;
    }
    noIdInlinePickerState.dbLoading = true;
    noIdInlinePickerState.dbItems = [];
    if(forceDraw !== false){ redrawMainTablePreservePage(); }
    fetch('/api/onliner-db-search?q=' + encodeURIComponent(q) + '&_ts=' + Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(data){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.dbLoading = false;
        noIdInlinePickerState.dbItems = Array.isArray(data && data.items) ? data.items : [];
        redrawMainTablePreservePage();
    }).catch(function(){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.dbLoading = false;
        noIdInlinePickerState.dbItems = [];
        noIdInlinePickerState.message = 'Кандидаты Onliner не найдены. Поиск по базе временно недоступен.';
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
                supplier: String(row[3] || ''),
                onliner_id: finalId,
                url: String(url || '')
            }]
        })
    }).then(function(r){
        return r.text().then(function(text){
            var data = null;
            try {
                data = text ? JSON.parse(text) : null;
            } catch(e) {
                data = {status: 'error', message: text || ('HTTP ' + r.status)};
            }
            if(!r.ok && data && !data.message){
                data.message = 'HTTP ' + r.status;
            }
            return data;
        });
    }).then(function(d){
        if(!d || d.status !== 'ok'){
            var error = new Error((d && d.message) || 'save_failed');
            if(d){
                error.payload = d;
            }
            throw error;
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
                updateNtechCheckCategoryBadges(mainTableRows);
                renderMainTableFallback();
            });
        }
        if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
        runPreExportQualityCheck();
    }).catch(function(err){
        if(Number(noIdInlinePickerState.rowIdx) !== idx){ return; }
        noIdInlinePickerState.applyingId = '';
        var duplicateMessage = formatNoIdDuplicateMessage(err);
        noIdInlinePickerState.message = duplicateMessage || ('Не удалось сохранить ID: ' + String((err && err.message) || err || 'ошибка'));
        redrawMainTablePreservePage();
        if(duplicateMessage){
            alert(duplicateMessage);
        }
    });
}

function formatNoIdDuplicateMessage(err){
    var payload = err && err.payload;
    if(!payload || payload.code !== 'duplicate_id_assigned'){
        return '';
    }
    var blocked = Array.isArray(payload.blocked) ? payload.blocked : [];
    var first = blocked.length ? blocked[0] : null;
    var conflicts = first && Array.isArray(first.conflicts) ? first.conflicts : [];
    var conflict = conflicts.length ? conflicts[0] : null;
    var oid = String((first && first.onliner_id) || '').trim();
    var supplier = String((conflict && conflict.supplier) || '').trim();
    var name = String((conflict && conflict.name) || '').trim();
    var rowIdx = String((conflict && conflict.row_idx) || '').trim();
    var msg = 'Данный ID' + (oid ? (' ' + oid) : '') + ' уже присвоен';
    if(supplier){ msg += ' у поставщика ' + supplier; }
    msg += '.';
    if(name){ msg += '\nТовар: ' + name; }
    else if(rowIdx){ msg += '\nСтрока: ' + rowIdx; }
    return msg;
}

function clearMainTableId(rowIdx){
    var idx = Number(rowIdx || -1);
    if(idx < 0){ return; }
    var row = (mainTableRows || []).find(function(r){
        return Number((r && r[8]) || -1) === idx;
    });
    if(!row){ return; }
    var currentId = String((row && row[0]) || '').trim();
    if(!currentId){ return; }
    var itemName = String((row && row[1]) || '').trim();
    if(!window.confirm('Снять OnlinerID у товара "' + itemName + '"?\nID ' + currentId + ' будет удалён из строки и заблокирован в вечном кеше.')){ return; }
    fetch('/api/manual-id-clear', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            source: 'inline_id_clear',
            item: {
                row_idx: idx,
                name: itemName,
                supplier: String((row && row[3]) || '').trim()
            }
        })
    }).then(function(r){
        return r.text().then(function(text){
            var data = null;
            try {
                data = text ? JSON.parse(text) : null;
            } catch(e) {
                data = {status: 'error', message: text || ('HTTP ' + r.status)};
            }
            if(!r.ok && data && !data.message){
                data.message = 'HTTP ' + r.status;
            }
            return data;
        });
    }).then(function(d){
        if(!d || d.status !== 'ok'){
            throw new Error((d && d.message) || 'clear_failed');
        }
        row[0] = '';
        if(tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        } else {
            renderMainTableFallback();
        }
        if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
        runPreExportQualityCheck();
    }).catch(function(err){
        alert('Не удалось снять ID: ' + String((err && err.message) || err || 'ошибка'));
    });
}

function handleNoIdTableClick(e){
    var clearBtn = e.target.closest('.id-clear-btn');
    if(clearBtn){
        e.preventDefault();
        clearMainTableId(clearBtn.getAttribute('data-row-idx'));
        return;
    }
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
    var dbRunBtn = e.target.closest('.noid-inline-db-run');
    if(dbRunBtn){
        e.preventDefault();
        var dbIdx = dbRunBtn.getAttribute('data-db-row-idx');
        var input = document.querySelector('.noid-inline-db-input[data-db-row-idx="' + dbIdx + '"]');
        runNoIdInlineDbSearch(dbIdx, input ? input.value : '', true);
        return;
    }
    var closeBtn = e.target.closest('.noid-inline-close');
    if(closeBtn){
        e.preventDefault();
        closeNoIdInlinePicker();
    }
}

var noIdDbSearchTimer = null;
document.addEventListener('input', function(e){
    var input = e.target && e.target.closest ? e.target.closest('.noid-inline-db-input') : null;
    if(!input){ return; }
    var rowIdx = input.getAttribute('data-db-row-idx');
    var value = String(input.value || '');
    if(Number(noIdInlinePickerState.rowIdx) !== Number(rowIdx || -1)){ return; }
    noIdInlinePickerState.dbQuery = value;
    if(noIdDbSearchTimer){ clearTimeout(noIdDbSearchTimer); }
    noIdDbSearchTimer = setTimeout(function(){
        runNoIdInlineDbSearch(rowIdx, value, true);
    }, 350);
});
