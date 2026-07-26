(function(){
    'use strict';

    var state = { jobId: '', page: 1, pages: 0, totalItems: 0, pollTimer: null, searchTimer: null, job: null, lastRenderedProcessed: -1, selected: new Set() };

    function byId(id){ return document.getElementById(id); }

    function requestJson(url, options){
        return fetch(url, options || {}).then(function(response){
            return response.text().then(function(text){
                var data = {};
                try { data = text ? JSON.parse(text) : {}; } catch(_err){ data = {}; }
                if(!response.ok || data.ok === false || data.status === 'error'){
                    throw new Error(data.error || data.message || ('HTTP ' + response.status));
                }
                return data;
            });
        });
    }

    function tierLabel(tier){
        return ({
            exact: 'Точное название',
            strong: 'Сильный кандидат',
            ambiguous: 'Спорные варианты',
            possible: 'Возможное совпадение',
            none: 'Без кандидатов'
        })[String(tier || '')] || 'Без кандидатов';
    }

    function reasonLabel(reason){
        return ({
            exact_name: 'полное название',
            strict_article: 'точный артикул',
            article: 'артикул',
            article_like: 'похожий артикул',
            motherboard_model: 'модель платы',
            motherboard_model_close: 'близкая модель платы',
            numeric_model: 'числовая модель',
            model_token: 'модель',
            paren_model: 'модель в скобках',
            brand_model_tokens: 'бренд и модель',
            tgpc_code_exact: 'точный код',
            apple_article: 'артикул Apple',
            tokens: 'совпавшие слова'
        })[String(reason || '')] || String(reason || 'текстовое совпадение');
    }

    function chip(label, value){
        return '<span class="experimental-noid-chip">' + escapeHtml(label) + ' <strong>' + escapeHtml(String(value || 0)) + '</strong></span>';
    }

    function summaryHtml(job){
        var tiers = (job && job.tier_counts) || {};
        var decisions = (job && job.decision_counts) || {};
        return chip('Точные', tiers.exact) +
            chip('Сильные', tiers.strong) +
            chip('Спорные', tiers.ambiguous) +
            chip('Возможные', tiers.possible) +
            chip('Без кандидатов', tiers.none) +
            chip('Подтверждено', decisions.confirmed) +
            chip('Пропущено', decisions.skipped) +
            chip('Из кэша', job && job.cache_hits) +
            chip('Новых расчётов', job && job.cache_misses);
    }

    function fillFilter(select, rows, emptyLabel){
        if(!select){ return; }
        var previous = select.value;
        var html = '<option value="">' + escapeHtml(emptyLabel) + '</option>';
        (rows || []).forEach(function(row){
            var name = String((row && row.name) || '').trim();
            if(!name){ return; }
            html += '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + ' (' + Number(row.count || 0) + ')</option>';
        });
        select.innerHTML = html;
        if(Array.prototype.some.call(select.options, function(option){ return option.value === previous; })){
            select.value = previous;
        }
    }

    function renderStatus(payload, options){
        var job = payload && payload.job;
        state.job = job || null;
        var startBtn = byId('experimental-noid-start-btn');
        var openBtn = byId('experimental-noid-open-btn');
        var note = byId('experimental-noid-note');
        var progress = byId('experimental-noid-progress');
        var progressValue = byId('experimental-noid-progress-value');
        var summary = byId('experimental-noid-summary');
        var reportNote = byId('experimental-noid-report-note');
        var reportSummary = byId('experimental-noid-report-summary');
        if(!job){
            if(startBtn){ startBtn.disabled = false; startBtn.textContent = 'Подобрать без ID, кроме ПЭВМ'; }
            if(openBtn){ openBtn.disabled = true; }
            if(note){ note.textContent = 'ПЭВМ исключены и проверяются в отдельном модуле.'; }
            if(progress){ progress.hidden = true; }
            if(summary){ summary.innerHTML = ''; }
            return;
        }
        state.jobId = String(job.job_id || '');
        var running = job.status === 'running' || job.status === 'queued';
        var percent = Math.max(0, Math.min(100, Number(job.percent || 0)));
        if(startBtn){
            startBtn.disabled = running;
            startBtn.textContent = running ? ('Подбираю ' + percent + '%') : 'Пересобрать без ПЭВМ';
        }
        if(openBtn){ openBtn.disabled = !state.jobId; }
        if(note){
            var jobMessage = String(job.message || '');
            var scopeHint = !running && jobMessage.indexOf('ПЭВМ исключено:') < 0
                ? ' Пересобери отчёт: новый подбор исключит ПЭВМ.'
                : '';
            note.textContent = jobMessage + (job.error ? (' ' + job.error) : '') + scopeHint;
        }
        if(progress){ progress.hidden = !running; }
        if(progressValue){ progressValue.style.width = percent + '%'; }
        if(summary){ summary.innerHTML = summaryHtml(job); }
        if(reportSummary){ reportSummary.innerHTML = summaryHtml(job); }
        if(reportNote){
            reportNote.textContent = 'Обработано ' + Number(job.processed || 0) + ' из ' + Number(job.total || 0) + '. ' + String(job.message || '');
        }
        fillFilter(byId('experimental-noid-supplier-filter'), job.suppliers, 'Все поставщики');
        fillFilter(byId('experimental-noid-category-filter'), job.categories, 'Все категории');
        var modal = byId('experimental-noid-modal');
        var processed = Number(job.processed || 0);
        if(!options || !options.skipItemRefresh){
            if(modal && modal.classList.contains('active') && processed !== state.lastRenderedProcessed){
                state.lastRenderedProcessed = processed;
                loadItems();
            }
        } else {
            state.lastRenderedProcessed = processed;
        }
        if(running){
            clearTimeout(state.pollTimer);
            state.pollTimer = setTimeout(loadStatus, 1800);
        }
    }

    function loadStatus(options){
        var query = state.jobId ? ('?job_id=' + encodeURIComponent(state.jobId) + '&_ts=' + Date.now()) : ('?_ts=' + Date.now());
        return requestJson('/api/experimental-noid/status' + query).then(function(payload){
            renderStatus(payload, options);
            return payload;
        }).catch(function(error){
            var note = byId('experimental-noid-note');
            if(note){ note.textContent = error.message; }
        });
    }

    function startJob(){
        var button = byId('experimental-noid-start-btn');
        if(button){ button.disabled = true; button.textContent = 'Запускаю...'; }
        requestJson('/api/experimental-noid/start', {method: 'POST'}).then(function(payload){
            state.jobId = String(payload.job_id || '');
            state.page = 1;
            return loadStatus();
        }).then(function(){
            openReport();
        }).catch(function(error){
            if(button){ button.disabled = false; button.textContent = 'Подобрать все без ID'; }
            var note = byId('experimental-noid-note');
            if(note){ note.textContent = error.message; }
        });
    }

    function activeCandidates(item){
        return (Array.isArray(item && item.candidates) ? item.candidates : []).filter(function(candidate){
            return !candidate.rejected;
        });
    }

    function renderCandidate(item, candidate){
        var score = Number(candidate.score || 0).toFixed(3);
        var disabled = item.decision_state !== 'open';
        var html = '<div class="experimental-noid-candidate' + (candidate.rejected ? ' rejected' : '') + '">';
        html += '<div><div class="experimental-noid-candidate-name">' + highlightCandidateName(item.product_name || '', candidate.name || candidate.id || '') + '</div>';
        html += renderCandidateBadges(candidate || {});
        html += '<div class="experimental-noid-candidate-meta">ID ' + escapeHtml(String(candidate.id || '')) + ' · score ' + escapeHtml(score) + ' · ' + escapeHtml(reasonLabel(candidate.reason)) + '</div></div>';
        html += '<div class="experimental-noid-candidate-actions">';
        if(candidate.url){ html += '<a class="experimental-noid-open" href="' + escapeHtml(candidate.url) + '" target="_blank" rel="noopener noreferrer">Открыть</a>'; }
        if(candidate.rejected){
            html += '<span class="experimental-noid-tag">Отклонён</span>';
        } else if(!disabled){
            html += '<button class="experimental-noid-confirm" data-exp-action="confirm" data-item-key="' + escapeHtml(item.item_key) + '" data-candidate-id="' + escapeHtml(String(candidate.id || '')) + '">Подтвердить</button>';
            html += '<button class="experimental-noid-reject" data-exp-action="reject_candidate" data-item-key="' + escapeHtml(item.item_key) + '" data-candidate-id="' + escapeHtml(String(candidate.id || '')) + '">Отклонить</button>';
        }
        html += '</div></div>';
        return html;
    }

    function renderItem(item){
        var candidates = Array.isArray(item.candidates) ? item.candidates : [];
        var active = activeCandidates(item);
        var tier = String(item.confidence_tier || 'none');
        var selectable = item.decision_state === 'open';
        var selected = state.selected.has(String(item.item_key || ''));
        var html = '<div class="experimental-noid-item' + (selected ? ' is-selected' : '') + '" data-item-key="' + escapeHtml(item.item_key || '') + '"' + (selectable ? ' data-selectable="true"' : '') + '>';
        html += '<div class="experimental-noid-local">';
        html += '<div class="experimental-noid-local-name"' + (selectable ? ' data-exp-select-toggle="' + escapeHtml(item.item_key) + '" role="button" tabindex="0" title="Нажми, чтобы выбрать товар"' : '') + '>' + escapeHtml(item.product_name || '') + '</div>';
        html += '<div class="experimental-noid-local-meta">';
        html += '<span class="experimental-noid-tag">' + escapeHtml(item.supplier || 'Без поставщика') + '</span>';
        html += '<span class="experimental-noid-tag">' + escapeHtml(item.category || 'Без категории') + '</span>';
        html += '<span class="experimental-noid-tag ' + escapeHtml(tier) + '">' + escapeHtml(tierLabel(tier)) + '</span>';
        if(Number(item.occurrences || 1) > 1){ html += '<span class="experimental-noid-tag">Позиций: ' + Number(item.occurrences) + '</span>'; }
        if(item.decision_state !== 'open'){ html += '<span class="experimental-noid-tag">' + escapeHtml(item.decision_state === 'confirmed' ? 'Подтверждён' : 'Пропущен') + '</span>'; }
        html += '</div>';
        if(item.decision_state === 'open'){
            html += '<div class="experimental-noid-item-actions"><button class="btn btn-outline" data-exp-action="skip" data-item-key="' + escapeHtml(item.item_key) + '">Пропустить товар</button></div>';
        }
        html += '</div><div class="experimental-noid-candidates">';
        if(candidates.length){
            candidates.forEach(function(candidate){ html += renderCandidate(item, candidate); });
        } else {
            html += '<div class="experimental-noid-empty">Кандидаты в локальной базе не найдены.</div>';
        }
        if(candidates.length && !active.length){
            html += '<div class="experimental-noid-empty">Все найденные варианты отклонены.</div>';
        }
        html += '</div></div>';
        return html;
    }

    function loadItems(){
        var list = byId('experimental-noid-list');
        if(!state.jobId){
            if(list){ list.innerHTML = '<div class="experimental-noid-empty">Сначала запусти подбор.</div>'; }
            return Promise.resolve();
        }
        if(list){ list.innerHTML = '<div class="experimental-noid-empty">Загружаю кандидатов...</div>'; }
        var params = new URLSearchParams({job_id: state.jobId, page: String(state.page), limit: '40'});
        var mappings = {
            supplier: 'experimental-noid-supplier-filter',
            category: 'experimental-noid-category-filter',
            confidence_tier: 'experimental-noid-tier-filter',
            decision_state: 'experimental-noid-state-filter',
            query: 'experimental-noid-search'
        };
        Object.keys(mappings).forEach(function(key){
            var field = byId(mappings[key]);
            if(field && String(field.value || '').trim()){ params.set(key, String(field.value).trim()); }
        });
        return requestJson('/api/experimental-noid/items?' + params.toString() + '&_ts=' + Date.now()).then(function(payload){
            state.page = Number(payload.page || 1);
            state.pages = Number(payload.pages || 0);
            state.totalItems = Number(payload.total || 0);
            if(list){
                var items = Array.isArray(payload.items) ? payload.items : [];
                list.innerHTML = items.length ? items.map(renderItem).join('') : '<div class="experimental-noid-empty">По выбранным фильтрам позиций нет.</div>';
            }
            updateBulkControls();
            var label = byId('experimental-noid-page-label');
            if(label){ label.textContent = 'Страница ' + (state.pages ? state.page : 0) + ' из ' + state.pages + ' · товаров ' + Number(payload.total || 0); }
            var prev = byId('experimental-noid-prev-btn');
            var next = byId('experimental-noid-next-btn');
            if(prev){ prev.disabled = state.page <= 1; }
            if(next){ next.disabled = !state.pages || state.page >= state.pages; }
        }).catch(function(error){
            if(list){ list.innerHTML = '<div class="experimental-noid-empty">' + escapeHtml(error.message) + '</div>'; }
        });
    }

    function updateLocalPageLabel(){
        var label = byId('experimental-noid-page-label');
        if(label){ label.textContent = 'Страница ' + (state.pages ? state.page : 0) + ' из ' + state.pages + ' · товаров ' + Math.max(0, state.totalItems); }
    }

    function updateBulkControls(){
        var count = state.selected.size;
        var label = byId('experimental-noid-selected-count');
        if(label){ label.textContent = 'Выбрано: ' + count; }
        ['experimental-noid-bulk-confirm-btn','experimental-noid-bulk-skip-btn'].forEach(function(id){
            var button = byId(id);
            if(button){ button.disabled = !count; }
        });
        var selectPage = byId('experimental-noid-select-page');
        var items = Array.prototype.slice.call(document.querySelectorAll('.experimental-noid-item[data-selectable="true"]'));
        if(selectPage){
            selectPage.checked = !!items.length && items.every(function(item){ return state.selected.has(String(item.dataset.itemKey || '')); });
            selectPage.indeterminate = items.some(function(item){ return state.selected.has(String(item.dataset.itemKey || '')); }) && !selectPage.checked;
        }
    }

    function toggleItemSelection(itemKey){
        var key = String(itemKey || '');
        if(!key){ return; }
        if(state.selected.has(key)){ state.selected.delete(key); } else { state.selected.add(key); }
        document.querySelectorAll('.experimental-noid-item').forEach(function(item){
            if(String(item.dataset.itemKey || '') === key){
                item.classList.toggle('is-selected', state.selected.has(key));
            }
        });
        updateBulkControls();
    }

    function bulkPayload(action){
        return {
            job_id: state.jobId,
            action: action,
            item_keys: Array.from(state.selected)
        };
    }

    function runBulk(action){
        var payload = bulkPayload(action);
        var actionButton = byId(action === 'confirm' ? 'experimental-noid-bulk-confirm-btn' : 'experimental-noid-bulk-skip-btn');
        var originalLabel = actionButton ? actionButton.textContent : '';
        if(actionButton){ actionButton.disabled = true; actionButton.textContent = 'Проверяю...'; }
        requestJson('/api/experimental-noid/bulk-preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(function(preview){
            if(!Number(preview.count || 0)){ throw new Error('В выбранных строках нет доступных кандидатов.'); }
            var verb = action === 'confirm' ? 'Подтвердить первые кандидаты' : 'Пропустить товары';
            if(!window.confirm(verb + ': ' + Number(preview.count || 0) + '?')){
                if(actionButton){ actionButton.textContent = originalLabel; }
                updateBulkControls();
                return null;
            }
            if(actionButton){ actionButton.textContent = action === 'confirm' ? 'Сохраняю одним пакетом...' : 'Пропускаю...'; }
            return requestJson('/api/experimental-noid/bulk-decision', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
        }).then(function(result){
            if(!result){ return; }
            (result.item_keys || []).forEach(function(key){
                state.selected.delete(String(key));
                var item = document.querySelector('.experimental-noid-item[data-item-key="' + CSS.escape(String(key)) + '"]');
                if(item){ item.remove(); }
            });
            updateBulkControls();
            if(actionButton){ actionButton.textContent = originalLabel; }
            if(typeof reloadMainTable === 'function'){ reloadMainTable(); }
            if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
            return loadStatus({skipItemRefresh: true});
        }).catch(function(error){
            if(actionButton){ actionButton.textContent = originalLabel; }
            updateBulkControls();
            window.alert(error.message);
        });
    }

    function renderInsights(history, quality){
        var panel = byId('experimental-noid-insights');
        if(!panel){ return; }
        var decisions = (history && history.decisions) || [];
        var suppliers = (quality && quality.suppliers) || [];
        var html = '<div class="experimental-noid-insights-grid"><div><h4>Последние решения</h4>';
        if(!decisions.length){ html += '<div class="experimental-noid-empty">История пока пуста.</div>'; }
        decisions.slice(0, 30).forEach(function(item){
            var label = item.action === 'confirm' ? 'Подтверждён ID ' + item.candidate_id : (item.action === 'skip' ? 'Пропущен' : 'Кандидат отклонён');
            html += '<div class="experimental-noid-history-row"><span>' + escapeHtml(item.supplier || '') + '</span><span>' + escapeHtml(item.product_name || item.item_key || '') + '<br><small>' + escapeHtml(label) + '</small></span>';
            html += item.undone_at ? '<span>Отменено</span>' : '<button class="btn btn-outline" data-exp-undo="' + Number(item.decision_id) + '">Отменить</button>';
            html += '</div>';
        });
        html += '</div><div><h4>Качество по поставщикам</h4>';
        suppliers.forEach(function(item){
            var precision = item.precision === null || item.precision === undefined ? 'нет выборки' : Math.round(Number(item.precision) * 100) + '%';
            html += '<div class="experimental-noid-quality-row"><span>' + escapeHtml(item.supplier) + ' · товаров ' + Number(item.total || 0) + '</span><strong>точность ' + escapeHtml(precision) + '</strong></div>';
        });
        html += '</div></div>';
        panel.innerHTML = html;
        panel.hidden = false;
    }

    function loadInsights(){
        return Promise.all([
            requestJson('/api/experimental-noid/history?job_id=' + encodeURIComponent(state.jobId) + '&limit=100'),
            requestJson('/api/experimental-noid/quality?job_id=' + encodeURIComponent(state.jobId))
        ]).then(function(results){ renderInsights(results[0], results[1]); });
    }

    function undoDecision(decisionId){
        requestJson('/api/experimental-noid/undo', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({decision_ids: [decisionId]})
        }).then(function(result){
            if(!Number(result.restored || 0)){ throw new Error((result.failed && result.failed[0] && result.failed[0].error) || 'Не удалось отменить решение.'); }
            if(typeof reloadMainTable === 'function'){ reloadMainTable(); }
            return Promise.all([loadStatus(), loadItems(), loadInsights()]);
        }).catch(function(error){ window.alert(error.message); });
    }

    function applyDecisionLocally(button, action){
        if(action === 'reject_candidate'){
            var candidate = button.closest('.experimental-noid-candidate');
            if(!candidate){ return; }
            candidate.classList.add('rejected');
            candidate.querySelectorAll('[data-exp-action]').forEach(function(control){ control.remove(); });
            var actions = candidate.querySelector('.experimental-noid-candidate-actions');
            if(actions && !actions.querySelector('.experimental-noid-tag')){
                var rejected = document.createElement('span');
                rejected.className = 'experimental-noid-tag';
                rejected.textContent = 'Отклонён';
                actions.appendChild(rejected);
            }
            return;
        }

        var item = button.closest('.experimental-noid-item');
        if(!item){ return; }
        state.selected.delete(String(item.dataset.itemKey || ''));
        updateBulkControls();
        item.querySelectorAll('[data-exp-action]').forEach(function(control){ control.disabled = true; });
        var note = document.createElement('div');
        note.className = 'experimental-noid-decision-note ' + (action === 'confirm' ? 'confirmed' : 'skipped');
        note.textContent = action === 'confirm' ? 'ID сохранён' : 'Товар пропущен';
        item.appendChild(note);
        item.classList.add('decision-complete');
        window.setTimeout(function(){
            item.style.maxHeight = item.getBoundingClientRect().height + 'px';
            window.requestAnimationFrame(function(){ item.classList.add('decision-removing'); });
            window.setTimeout(function(){
                item.remove();
                state.totalItems = Math.max(0, state.totalItems - 1);
                updateLocalPageLabel();
                var list = byId('experimental-noid-list');
                if(list && !list.querySelector('.experimental-noid-item')){
                    list.innerHTML = '<div class="experimental-noid-empty">На этой странице всё обработано. Нажми обновить или перейди дальше.</div>';
                }
            }, 260);
        }, 420);
    }

    function makeDecision(button){
        if(!button || button.disabled){ return; }
        var action = String(button.dataset.expAction || '');
        var itemKey = String(button.dataset.itemKey || '');
        var candidateId = String(button.dataset.candidateId || '');
        if(!action || !itemKey){ return; }
        button.disabled = true;
        requestJson('/api/experimental-noid/decision', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_id: state.jobId, item_key: itemKey, action: action, candidate_id: candidateId})
        }).then(function(){
            if(action === 'confirm'){
                if(typeof reloadMainTable === 'function'){ reloadMainTable(); }
                else if(window.tblMain && tblMain.ajax){ tblMain.ajax.reload(null, false); }
                if(typeof refreshActionBadges === 'function'){ refreshActionBadges(); }
            }
            applyDecisionLocally(button, action);
            return loadStatus({skipItemRefresh: true});
        }).catch(function(error){
            button.disabled = false;
            window.alert(error.message);
        });
    }

    function openReport(){
        var modal = byId('experimental-noid-modal');
        if(!modal){ return; }
        modal.classList.add('active');
        modal.setAttribute('aria-hidden', 'false');
        loadStatus().then(loadItems);
    }

    function closeReport(){
        var modal = byId('experimental-noid-modal');
        if(!modal){ return; }
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
    }

    function init(){
        var start = byId('experimental-noid-start-btn');
        var open = byId('experimental-noid-open-btn');
        var close = byId('experimental-noid-close-btn');
        var refresh = byId('experimental-noid-refresh-btn');
        var modal = byId('experimental-noid-modal');
        var list = byId('experimental-noid-list');
        if(!start){ return; }
        start.addEventListener('click', startJob);
        if(open){ open.addEventListener('click', openReport); }
        if(close){ close.addEventListener('click', closeReport); }
        if(refresh){ refresh.addEventListener('click', function(){ loadStatus().then(loadItems); }); }
        if(modal){ modal.addEventListener('click', function(event){ if(event.target === modal){ closeReport(); } }); }
        if(list){
            list.addEventListener('click', function(event){
                var button = event.target.closest('[data-exp-action]');
                if(button){ makeDecision(button); }
            });
            list.addEventListener('click', function(event){
                var title = event.target.closest('[data-exp-select-toggle]');
                if(title){ toggleItemSelection(title.dataset.expSelectToggle); }
            });
            list.addEventListener('keydown', function(event){
                var title = event.target.closest('[data-exp-select-toggle]');
                if(title && (event.key === 'Enter' || event.key === ' ')){
                    event.preventDefault();
                    toggleItemSelection(title.dataset.expSelectToggle);
                }
            });
        }
        var selectPage = byId('experimental-noid-select-page');
        if(selectPage){ selectPage.addEventListener('change', function(){
            document.querySelectorAll('.experimental-noid-item[data-selectable="true"]').forEach(function(item){
                var key = String(item.dataset.itemKey || '');
                if(selectPage.checked){ state.selected.add(key); } else { state.selected.delete(key); }
                item.classList.toggle('is-selected', selectPage.checked);
            });
            updateBulkControls();
        }); }
        var bulkConfirm = byId('experimental-noid-bulk-confirm-btn');
        var bulkSkip = byId('experimental-noid-bulk-skip-btn');
        var history = byId('experimental-noid-history-btn');
        if(bulkConfirm){ bulkConfirm.addEventListener('click', function(){ runBulk('confirm'); }); }
        if(bulkSkip){ bulkSkip.addEventListener('click', function(){ runBulk('skip'); }); }
        if(history){ history.addEventListener('click', function(){
            var panel = byId('experimental-noid-insights');
            if(panel && !panel.hidden){
                panel.hidden = true;
                history.textContent = 'История и качество';
                return;
            }
            history.textContent = 'Скрыть историю';
            loadInsights().catch(function(error){
                history.textContent = 'История и качество';
                window.alert(error.message);
            });
        }); }
        var insights = byId('experimental-noid-insights');
        if(insights){ insights.addEventListener('click', function(event){
            var button = event.target.closest('[data-exp-undo]');
            if(button){ undoDecision(Number(button.dataset.expUndo)); }
        }); }
        ['experimental-noid-supplier-filter','experimental-noid-category-filter','experimental-noid-tier-filter','experimental-noid-state-filter'].forEach(function(id){
            var field = byId(id);
            if(field){ field.addEventListener('change', function(){ state.page = 1; loadItems(); }); }
        });
        var search = byId('experimental-noid-search');
        if(search){ search.addEventListener('input', function(){ clearTimeout(state.searchTimer); state.searchTimer = setTimeout(function(){ state.page = 1; loadItems(); }, 280); }); }
        var prev = byId('experimental-noid-prev-btn');
        var next = byId('experimental-noid-next-btn');
        if(prev){ prev.addEventListener('click', function(){ if(state.page > 1){ state.page -= 1; loadItems(); } }); }
        if(next){ next.addEventListener('click', function(){ if(state.page < state.pages){ state.page += 1; loadItems(); } }); }
        document.addEventListener('keydown', function(event){ if(event.key === 'Escape' && modal && modal.classList.contains('active')){ closeReport(); } });
        loadStatus();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
