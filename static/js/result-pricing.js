function getSelectedValues(selectId){
    var sel = document.getElementById(selectId);
    return Array.from(new Set(Array.from(sel.options).filter(function(o){ return o.selected; }).map(function(o){ return o.value; })));
}

var activeMarkupCategoryTab = 'onliner';
var lastMarkupCategoryTabKey = null;
var revealMarkupCategorySelectionOnNextRender = false;
var normalizedMarkupCategoryNames = new Set();
var MARKUP_CATEGORY_TABS = [
    {id: 'onliner', label: 'Структура Onliner'},
    {id: 'sorting', label: 'Требует сортировки'},
    {id: 'without_id', label: 'Товары без ID'}
];

function markupCategoryOptionKey(option){
    return String((option && option.value) || '') + '\u0000' + String((option && option.dataset && option.dataset.idMode) || 'all');
}

function looksLikeRawMarkupCategoryName(name){
    var text = String(name || '').trim();
    if(!text){ return false; }
    if(['SSD', 'HDD', 'ИБП', 'БП', 'NAS'].indexOf(text) >= 0){ return false; }
    if(text.length < 2){ return false; }
    if(text !== text.toUpperCase()){ return false; }
    return /^[A-ZА-ЯЁ0-9\s\-+/_\.]+$/.test(text) && text.split(/\s+/).filter(Boolean).length <= 2;
}

function shouldShowMarkupCategoryName(name){
    var text = String(name || '').trim();
    if(!text){ return false; }
    if(text.indexOf('Требует сортировки') === 0){ return false; }
    if(looksLikeRawMarkupCategoryName(text)){ return false; }
    if(normalizedMarkupCategoryNames && normalizedMarkupCategoryNames.size){
        return normalizedMarkupCategoryNames.has(text);
    }
    return true;
}

function getSelectedCategoryFilters(selectId){
    var sel = document.getElementById(selectId);
    if(!sel){ return []; }
    return Array.from(sel.options).filter(function(o){ return o.selected; }).map(function(o){
        return {category: o.value, id_mode: o.dataset.idMode || 'all'};
    });
}

function applyCategoryFilterSelection(selectId, filters){
    var sel = document.getElementById(selectId);
    if(!sel){ return; }
    var selected = new Set((filters || []).map(function(item){
        return String((item && item.category) || '') + '\u0000' + String((item && item.id_mode) || 'all');
    }));
    Array.from(sel.options).forEach(function(o){
        o.selected = selected.has(String(o.value) + '\u0000' + String(o.dataset.idMode || 'all'));
    });
}

function applyPrimaryCategorySelection(selectId, values){
    var sel = document.getElementById(selectId);
    if(!sel){ return; }
    var selected = new Set(values || []);
    var applied = new Set();
    Array.from(sel.options).forEach(function(o){
        var shouldSelect = selected.has(o.value) && !applied.has(o.value);
        o.selected = shouldSelect;
        if(shouldSelect){ applied.add(o.value); }
    });
}

function setSelectedValues(selectId, values){
    var sel = document.getElementById(selectId);
    if(!sel){ return; }
    var selected = new Set((values || []).map(function(v){ return String(v); }));
    Array.from(sel.options).forEach(function(o){
        o.selected = selected.has(String(o.value));
    });
}

function getAllValues(selectId){
    var sel = document.getElementById(selectId);
    if(!sel){ return []; }
    return Array.from(sel.options).map(function(o){ return o.value; }).filter(function(v){ return !!v; });
}

function saveUiState(){
    var state = {
        categories: getSelectedValues('markup-categories'),
        categoryFilters: getSelectedCategoryFilters('markup-categories'),
        percent: document.getElementById('markup-percent').value || '10',
        threshold: document.getElementById('markup-threshold').value || '0',
        minProfit: document.getElementById('markup-min-profit').value || '0',
        noDiscountPercent: document.getElementById('markup-no-discount-percent').value || '0',
        previewPercent: document.getElementById('preview-percent').value || '10',
        previewThreshold: document.getElementById('preview-threshold').value || '0',
        previewMinProfit: document.getElementById('preview-min-profit').value || '0',
        previewNoDiscountPercent: document.getElementById('preview-no-discount-percent').value || '0',
        previewBaseMode: document.getElementById('preview-base-mode').value || 'wholesale'
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

function renderOnlinerStructurePreview(data){
    var summary = (data && data.summary) || {};
    var summaryEl = document.getElementById('onliner-structure-summary');
    var stats = [
        [summary.total || 0, 'Всего строк'],
        [summary.with_id || 0, 'С OnlinerID'],
        [summary.mapped || 0, 'Категория найдена'],
        [summary.changed || 0, 'Изменят категорию'],
        [summary.missing_catalog_category || 0, 'ID вне каталога'],
        [summary.categories_without_markup || 0, 'Категорий без наценки']
    ];
    summaryEl.innerHTML = stats.map(function(item){
        return '<div class="onliner-structure-stat"><strong>' + escapeHtml(String(item[0])) + '</strong><span>' + escapeHtml(item[1]) + '</span></div>';
    }).join('');

    var categories = document.getElementById('onliner-structure-categories');
    categories.innerHTML = ((data && data.categories) || []).map(function(item){
        var examples = (item.examples || []).slice(0, 3).map(function(name){ return escapeHtml(String(name || '')); }).join('<br>');
        return '<tr><td><strong>' + escapeHtml(item.name || '') + '</strong>'
            + (examples ? '<div class="onliner-structure-examples">' + examples + '</div>' : '')
            + '</td><td>' + escapeHtml(String(item.count || 0)) + '</td>'
            + '<td>' + escapeHtml(String(item.changed || 0)) + '</td>'
            + '<td><span class="onliner-structure-badge ' + (item.has_markup ? 'ok' : 'warn') + '">'
            + (item.has_markup ? 'есть' : 'нужно задать') + '</span></td></tr>';
    }).join('') || '<tr><td colspan="4">Категории не найдены.</td></tr>';

    var transitions = document.getElementById('onliner-structure-transitions');
    transitions.innerHTML = ((data && data.transitions) || []).map(function(item){
        var examples = (item.examples || []).slice(0, 2).map(function(name){ return escapeHtml(String(name || '')); }).join('<br>');
        return '<tr><td>' + escapeHtml(item.from || '') + '</td><td><strong>' + escapeHtml(item.to || '') + '</strong>'
            + (examples ? '<div class="onliner-structure-examples">' + examples + '</div>' : '')
            + '</td><td>' + escapeHtml(String(item.count || 0)) + '</td></tr>';
    }).join('') || '<tr><td colspan="3">Изменений категорий нет.</td></tr>';
}

function openOnlinerStructurePreview(){
    var modal = document.getElementById('onliner-structure-modal');
    document.getElementById('onliner-structure-summary').innerHTML = '<div class="onliner-structure-note">Собираю отчет…</div>';
    document.getElementById('onliner-structure-categories').innerHTML = '';
    document.getElementById('onliner-structure-transitions').innerHTML = '';
    modal.classList.add('active');
    fetch('/api/onliner-category-preview').then(function(r){
        return r.json().then(function(data){
            if(!r.ok || !data || data.status !== 'ok'){
                throw new Error((data && data.message) || 'Не удалось собрать отчет.');
            }
            return data;
        });
    }).then(renderOnlinerStructurePreview).catch(function(err){
        document.getElementById('onliner-structure-summary').innerHTML =
            '<div class="onliner-structure-note" style="color:#b91c1c;">' + escapeHtml(String(err.message || err)) + '</div>';
    });
}

function closeOnlinerStructurePreview(){
    document.getElementById('onliner-structure-modal').classList.remove('active');
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
    var exportGoogleBtn = document.getElementById('export-google-sheet-btn');
    var exportGoogleBtnDefaultText = exportGoogleBtn ? exportGoogleBtn.textContent : 'В Google Таблицу';
    function startGoogleExportProgress(){
        if(googleExportProgressTimer){ clearInterval(googleExportProgressTimer); googleExportProgressTimer = null; }
        if(exportGoogleBtn){
            exportGoogleBtn.classList.add('is-loading');
            exportGoogleBtn.textContent = 'Подключаюсь к Google Sheets...';
        }
        var ticks = 0;
        googleExportProgressTimer = setInterval(function(){
            ticks += 1;
            if(exportGoogleBtn){
                if(ticks < 4){
                    exportGoogleBtn.textContent = 'Подключаюсь к Google Sheets' + '.'.repeat((ticks % 3) + 1);
                } else {
                    exportGoogleBtn.textContent = 'Записываю в лист' + '.'.repeat((ticks % 3) + 1);
                }
            }
        }, 420);
    }
    function finishGoogleExportProgress(isSuccess, text){
        if(googleExportProgressTimer){ clearInterval(googleExportProgressTimer); googleExportProgressTimer = null; }
        if(exportGoogleBtn){
            exportGoogleBtn.classList.remove('is-loading');
            exportGoogleBtn.textContent = text || (isSuccess ? 'Готово' : 'Ошибка выгрузки');
        }
        setTimeout(function(){
            if(exportGoogleBtn){
                exportGoogleBtn.textContent = exportGoogleBtnDefaultText || 'В Google Таблицу';
            }
        }, isSuccess ? 1600 : 2600);
    }
    if(exportGoogleBtn){
        exportGoogleBtn.addEventListener('click', function(){
            if(!confirm('Записать текущий сводный прайс в Google Таблицу по настройкам (ссылка/ID и имя листа)? Данные на этом листе будут полностью заменены.')){ return; }
            exportGoogleBtn.disabled = true;
            startGoogleExportProgress();
            fetch('/api/export-google-sheets', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})})
            .then(function(r){ return r.json(); })
            .then(function(d){
                exportGoogleBtn.disabled = false;
                if(d && d.status === 'ok'){
                    finishGoogleExportProgress(true, 'Готово: выгрузка в Google Sheets завершена.');
                    alert(d.message || 'Готово.');
                } else {
                    finishGoogleExportProgress(false, (d && d.message) || 'Ошибка выгрузки.');
                    alert((d && d.message) || 'Ошибка выгрузки.');
                }
            }).catch(function(){
                exportGoogleBtn.disabled = false;
                finishGoogleExportProgress(false, 'Ошибка сети при выгрузке в Google Таблицу.');
                alert('Ошибка сети при выгрузке в Google Таблицу.');
            });
        });
    }
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
	    document.getElementById('markup-categories').addEventListener('change', function(){ renderMarkupCategoryTabs(); applyStoredPercentForSelection(); syncPreviewModalCategorySelector(); saveUiState(); requestPreview(); });
    document.getElementById('markup-percent').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-threshold').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-min-profit').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('markup-no-discount-percent').addEventListener('input', function(){ saveUiState(); requestPreview(); });
    document.getElementById('close-full-list-btn').addEventListener('click', closeFullListModal);
    document.getElementById('full-list-modal').addEventListener('click', function(e){
        if(e.target.id === 'full-list-modal'){ closeFullListModal(); }
    });
    var openNtechChecksBtn = document.getElementById('open-ntech-checks-modal-btn');
    var closeNtechChecksBtn = document.getElementById('close-ntech-checks-modal-btn');
    var ntechChecksModal = document.getElementById('ntech-checks-modal');
    if(openNtechChecksBtn && ntechChecksModal){
        openNtechChecksBtn.addEventListener('click', function(){
            ntechChecksModal.classList.add('active');
        });
    }
    if(closeNtechChecksBtn && ntechChecksModal){
        closeNtechChecksBtn.addEventListener('click', function(){
            ntechChecksModal.classList.remove('active');
        });
    }
    if(ntechChecksModal){
        ntechChecksModal.addEventListener('click', function(e){
            if(e.target.id === 'ntech-checks-modal'){
                ntechChecksModal.classList.remove('active');
            }
        });
        document.addEventListener('keydown', function(e){
            if(e.key === 'Escape' && ntechChecksModal.classList.contains('active')){
                ntechChecksModal.classList.remove('active');
            }
        });
    }
    document.getElementById('open-preview-modal-btn').addEventListener('click', openPreviewModal);
    document.getElementById('open-onliner-structure-btn').addEventListener('click', openOnlinerStructurePreview);
    document.getElementById('sorting-reparse-btn').addEventListener('click', function(){ startSortingReparse(false); });
    document.getElementById('sorting-reparse-all-btn').addEventListener('click', function(){ startSortingReparse(true); });
    var supplierCategorySearch = document.getElementById('supplier-category-search');
    var supplierCategorySearchClear = document.getElementById('supplier-category-search-clear');
    if(supplierCategorySearch){
        supplierCategorySearch.addEventListener('input', applySupplierCategorySearch);
        supplierCategorySearch.addEventListener('keydown', function(e){
            if(e.key === 'Enter'){
                e.preventDefault();
                hideFirstVisibleSupplierCategoryMatch();
            }
        });
    }
    if(supplierCategorySearchClear){
        supplierCategorySearchClear.addEventListener('click', function(){
            if(supplierCategorySearch){ supplierCategorySearch.value = ''; }
            applySupplierCategorySearch();
            if(supplierCategorySearch){ supplierCategorySearch.focus(); }
        });
    }
    document.getElementById('close-onliner-structure-btn').addEventListener('click', closeOnlinerStructurePreview);
    document.getElementById('onliner-structure-modal').addEventListener('click', function(e){
        if(e.target.id === 'onliner-structure-modal'){ closeOnlinerStructurePreview(); }
    });
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
    document.getElementById('close-offers-btn').addEventListener('click', closeOffersModal);
    document.getElementById('offers-modal').addEventListener('click', function(e){
        if(e.target.id === 'offers-modal'){ closeOffersModal(); }
    });
    document.querySelector('#preview-full-table tbody').addEventListener('click', function(e){
        var tr = e.target.closest('tr[data-row-idx]');
        if(!tr){ return; }
        setSelectedPreviewRow(parseInt(tr.getAttribute('data-row-idx') || '-1', 10));
    });
    initMarketOffersHover();
    document.getElementById('preview-modal-categories').addEventListener('change', function(){
        renderPreviewCategoryGrid();
        applyStoredPercentForPreviewSelection();
        schedulePreviewModalItemsLoad();
    });
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
    var names = Object.keys(categoryMarkups || {})
        .filter(shouldShowMarkupCategoryName)
        .sort(compareCategoriesByUiOrder);
    tbody.innerHTML = '';
    if(!names.length){
        var trEmpty = document.createElement('tr');
        trEmpty.innerHTML = '<td colspan="6" style="color:#6b7280;">Наценки по нормализованным категориям пока не заданы.</td>';
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
    if(categoryUiOrder && categoryUiOrder.length){
        var orderIdx = categoryUiOrder.indexOf(name);
        if(orderIdx >= 0){ return orderIdx; }
        return 10000;
    }
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

var sortingReparseTimer = null;
var sortingReparseMode = 'queue';
var sortingReparseQueueCount = 0;
var sortingReparseRunning = false;

function syncSortingReparseQueueUi(){
    var note = document.getElementById('sorting-reparse-note');
    var button = document.getElementById('sorting-reparse-btn');
    if(!note || !button){ return; }
    button.disabled = sortingReparseRunning || sortingReparseQueueCount <= 0;
    if(!sortingReparseRunning && sortingReparseQueueCount <= 0){
        note.textContent = 'Очередь «Требует сортировки» пуста. Товары без OnlinerID находятся во вкладке «Товары без ID».';
    }
}

function renderSortingReparseStatus(status){
    var note = document.getElementById('sorting-reparse-note');
    var button = document.getElementById('sorting-reparse-btn');
    var allButton = document.getElementById('sorting-reparse-all-btn');
    if(!note || !button || !allButton){ return; }
    var total = Number(status.total || 0);
    var processed = Number(status.processed || 0);
    var found = Number(status.found || 0);
    var missing = Number(status.not_found || 0);
    var unavailable = Number(status.unavailable || 0);
    var written = Number(status.written_to_db || status.written || 0);
    var scannedCategories = Number(status.scanned_categories || 0);
    var totalCategories = Number(status.total_categories || 0);
    var percent = Math.max(0, Math.min(100, Number(status.percent || 0)));
    var running = !!status.is_running;
    sortingReparseRunning = running;
    var activeButton = sortingReparseMode === 'all' ? allButton : button;
    [button, allButton].forEach(function(btn){
        btn.disabled = running || (btn === button && sortingReparseQueueCount <= 0);
        btn.classList.toggle('is-running', running && btn === activeButton);
        btn.style.setProperty('--sorting-progress', (running && btn === activeButton ? percent : 0) + '%');
    });
    button.textContent = running && sortingReparseMode === 'queue'
        ? ('Допарсинг ' + percent + '% · ' + processed + '/' + total)
        : 'Допарсить очередь';
    allButton.textContent = running && sortingReparseMode === 'all'
        ? ('Проверка ' + percent + '% · ' + processed + '/' + total)
        : 'Проверить новые/спорные ID';
    note.textContent = status.is_running
        ? 'Допарсинг в фоне: ' + percent + '%. Обработано ID ' + processed + ' / ' + total + '. Найдено: ' + found + ', не найдено: ' + missing + ', API недоступен: ' + unavailable + ', записано в базу: ' + written + '. Неответившие карточки останутся в ручной очереди.'
        : (status.message || 'Очередь «Требует сортировки» можно допарсить в фоне. «Проверить новые/спорные ID» спросит Onliner только по ID без сохранённой категории или из ручной очереди.')
            + (total ? ' Обработано: ' + processed + ' / ' + total + '. Найдено: ' + found + ', не найдено: ' + missing + ', API недоступен: ' + unavailable + ', записано в базу: ' + written + '.' : '');
}

function pollSortingReparseStatus(){
    fetch('/api/sorting-reparse/status').then(function(r){ return r.json(); }).then(function(status){
        if(!status.ok){ throw new Error(status.error || 'Не удалось получить статус.'); }
        renderSortingReparseStatus(status);
        if(status.is_running){
            sortingReparseTimer = setTimeout(pollSortingReparseStatus, 600);
        } else {
            sortingReparseTimer = null;
            loadCategories(getSelectedValues('markup-categories'));
            loadSupplierCategories();
            if(tblMain){ tblMain.ajax.reload(null, false); }
        }
    }).catch(function(err){
        document.getElementById('sorting-reparse-note').textContent = err.message;
        sortingReparseRunning = false;
        document.getElementById('sorting-reparse-btn').disabled = sortingReparseQueueCount <= 0;
        var allButton = document.getElementById('sorting-reparse-all-btn');
        if(allButton){ allButton.disabled = false; }
        sortingReparseTimer = null;
    });
}

function startSortingReparse(allIds){
    if(!allIds && sortingReparseQueueCount <= 0){
        syncSortingReparseQueueUi();
        return;
    }
    sortingReparseMode = allIds ? 'all' : 'queue';
    document.getElementById('sorting-reparse-btn').disabled = true;
    document.getElementById('sorting-reparse-all-btn').disabled = true;
    document.getElementById('sorting-reparse-note').textContent = allIds ? 'Передаю новые и спорные OnlinerID парсеру...' : 'Передаю очередь парсеру...';
    fetch(allIds ? '/api/sorting-reparse/run-all' : '/api/sorting-reparse/run', {method:'POST'}).then(function(r){ return r.json().then(function(data){ return {ok:r.ok, data:data}; }); }).then(function(result){
        if(!result.ok || !result.data.ok){ throw new Error(result.data.error || 'Не удалось запустить допарсинг.'); }
        renderSortingReparseStatus(result.data.status || {});
        if(sortingReparseTimer){ clearTimeout(sortingReparseTimer); }
        sortingReparseTimer = setTimeout(pollSortingReparseStatus, 900);
    }).catch(function(err){
        document.getElementById('sorting-reparse-note').textContent = err.message;
        sortingReparseRunning = false;
        document.getElementById('sorting-reparse-btn').disabled = sortingReparseQueueCount <= 0;
        document.getElementById('sorting-reparse-all-btn').disabled = false;
    });
}

function loadCategories(preselected){
    fetch('/api/categories').then(function(r){ return r.json(); }).then(function(d){
        var sel = document.getElementById('markup-categories');
        var previousFilters = getSelectedCategoryFilters('markup-categories');
        sel.innerHTML = '';
        var categories = d.categories || [];
        categoryUiOrder = categories.map(function(c){ return String((c && c.name) || ''); });
        normalizedMarkupCategoryNames = new Set();
        var onlinerGroup = document.createElement('optgroup');
        var pendingGroup = document.createElement('optgroup');
        var sortingGroup = document.createElement('optgroup');
        var totalWithoutId = 0;
        var totalSorting = 0;
        categories.forEach(function(c){
            var count = Number((c && c.count) || 0);
            var withoutId = Number((c && c.without_id) || 0);
            var withId = Math.max(0, count - withoutId);
            var sortingPrefix = 'Требует сортировки · родитель: ';
            var categoryName = String((c && c.name) || '');
            if(categoryName.indexOf(sortingPrefix) === 0){
                var parentCategoryName = categoryName.slice(sortingPrefix.length);
                if(withId > 0){
                    var sortingOption = document.createElement('option');
                    sortingOption.value = categoryName;
                    sortingOption.textContent = parentCategoryName + ' (' + String(withId) + ')';
                    sortingOption.dataset.count = String(withId);
                    sortingOption.dataset.withoutId = '0';
                    sortingOption.dataset.idMode = 'sorting';
                    sortingOption.title = categoryName + ': OnlinerID есть, но родная категория не найдена в локальной базе';
                    sortingGroup.appendChild(sortingOption);
                    totalSorting += withId;
                }
                if(withoutId > 0){
                    var pendingSortingOption = document.createElement('option');
                    pendingSortingOption.value = categoryName;
                    pendingSortingOption.textContent = parentCategoryName + ' (' + String(withoutId) + ')';
                    pendingSortingOption.dataset.count = String(withoutId);
                    pendingSortingOption.dataset.withoutId = String(withoutId);
                    pendingSortingOption.dataset.idMode = 'without_id';
                    pendingSortingOption.title = parentCategoryName + ': без OnlinerID ' + String(withoutId);
                    pendingGroup.appendChild(pendingSortingOption);
                    totalWithoutId += withoutId;
                }
                return;
            }
            if(!looksLikeRawMarkupCategoryName(categoryName)){
                normalizedMarkupCategoryNames.add(categoryName);
            }
            if(withId > 0){
                var onlinerOption = document.createElement('option');
                onlinerOption.value = c.name;
                onlinerOption.textContent = String(c.name || '') + ' (' + String(withId) + ')';
                onlinerOption.dataset.count = String(withId);
                onlinerOption.dataset.withoutId = '0';
                onlinerOption.dataset.idMode = 'with_id';
                onlinerOption.title = String(c.name || '') + ': товаров с OnlinerID ' + String(withId);
                onlinerGroup.appendChild(onlinerOption);
            }
            if(withoutId > 0){
                var pendingOption = document.createElement('option');
                pendingOption.value = c.name;
                pendingOption.textContent = String(c.name || '') + ' (' + String(withoutId) + ')';
                pendingOption.dataset.count = String(withoutId);
                pendingOption.dataset.withoutId = String(withoutId);
                pendingOption.dataset.idMode = 'without_id';
                pendingOption.title = String(c.name || '') + ': без OnlinerID ' + String(withoutId);
                pendingGroup.appendChild(pendingOption);
                totalWithoutId += withoutId;
            }
        });
        onlinerGroup.label = 'Структура Onliner';
        pendingGroup.label = 'Нужен подбор ID · ' + String(totalWithoutId);
        sortingGroup.label = 'Требует сортировки · ' + String(totalSorting);
        if(onlinerGroup.children.length){ sel.appendChild(onlinerGroup); }
        if(pendingGroup.children.length){ sel.appendChild(pendingGroup); }
        if(sortingGroup.children.length){ sel.appendChild(sortingGroup); }
        sortingReparseQueueCount = totalSorting;
        syncSortingReparseQueueUi();
        renderCategoryMarkupTable();
        var available = new Set(categories.map(function(c){ return c.name; }));
        var desired = (preselected && preselected.length) ? preselected : (loadUiState().categories || []);
        desired = desired.filter(function(name){ return available.has(name); });
        var desiredFilters = previousFilters.length ? previousFilters : (loadUiState().categoryFilters || []);
        if(desiredFilters.length){ applyCategoryFilterSelection('markup-categories', desiredFilters); }
        else { applyPrimaryCategorySelection('markup-categories', desired); }
        renderMarkupCategoryTabs();
        syncPreviewModalCategorySelector();
        applyStoredPercentForSelection();
        saveUiState();
        document.getElementById('markup-note').textContent = categories.length
            ? 'Выберите категории и процент. Будут пересчитаны колонки "РРЦ" и "Цена без скидки".'
            : 'Категории не найдены.';
        requestPreview();
        renderExportCategoryAnalytics();
        renderWithoutIdCategoryAnalytics();
        updateNoIdCategoryFilterOptions(mainTableRows || []);
    }).catch(function(){
        document.getElementById('markup-note').textContent = 'Не удалось загрузить категории.';
    });
}

function formatPreviewCategoryParts(category){
    var name = String((category && category.name) || '');
    var count = Number((category && category.count) || 0);
    var withoutId = Number((category && category.without_id) || 0);
    return {
        left: name + ' (' + String(count) + ')',
        right: withoutId > 0 ? ('(без ID: ' + String(withoutId) + ')') : '✓'
    };
}

function formatMarkupCategoryOptionTitle(category){
    var name = String((category && category.name) || '');
    var count = Number((category && category.count) || 0);
    var withoutId = Number((category && category.without_id) || 0);
    if(withoutId > 0){
        return name + ': всего ' + String(count) + ', без ID ' + String(withoutId);
    }
    return name + ': всего ' + String(count) + ', все товары с OnlinerID';
}

function classifyMarkupCategoryOption(option){
    var mode = String((option && option.dataset && option.dataset.idMode) || '');
    var value = String((option && option.value) || '');
    if(mode === 'without_id' || Number((option && option.dataset && option.dataset.withoutId) || 0) > 0){
        return 'without_id';
    }
    if(mode === 'sorting' || value.indexOf('Требует сортировки · родитель: ') === 0){
        return 'sorting';
    }
    return 'onliner';
}

function renderMarkupCategoryTabs(){
    var sel = document.getElementById('markup-categories');
    var root = document.getElementById('markup-category-tabs');
    if(!sel || !root){ return; }
    var previousList = root.querySelector('.markup-category-list');
    var previousTab = root.dataset.activeMarkupCategoryTab || '';
    var buckets = {onliner: [], sorting: [], without_id: []};
    Array.from(sel.options).forEach(function(option){
        var tabId = classifyMarkupCategoryOption(option);
        if(!buckets[tabId]){ buckets[tabId] = []; }
        buckets[tabId].push(option);
    });
    if(!buckets[activeMarkupCategoryTab] || !buckets[activeMarkupCategoryTab].length){
        var fallback = MARKUP_CATEGORY_TABS.find(function(tab){ return buckets[tab.id] && buckets[tab.id].length; });
        activeMarkupCategoryTab = fallback ? fallback.id : 'onliner';
    }
    var previousScrollTop = (previousList && previousTab === activeMarkupCategoryTab) ? previousList.scrollTop : 0;

    var tabbar = document.createElement('div');
    tabbar.className = 'markup-category-tabbar';
    MARKUP_CATEGORY_TABS.forEach(function(tab){
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'markup-category-tab' + (tab.id === activeMarkupCategoryTab ? ' active' : '');
        btn.textContent = tab.label + ' · ' + String((buckets[tab.id] || []).length);
        btn.addEventListener('click', function(){
            activeMarkupCategoryTab = tab.id;
            lastMarkupCategoryTabKey = null;
            renderMarkupCategoryTabs();
        });
        tabbar.appendChild(btn);
    });

    var list = document.createElement('div');
    list.className = 'markup-category-list';
    list.tabIndex = 0;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-multiselectable', 'true');
    list.addEventListener('keydown', function(e){
        handleMarkupCategoryListKeydown(e, options);
    });
    var options = buckets[activeMarkupCategoryTab] || [];
    if(!options.length){
        var empty = document.createElement('div');
        empty.className = 'markup-category-empty';
        empty.textContent = 'Категорий в этой вкладке нет.';
        list.appendChild(empty);
    } else {
        options.forEach(function(option){
            list.appendChild(createMarkupCategoryTabRow(option, options));
        });
    }

    root.innerHTML = '';
    root.appendChild(tabbar);
    root.appendChild(list);
    root.dataset.activeMarkupCategoryTab = activeMarkupCategoryTab;
    if(revealMarkupCategorySelectionOnNextRender){
        var selectedRow = list.querySelector('.markup-category-row.is-selected');
        if(selectedRow){
            selectedRow.scrollIntoView({block: 'nearest'});
        }
    } else {
        list.scrollTop = previousScrollTop;
    }
    revealMarkupCategorySelectionOnNextRender = false;
}

function createMarkupCategoryTabRow(option, visibleOptions){
    var row = document.createElement('div');
    row.className = 'markup-category-row' + (option.selected ? ' is-selected' : '');
    row.dataset.key = markupCategoryOptionKey(option);
    row.title = option.title || option.textContent || option.value;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', option.selected ? 'true' : 'false');

    var name = document.createElement('span');
    name.className = 'markup-category-row-name';
    name.textContent = markupCategoryRowLabel(option);

    var count = document.createElement('span');
    count.className = 'markup-category-row-count';
    count.textContent = '';

    row.appendChild(name);
    row.appendChild(count);
    row.addEventListener('click', function(e){
        toggleMarkupCategoryOption(option, visibleOptions, e);
        refocusMarkupCategoryList();
    });
    return row;
}

function markupCategoryRowLabel(option){
    var name = markupCategoryRowName(option);
    var count = markupCategoryRowCount(option);
    return count ? (name + ' ' + count) : name;
}

function markupCategoryRowName(option){
    var text = String((option && option.textContent) || '').trim();
    return text.replace(/\s+\(\d+\)\s*$/, '') || String((option && option.value) || '');
}

function markupCategoryRowCount(option){
    var count = String((option && option.dataset && option.dataset.count) || '').trim();
    if(count){ return '(' + count + ')'; }
    var text = String((option && option.textContent) || '');
    var match = text.match(/\((\d+)\)\s*$/);
    return match ? ('(' + match[1] + ')') : '';
}

function getMarkupCategoryNavigationIndex(options){
    if(!options.length){ return -1; }
    var anchorKey = lastMarkupCategoryTabKey || '';
    if(anchorKey){
        var anchorIdx = options.findIndex(function(option){
            return markupCategoryOptionKey(option) === anchorKey;
        });
        if(anchorIdx >= 0){ return anchorIdx; }
    }
    var selectedIdx = options.findIndex(function(option){ return !!option.selected; });
    return selectedIdx >= 0 ? selectedIdx : 0;
}

function refocusMarkupCategoryList(){
    setTimeout(function(){
        var list = document.querySelector('#markup-category-tabs .markup-category-list');
        if(list){ list.focus({preventScroll: true}); }
    }, 0);
}

function handleMarkupCategoryListKeydown(e, options){
    if(!options || !options.length){ return; }
    var currentIdx = getMarkupCategoryNavigationIndex(options);
    var nextIdx = currentIdx;
    if(e.key === 'ArrowDown'){
        nextIdx = Math.min(options.length - 1, currentIdx + 1);
    } else if(e.key === 'ArrowUp'){
        nextIdx = Math.max(0, currentIdx - 1);
    } else if(e.key === 'Home'){
        nextIdx = 0;
    } else if(e.key === 'End'){
        nextIdx = options.length - 1;
    } else {
        return;
    }
    e.preventDefault();
    revealMarkupCategorySelectionOnNextRender = true;
    toggleMarkupCategoryOption(options[nextIdx], options, {
        shiftKey: !!e.shiftKey,
        ctrlKey: false,
        metaKey: false
    });
    refocusMarkupCategoryList();
}

function clearMarkupCategorySelection(sel){
    Array.from(sel.options || []).forEach(function(opt){
        opt.selected = false;
    });
}

function toggleMarkupCategoryOption(option, visibleOptions, event){
    var sel = document.getElementById('markup-categories');
    if(!sel || !option){ return; }
    var useRange = !!(event && event.shiftKey);
    var useToggle = !!(event && (event.ctrlKey || event.metaKey));
    if(useRange && lastMarkupCategoryTabKey){
        var keys = visibleOptions.map(markupCategoryOptionKey);
        var from = keys.indexOf(lastMarkupCategoryTabKey);
        var to = keys.indexOf(markupCategoryOptionKey(option));
        clearMarkupCategorySelection(sel);
        if(from >= 0 && to >= 0){
            var start = Math.min(from, to);
            var end = Math.max(from, to);
            for(var i = start; i <= end; i++){
                visibleOptions[i].selected = true;
            }
        } else {
            option.selected = true;
        }
    } else if(useToggle){
        option.selected = !option.selected;
    } else {
        clearMarkupCategorySelection(sel);
        option.selected = true;
    }
    lastMarkupCategoryTabKey = markupCategoryOptionKey(option);
    sel.dispatchEvent(new Event('change', {bubbles: true}));
}

function syncPreviewModalCategorySelector(){
    var src = document.getElementById('markup-categories');
    var dst = document.getElementById('preview-modal-categories');
    if(!src || !dst){ return; }
    dst.innerHTML = '';
    Array.from(src.options).forEach(function(o){
        var category = {
            name: o.value,
            count: Number(o.dataset.count || 0),
            without_id: Number(o.dataset.withoutId || 0)
        };
        var parts = formatPreviewCategoryParts(category);
        var opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = parts.left + ' ' + parts.right;
        opt.title = formatMarkupCategoryOptionTitle(category);
        opt.dataset.count = String(category.count);
        opt.dataset.withoutId = String(category.without_id);
        opt.dataset.idMode = o.dataset.idMode || 'all';
        if(category.without_id <= 0){
            opt.className = 'category-option-complete';
        }
        opt.selected = !!o.selected;
        dst.appendChild(opt);
    });
    renderPreviewCategoryGrid();
}

function renderPreviewCategoryGrid(){
    var sel = document.getElementById('preview-modal-categories');
    var grid = document.getElementById('preview-modal-category-grid');
    if(!sel || !grid){ return; }
    grid.innerHTML = '';
    Array.from(sel.options).forEach(function(opt, idx){
        var category = {
            name: opt.value,
            count: Number(opt.dataset.count || 0),
            without_id: Number(opt.dataset.withoutId || 0)
        };
        var parts = formatPreviewCategoryParts(category);
        var row = document.createElement('div');
        row.className = 'preview-category-grid-row'
            + (opt.selected ? ' is-selected' : '')
            + (category.without_id <= 0 ? ' category-option-complete' : '');
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', opt.selected ? 'true' : 'false');
        row.dataset.index = String(idx);
        row.title = opt.title || '';
        row.innerHTML =
            '<span class="preview-category-grid-name">' + escapeHtml(parts.left) + '</span>' +
            '<span class="preview-category-grid-meta">' + escapeHtml(parts.right) + '</span>';
        row.addEventListener('click', function(ev){
            selectPreviewCategoryGridRow(idx, ev);
        });
        grid.appendChild(row);
    });
}

function selectPreviewCategoryGridRow(index, ev){
    var sel = document.getElementById('preview-modal-categories');
    var grid = document.getElementById('preview-modal-category-grid');
    if(!sel || !grid){ return; }
    var opts = Array.from(sel.options);
    var idx = Number(index);
    if(idx < 0 || idx >= opts.length){ return; }
    var anchor = Number(grid.dataset.anchorIndex || -1);
    if(ev && ev.shiftKey && anchor >= 0 && anchor < opts.length){
        var from = Math.min(anchor, idx);
        var to = Math.max(anchor, idx);
        opts.forEach(function(option, optionIdx){
            option.selected = optionIdx >= from && optionIdx <= to;
        });
    } else if(ev && (ev.ctrlKey || ev.metaKey)){
        opts[idx].selected = !opts[idx].selected;
        grid.dataset.anchorIndex = String(idx);
    } else {
        opts.forEach(function(option, optionIdx){
            option.selected = optionIdx === idx;
        });
        grid.dataset.anchorIndex = String(idx);
    }
    sel.dispatchEvent(new Event('change', {bubbles:true}));
}

function requestPreview(){
    if(previewTimer){ clearTimeout(previewTimer); }
    previewTimer = setTimeout(function(){
        loadPreviewItems();
        if(document.getElementById('preview-modal').classList.contains('active')){
            schedulePreviewModalItemsLoad();
        }
    }, 220);
}

function renderPreviewTransferItems(items){
    previewTransferItems = Array.isArray(items) ? items : [];
    var hiddenSelect = document.getElementById('preview-items');
    var list = document.getElementById('preview-items-dnd');
    if(hiddenSelect){ hiddenSelect.innerHTML = ''; }
    if(!list){ return; }
    list.innerHTML = '';
    var optionFrag = document.createDocumentFragment();
    var rowFrag = document.createDocumentFragment();
    previewTransferItems.forEach(function(it){
        var label = '[' + (it.category || '') + '] ' + (it.name || '') + ' (' + (it.supplier || '') + ')';
        if(hiddenSelect){
            optionFrag.appendChild(new Option(label, it.key || ''));
        }
        var row = document.createElement('div');
        row.className = 'transfer-item-row';
        row.dataset.key = it.key || '';
        row.title = label;
        row.textContent = label;
        rowFrag.appendChild(row);
    });
    if(hiddenSelect){ hiddenSelect.appendChild(optionFrag); }
    list.appendChild(rowFrag);
}

function loadPreviewItems(){
    var categories = getSelectedValues('markup-categories');
    var categoryFilters = getSelectedCategoryFilters('markup-categories');
    var sel = document.getElementById('preview-items');
    var list = document.getElementById('preview-items-dnd');
    var note = document.getElementById('preview-items-note');
    if(sel){ sel.innerHTML = ''; }
    if(list){ list.innerHTML = ''; }
    if(!categories.length){
        note.textContent = 'Выберите категории выше, чтобы увидеть товары этих категорий.';
        return;
    }
    note.textContent = 'Загружаю товары выбранных категорий...';
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, category_filters: categoryFilters, limit: 1500})
    }).then(function(r){ return r.json(); }).then(function(d){
        var items = d.items || [];
        renderPreviewTransferItems(items);
        var total = parseInt(d.total_matches || items.length, 10) || items.length;
        var prefix = d.truncated ? ('Показано ' + items.length + ' из ' + total + '. ') : ('Найдено товаров: ' + items.length + '. ');
        note.textContent = prefix + 'Это только просмотр текущей раскладки по категориям.';
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
                schedulePreviewModalItemsLoad();
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
    loadSupplierCategories();
}

function loadSupplierCategories(){
    saveUiState();
    fetch('/api/supplier-categories')
	    .then(function(r){ return r.json(); })
	    .then(function(d){
	        var list = document.getElementById('supplier-categories');
	        list.innerHTML = '';
	        buildSupplierCategoryGroups(d.categories || []).forEach(function(groupEl){
	            list.appendChild(groupEl);
	        });
	        updateAllSupplierCategoryGroupStates();
	        document.getElementById('visibility-note').textContent = 'Галочка включена — категория показана у всех поставщиков. Снимите галочку, чтобы скрыть везде.';
	        applySupplierCategorySearch();
	    }).catch(function(){
	        document.getElementById('visibility-note').textContent = 'Не удалось загрузить общие категории.';
	    });
		}

	var SUPPLIER_CATEGORY_GROUPS = [
	    {
	        title: 'ПК комплектующие',
	        categories: [
	            'Процессор', 'Кулер', 'Кулеры', 'Охлаждение', 'Материнская плата', 'Оперативная память',
	            'SSD', 'Жесткий диск', 'Видеокарта', 'Блок питания', 'Корпус', 'Монитор', 'Кронштейны',
	            'Термопасты и термопрокладки', 'Моддинг ПК', 'Моддинг, аксессуары для системных блоков'
	        ]
	    },
	    {
	        title: 'Компьютеры и ноутбуки',
	        categories: [
	            'Компьютеры', 'Системные блоки', 'Системный блок', 'Моноблоки', 'Ноутбук',
	            'Мини-ПК и одноплатные компьютеры'
	        ]
	    },
	    {
	        title: 'Печать и сканирование',
	        categories: [
	            'Принтеры', 'ПРИНТЕР', 'Принтер и МФУ', 'МФУ', 'Картриджи', 'КАРТРИДЖ',
	            'Бумага и материалы для печати', 'Фотобумага', 'Сканеры', 'Сканеры штрих-кодов',
	            'Ламинаторы', 'Расходные материалы для ламинаторов и брошюровщиков'
	        ]
	    },
	    {
	        title: 'Периферия, звук и USB',
	        categories: [
	            'Клавиатура', 'Мышь', 'Наушники', 'Акустика', 'Портативные колонки', 'Саундбары',
	            'Комплекты периферии', 'Веб-камеры', 'Коврики для мыши', 'Микрофоны', 'Спикерфоны',
	            'Аксессуары для наушников', 'AV-ресиверы и усилители', 'USB-хабы', 'Периферия',
	            'Звуковые карты'
	        ]
	    },
	    {
	        title: 'Накопители и карты памяти',
	        categories: [
	            'Накопители USB', 'Внешние накопители', 'Карты памяти', 'Боксы для накопителей',
	            'Картридеры', 'Оптические приводы', 'Оптические диски', 'Сетевые накопители (NAS)'
	        ]
	    },
	    {
	        title: 'Сеть, связь и кабели',
	        categories: [
	            'Кабели и переходники', 'Сеть', 'Wi-Fi роутеры', 'Коммутаторы', 'Точки доступа Wi-Fi',
	            'Беспроводные адаптеры', 'Сетевые адаптеры', 'DSL-модемы', 'Сети по электропроводке (Powerline)',
	            'Проводные телефоны', 'Радиотелефоны DECT', 'Антенны беспроводной связи', 'FM-модуляторы'
	        ]
	    },
	    {
	        title: 'Питание и электрика',
	        categories: [
	            'ИБП', 'Стабилизаторы и сетевые фильтры', 'Аккумуляторы для ИБП',
	            'Батарейки, аккумуляторы, зарядные', 'Внешние аккумуляторы', 'Зарядные устройства',
	            'Пуско-зарядные устройства', 'Розетки, выключатели', 'Электрические щиты', 'Кабельный крепеж'
	        ]
	    },
	    {
	        title: 'Видео, наблюдение и экраны',
	        categories: [
	            'IP-камеры', 'Камеры CCTV', 'Видеодомофоны', 'Видеорегистраторы',
	            'Автомобильные видеорегистраторы', 'Карты видеозахвата', 'Информационные панели',
	            'Проекторы', 'Проекционные экраны', 'Телевизоры'
	        ]
	    },
	    {
	        title: 'Гаджеты и мобильные аксессуары',
	        categories: [
	            'Сумки и чехлы для ноутбуков', 'Смартфоны', 'Планшеты', 'Умные часы',
	            'Умные часы и браслеты', 'Игровые приставки', 'Игровые контроллеры и аксессуары',
	            'Подставки для ноутбуков, телефонов, планшетов', 'Рюкзаки', 'Автомобильные держатели',
	            'Аксессуары для салона автомобиля'
	        ]
	    },
	    {
	        title: 'Офис, дом и инструменты',
	        categories: [
	            'Чистящие средства', 'Аксессуары', 'Аксессуары для оргтехники', 'Графические планшеты',
	            'Шредеры', 'Офисные кресла', 'Детские парты, столы, стулья', 'Обогреватели',
	            'Медиаплееры и ТВ-приставки', 'Плееры', 'Приемники цифрового ТВ', 'Пульты ДУ',
	            'Радионяни и видеоняни', 'Радиоприемники', 'Мультиметры', 'Наборы инструментов',
	            'Строительный, слесарный, монтажный инструмент',
	            'Воздуходувки',
	            'Биты и насадки', 'Сверла и буры', 'Штативы и аксессуары для измерительных приборов',
	            'Шлифовальные диски, насадки, листы',
	            'Расходные материалы и аксессуары для 3D-печати'
	        ]
	    }
	];
	var SUPPLIER_CATEGORY_FALLBACK_GROUP_TITLE = 'Прочие категории';
	var SUPPLIER_CATEGORY_GROUP_LOOKUP = buildSupplierCategoryGroupLookup();

	function buildSupplierCategoryGroups(categories){
	    var grouped = {};
	    var orderedTitles = SUPPLIER_CATEGORY_GROUPS.map(function(group){ return group.title; });
	    orderedTitles.push(SUPPLIER_CATEGORY_FALLBACK_GROUP_TITLE);
	    orderedTitles.forEach(function(title){ grouped[title] = []; });

	    (categories || []).forEach(function(category){
	        var title = getSupplierCategorySemanticGroupTitle(category && category.name);
	        grouped[title].push(category);
	    });

	    var result = [];
	    orderedTitles.forEach(function(title){
	        if(grouped[title] && grouped[title].length){
	            result.push(createSupplierCategoryGroup(grouped[title], result.length, title));
	        }
	    });
	    return result;
	}

	function buildSupplierCategoryGroupLookup(){
	    var lookup = {};
	    SUPPLIER_CATEGORY_GROUPS.forEach(function(group){
	        group.categories.forEach(function(category){
	            lookup[normalizeSupplierCategoryGroupKey(category)] = group.title;
	        });
	    });
	    return lookup;
	}

	function normalizeSupplierCategoryGroupKey(category){
	    return String(category || '').trim().toLocaleLowerCase('ru');
	}

	function normalizeSupplierCategorySearchText(value){
	    return String(value || '')
	        .toLocaleLowerCase('ru')
	        .replace(/ё/g, 'е')
	        .replace(/\s+/g, ' ')
	        .trim();
	}

	function getSupplierCategorySemanticGroupTitle(categoryName){
	    var key = normalizeSupplierCategoryGroupKey(categoryName);
	    if(SUPPLIER_CATEGORY_GROUP_LOOKUP[key]){
	        return SUPPLIER_CATEGORY_GROUP_LOOKUP[key];
	    }
	    return SUPPLIER_CATEGORY_FALLBACK_GROUP_TITLE;
	}

	function createSupplierCategoryGroup(categories, index, groupTitle){
	    var group = document.createElement('div');
	    group.className = 'supplier-category-group';
	    group.dataset.groupIndex = String(index);
	    group.dataset.groupTitle = String(groupTitle || '');

	    var header = document.createElement('div');
	    header.className = 'supplier-category-group-header';

	    var groupCheckbox = document.createElement('input');
	    groupCheckbox.type = 'checkbox';
	    groupCheckbox.className = 'supplier-category-group-checkbox';
	    groupCheckbox.setAttribute('aria-label', 'Показать или скрыть весь подраздел');
	    groupCheckbox.addEventListener('click', function(e){ e.stopPropagation(); });
	    groupCheckbox.addEventListener('change', function(){
	        setSupplierCategoryGroupVisibility(group, !groupCheckbox.checked, groupCheckbox);
	    });

	    var title = document.createElement('span');
	    title.className = 'supplier-category-group-title';
	    title.textContent = getSupplierCategoryGroupTitle(categories, groupTitle);
	    title.title = title.textContent;

	    var state = document.createElement('span');
	    state.className = 'supplier-category-group-state';

	    var caret = document.createElement('span');
	    caret.className = 'supplier-category-group-caret';
	    caret.textContent = '▾';
	    caret.setAttribute('aria-hidden', 'true');

	    header.appendChild(groupCheckbox);
	    header.appendChild(title);
	    header.appendChild(state);
	    header.appendChild(caret);
	    header.addEventListener('click', function(){
	        group.classList.toggle('is-collapsed');
	    });

	    var body = document.createElement('div');
	    body.className = 'supplier-category-group-body';
	    categories.forEach(function(c){
	        body.appendChild(createSupplierCategoryRow(c));
	    });

	    group.appendChild(header);
	    group.appendChild(body);
	    return group;
	}

	function getSupplierCategoryGroupTitle(categories, groupTitle){
	    return String(groupTitle || 'Категории') + ' · ' + String((categories || []).length);
	}

	function createSupplierCategoryRow(c){
	    var row = document.createElement('label');
	    row.className = 'supplier-category-toggle' + (c.hidden ? ' is-hidden' : '');
	    row.dataset.category = c.name;
	    row.dataset.count = c.count || 0;
	    row.dataset.examples = JSON.stringify(c.examples || []);
	    row.dataset.items = JSON.stringify(c.items || []);
	    row.dataset.searchText = normalizeSupplierCategorySearchText([
	        c.name,
	        c.count,
	        c.search_text || '',
	        (c.examples || []).join(' '),
	        (c.items || []).map(function(item){ return item && item.name; }).join(' ')
	    ].join(' '));

	    var checkbox = document.createElement('input');
	    checkbox.type = 'checkbox';
	    checkbox.checked = !c.hidden;
	    checkbox.setAttribute('aria-label', (c.hidden ? 'Показать ' : 'Скрыть ') + c.name);
	    checkbox.addEventListener('change', function(){
	        setCategoryVisibility(c.name, !checkbox.checked, row, checkbox);
	    });

	    var name = document.createElement('span');
	    name.className = 'supplier-category-toggle-name';
	    name.textContent = c.name;
	    name.title = c.name;

	    var count = document.createElement('span');
	    count.className = 'supplier-category-toggle-count';
	    count.textContent = '(' + c.count + ')';

	    var info = document.createElement('span');
	    info.className = 'supplier-category-info';
	    info.textContent = '▾';
	    info.setAttribute('aria-hidden', 'true');

	    row.appendChild(checkbox);
	    row.appendChild(name);
	    row.appendChild(count);
	    row.appendChild(info);
	    row.addEventListener('mouseenter', function(){ cancelSupplierCategoryTooltipHide(); showSupplierCategoryTooltip(row); });
	    row.addEventListener('mouseleave', scheduleSupplierCategoryTooltipHide);
	    row.addEventListener('focusin', function(){ cancelSupplierCategoryTooltipHide(); showSupplierCategoryTooltip(row); });
	    row.addEventListener('focusout', scheduleSupplierCategoryTooltipHide);
	    return row;
	}

	function updateAllSupplierCategoryGroupStates(){
	    document.querySelectorAll('.supplier-category-group').forEach(updateSupplierCategoryGroupState);
	}

	function applySupplierCategorySearch(){
	    var input = document.getElementById('supplier-category-search');
	    var clearBtn = document.getElementById('supplier-category-search-clear');
	    var query = normalizeSupplierCategorySearchText(input ? input.value : '');
	    if(clearBtn){ clearBtn.classList.toggle('active', !!query); }
	    var totalMatches = 0;
	    document.querySelectorAll('.supplier-category-group').forEach(function(group){
	        var groupTitle = normalizeSupplierCategorySearchText(group.dataset.groupTitle || '');
	        var groupMatches = !query || groupTitle.indexOf(query) >= 0;
	        var visibleRows = 0;
	        group.querySelectorAll('.supplier-category-toggle').forEach(function(row){
	            var haystack = String(row.dataset.searchText || '') + ' ' + groupTitle;
	            var matched = !query || groupMatches || haystack.indexOf(query) >= 0;
	            row.classList.toggle('is-filtered-out', !matched);
	            row.classList.toggle('is-search-match', !!query && matched);
	            if(matched){
	                visibleRows += 1;
	                totalMatches += 1;
	            }
	        });
	        group.classList.toggle('is-filtered-out', visibleRows <= 0);
	        if(query && visibleRows > 0){
	            group.classList.remove('is-collapsed');
	        }
	    });
	    if(query){
	        var note = document.getElementById('visibility-note');
	        if(note){
	            note.textContent = totalMatches
	                ? ('Найдено категорий: ' + totalMatches + '. Сними галочку или нажми Enter, чтобы скрыть первый найденный пункт.')
	                : 'Категории по поиску не найдены.';
	        }
	    }
	}

	function hideFirstVisibleSupplierCategoryMatch(){
	    var row = document.querySelector('.supplier-category-toggle:not(.is-filtered-out):not(.is-hidden)');
	    if(!row){
	        document.getElementById('visibility-note').textContent = 'Нет показанной категории в результатах поиска.';
	        return;
	    }
	    var checkbox = row.querySelector('input[type="checkbox"]');
	    var category = row.dataset.category || '';
	    if(checkbox && checkbox.checked){
	        checkbox.checked = false;
	    }
	    setCategoryVisibility(category, true, row, checkbox);
	}

	function updateSupplierCategoryGroupState(group){
	    var boxes = Array.prototype.slice.call(group.querySelectorAll('.supplier-category-toggle input[type="checkbox"]'));
	    var groupCheckbox = group.querySelector('.supplier-category-group-checkbox');
	    var state = group.querySelector('.supplier-category-group-state');
	    if(!boxes.length || !groupCheckbox){ return; }
	    var checkedCount = boxes.filter(function(box){ return box.checked; }).length;
	    groupCheckbox.checked = checkedCount === boxes.length;
	    groupCheckbox.indeterminate = checkedCount > 0 && checkedCount < boxes.length;
	    if(state){ state.textContent = checkedCount + '/' + boxes.length; }
	}

		function setSupplierCategoryGroupVisibility(groupEl, hidden, groupCheckboxEl){
		    var rows = Array.prototype.slice.call(groupEl.querySelectorAll('.supplier-category-toggle'));
		    var categories = rows.map(function(row){ return row.dataset.category || ''; }).filter(Boolean);
	    if(!categories.length){
	        document.getElementById('visibility-note').textContent = 'Категории подраздела не найдены.';
	        updateSupplierCategoryGroupState(groupEl);
	        return;
	    }
	    groupEl.classList.add('is-saving');
	    rows.forEach(function(row){
	        row.classList.add('is-saving');
	        var box = row.querySelector('input[type="checkbox"]');
	        if(box){ box.disabled = true; }
	    });
	    if(groupCheckboxEl){ groupCheckboxEl.disabled = true; }
	    document.getElementById('visibility-note').textContent = hidden ? 'Скрываю подраздел...' : 'Показываю подраздел...';
		    fetch('/api/category-visibility', {
		        method: 'POST',
		        headers: {'Content-Type': 'application/json'},
		        body: JSON.stringify({categories: categories, hidden: hidden})
		    }).then(function(r){ return r.json(); }).then(function(d){
	        if(d.status === 'ok'){
	            document.getElementById('visibility-note').textContent = hidden ? 'Подраздел скрыт.' : 'Подраздел показан.';
	            rows.forEach(function(row){
	                var category = row.dataset.category || '';
	                var box = row.querySelector('input[type="checkbox"]');
	                row.classList.toggle('is-hidden', hidden);
	                if(box){
	                    box.checked = !hidden;
	                    box.setAttribute('aria-label', (hidden ? 'Показать ' : 'Скрыть ') + category);
	                }
	            });
	            updateSupplierCategoryGroupState(groupEl);
	            loadCategories(getSelectedValues('markup-categories'));
	            if(tblMain){ tblMain.ajax.reload(null, false); }
	        } else {
	            document.getElementById('visibility-note').textContent = d.message || 'Ошибка изменения видимости подраздела.';
	            updateSupplierCategoryGroupState(groupEl);
	        }
	    }).catch(function(){
	        document.getElementById('visibility-note').textContent = 'Ошибка связи с сервером.';
	        updateSupplierCategoryGroupState(groupEl);
	    }).finally(function(){
	        groupEl.classList.remove('is-saving');
	        rows.forEach(function(row){
	            row.classList.remove('is-saving');
	            var box = row.querySelector('input[type="checkbox"]');
	            if(box){ box.disabled = false; }
	        });
	        if(groupCheckboxEl){ groupCheckboxEl.disabled = false; }
	    });
	}

	var supplierCategoryTooltipHideTimer = null;

	function getSupplierCategoryTooltip(){
	    var tip = document.getElementById('supplier-category-tooltip');
	    if(!tip){
	        tip = document.createElement('div');
	        tip.id = 'supplier-category-tooltip';
	        tip.className = 'supplier-category-tooltip';
	        tip.addEventListener('mouseenter', cancelSupplierCategoryTooltipHide);
	        tip.addEventListener('mouseleave', scheduleSupplierCategoryTooltipHide);
	        tip.addEventListener('focusin', cancelSupplierCategoryTooltipHide);
	        tip.addEventListener('focusout', scheduleSupplierCategoryTooltipHide);
	        document.body.appendChild(tip);
	    }
	    return tip;
	}

	function showSupplierCategoryTooltip(row){
	    if(!row){ return; }
	    var tip = getSupplierCategoryTooltip();
	    var category = row.dataset.category || 'Категория';
	    var count = row.dataset.count || '0';
	    var examples = [];
	    var items = [];
	    try { examples = JSON.parse(row.dataset.examples || '[]') || []; } catch(e) { examples = []; }
	    try { items = JSON.parse(row.dataset.items || '[]') || []; } catch(e) { items = []; }
	    var hidden = row.classList.contains('is-hidden');
	    var html = '<div class="supplier-category-tooltip-head">'
	        + escapeHtml(category) + ' (' + escapeHtml(String(count)) + ')'
	        + '<div class="supplier-category-tooltip-sub">' + (hidden ? 'Скрыта. Товары внутри:' : 'Показана. Товары внутри:') + '</div>'
	        + '</div>';
	    if(items.length){
	        html += '<div class="supplier-category-tooltip-body">'
	            + '<table class="supplier-category-tooltip-table">'
	            + '<colgroup><col class="name-col"><col class="price-col"><col class="price-col"><col class="no-discount-col"></colgroup>'
	            + '<thead><tr><th>Товар</th><th>Опт</th><th>РРЦ</th><th>Без скидки</th></tr></thead><tbody>';
	        items.forEach(function(item){
	            html += '<tr>'
	                + '<td>' + escapeHtml(String((item && item.name) || '')) + '</td>'
	                + '<td class="num">' + escapeHtml(formatSupplierCategoryPrice(item && item.wholesale)) + '</td>'
	                + '<td class="num">' + escapeHtml(formatSupplierCategoryPrice(item && item.rrc)) + '</td>'
	                + '<td class="num">' + escapeHtml(formatSupplierCategoryPrice(item && item.no_discount)) + '</td>'
	                + '</tr>';
	        });
	        html += '</tbody></table></div>';
	    } else if(examples.length){
	        html += '<div class="supplier-category-tooltip-body">'
	            + '<table class="supplier-category-tooltip-table">'
	            + '<colgroup><col class="name-col"><col class="price-col"><col class="price-col"><col class="no-discount-col"></colgroup>'
	            + '<thead><tr><th>Товар</th><th>Опт</th><th>РРЦ</th><th>Без скидки</th></tr></thead><tbody>';
	        examples.slice(0, 8).forEach(function(name){
	            html += '<tr><td>' + escapeHtml(String(name || '')) + '</td><td class="num">—</td><td class="num">—</td><td class="num">—</td></tr>';
	        });
	        html += '</tbody></table></div>';
	    } else {
	        html += '<div class="supplier-category-tooltip-empty">Товары внутри категории не найдены.</div>';
	    }
	    tip.innerHTML = html;

	    var rect = row.getBoundingClientRect();
	    var top = Math.max(12, Math.min(rect.top - 8, window.innerHeight - 320));
	    var left = rect.right + 12;
	    tip.classList.remove('left-side');
	    tip.classList.add('active');
	    var tipRect = tip.getBoundingClientRect();
	    if(left + tipRect.width > window.innerWidth - 12){
	        left = Math.max(12, rect.left - tipRect.width - 12);
	        tip.classList.add('left-side');
	    }
	    tip.style.left = Math.round(left) + 'px';
	    tip.style.top = Math.round(top) + 'px';
	}

	function formatSupplierCategoryPrice(value){
	    var text = String(value == null ? '' : value).trim();
	    if(!text){ return '—'; }
	    var normalized = text.replace(',', '.');
	    if(/^-?\d+(\.\d+)?$/.test(normalized)){
	        return Number(normalized).toFixed(2);
	    }
	    return text;
	}

	function cancelSupplierCategoryTooltipHide(){
	    if(supplierCategoryTooltipHideTimer){
	        clearTimeout(supplierCategoryTooltipHideTimer);
	        supplierCategoryTooltipHideTimer = null;
	    }
	}

	function scheduleSupplierCategoryTooltipHide(){
	    cancelSupplierCategoryTooltipHide();
	    supplierCategoryTooltipHideTimer = setTimeout(hideSupplierCategoryTooltip, 140);
	}

	function hideSupplierCategoryTooltip(){
	    cancelSupplierCategoryTooltipHide();
	    var tip = document.getElementById('supplier-category-tooltip');
	    if(tip){ tip.classList.remove('active'); }
	}

		function setCategoryVisibility(category, hidden, rowEl, checkboxEl){
		    var categories = category ? [category] : [];
	    if(!categories.length){
	        document.getElementById('visibility-note').textContent = 'Категория не выбрана.';
	        if(checkboxEl){ checkboxEl.checked = !hidden; }
	        return;
	    }
	    if(rowEl){ rowEl.classList.add('is-saving'); }
	    if(checkboxEl){ checkboxEl.disabled = true; }
	    document.getElementById('visibility-note').textContent = hidden ? 'Скрываю категорию...' : 'Показываю категорию...';
		    fetch('/api/category-visibility', {
		        method: 'POST',
		        headers: {'Content-Type': 'application/json'},
		        body: JSON.stringify({categories: categories, hidden: hidden})
		    }).then(function(r){ return r.json(); }).then(function(d){
	        if(d.status === 'ok'){
	            document.getElementById('visibility-note').textContent = hidden ? 'Категория скрыта.' : 'Категория показана.';
	            if(rowEl){ rowEl.classList.toggle('is-hidden', hidden); }
	            if(checkboxEl){
	                checkboxEl.checked = !hidden;
	                checkboxEl.setAttribute('aria-label', (hidden ? 'Показать ' : 'Скрыть ') + category);
	            }
	            loadCategories(getSelectedValues('markup-categories'));
	            if(tblMain){ tblMain.ajax.reload(null, false); }
	        } else {
	            document.getElementById('visibility-note').textContent = d.message || 'Ошибка изменения видимости.';
	            if(checkboxEl){ checkboxEl.checked = !hidden; }
	        }
	    }).catch(function(){
	        document.getElementById('visibility-note').textContent = 'Ошибка связи с сервером.';
	        if(checkboxEl){ checkboxEl.checked = !hidden; }
	    }).finally(function(){
	        if(rowEl){ rowEl.classList.remove('is-saving'); }
	        if(checkboxEl){ checkboxEl.disabled = false; }
	        updateAllSupplierCategoryGroupStates();
	    });
	}
