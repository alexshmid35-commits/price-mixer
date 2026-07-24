function openFullListModal(){
    document.getElementById('full-list-modal').classList.add('active');
    loadFullListItems();
}

function closeFullListModal(){
    document.getElementById('full-list-modal').classList.remove('active');
}

function loadFullListItems(){
    var categories = getSelectedValues('markup-categories');
    var categoryFilters = getSelectedCategoryFilters('markup-categories');
    var note = document.getElementById('full-list-note');
    var tbody = document.querySelector('#full-list-table tbody');
    tbody.innerHTML = '';
    if(!categories.length){
        note.textContent = 'Выберите категории в блоке наценки, затем откройте полный список.';
        return;
    }
    note.textContent = 'Загрузка полного списка...';
    fetch('/api/category-preview-items', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, category_filters: categoryFilters, limit: 10000})
    }).then(function(r){ return r.json(); }).then(function(d){
        var items = d.items || [];
        items.forEach(function(it){
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + it.category + '</td>'
                + '<td>' + it.name + '</td>'
                + '<td>' + it.supplier + '</td>'
                + '<td>' + (it.price || '') + '</td>'
                + '<td>' + (it.rrc || '') + '</td>';
            tbody.appendChild(tr);
        });
        note.textContent = 'Найдено товаров: ' + items.length + '. Это окно только для проверки состава категорий.';
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
    var colgroup = table.querySelector('colgroup');
    var colWidths = ['125px', '360px', '95px', '72px', '128px', '128px', '128px', '82px', '104px', '86px', '170px'];
    var colHtml = colWidths.map(function(width){ return '<col style="width:' + width + ';">'; }).join('');
    if(!colgroup){
        colgroup = document.createElement('colgroup');
        table.insertBefore(colgroup, table.firstChild);
    }
    colgroup.innerHTML = colHtml;
    var thead = table.querySelector('thead');
    if(!thead){ return; }
    thead.innerHTML = '<tr>'
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
            while(row.cells.length > 11){
                row.deleteCell(0);
            }
        });
    }
}

function openPreviewModal(){
    var categories = getSelectedValues('markup-categories');
    if(!categories.length){
        var mainCategories = document.getElementById('markup-categories');
        if(mainCategories && mainCategories.options.length){
            mainCategories.options[0].selected = true;
            categories = getSelectedValues('markup-categories');
            saveUiState();
        }
    }
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
    schedulePreviewModalItemsLoad();
}

function closePreviewModal(){
    document.getElementById('preview-modal').classList.remove('active');
    hideMarketOffersTooltip();
    if(marketRefreshPollTimer){ clearTimeout(marketRefreshPollTimer); marketRefreshPollTimer = null; }
    if(previewModalLoadTimer){ clearTimeout(previewModalLoadTimer); previewModalLoadTimer = null; }
    previewModalQueuedOptions = null;
    previewModalInFlight = false;
    previewModalInFlightSeq = 0;
    if(previewModalFetchController && typeof previewModalFetchController.abort === 'function'){
        try { previewModalFetchController.abort(); } catch(_abortErr) {}
        previewModalFetchController = null;
    }
    previewModalRequestSeq++;
    previewModalRenderRafToken++;
    setPreviewModalLoading(false);
    var btn = document.getElementById('refresh-market-btn');
    if(btn){ btn.disabled = false; setRefreshMarketButtonIdle(btn); }
}

function refreshMarketIconSvg(){
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">'
        + '<path d="M21 12a9 9 0 0 1-15.5 6.3"></path>'
        + '<path d="M3 12A9 9 0 0 1 18.5 5.7"></path>'
        + '<path d="M18 2v4h4"></path>'
        + '<path d="M6 22v-4H2"></path>'
        + '</svg>';
}

function setRefreshMarketButtonIdle(btn){
    if(!btn){ return; }
    btn.innerHTML = refreshMarketIconSvg() + '<span>Цены Onliner</span>';
}

function setRefreshMarketButtonProgress(btn, percent){
    if(!btn){ return; }
    btn.innerHTML = refreshMarketIconSvg() + '<span>' + escapeHtml(String(percent || 0)) + '%</span>';
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

function getMarketOffersTooltip(){
    var tip = document.getElementById('market-offers-tooltip');
    if(tip){ return tip; }
    tip = document.createElement('div');
    tip.id = 'market-offers-tooltip';
    tip.className = 'market-offers-tooltip';
    document.body.appendChild(tip);
    return tip;
}

function positionMarketOffersTooltip(e){
    var tip = getMarketOffersTooltip();
    if(!tip.classList.contains('active')){ return; }
    var pad = 12;
    var x = e.clientX + 14;
    var y = e.clientY + 14;
    var rect = tip.getBoundingClientRect();
    if(x + rect.width + pad > window.innerWidth){
        x = Math.max(pad, e.clientX - rect.width - 14);
    }
    if(y + rect.height + pad > window.innerHeight){
        y = Math.max(pad, window.innerHeight - rect.height - pad);
    }
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
}

function hideMarketOffersTooltip(){
    marketOffersTooltipTarget = null;
    marketOffersTooltipToken++;
    var tip = document.getElementById('market-offers-tooltip');
    if(tip){ tip.classList.remove('active'); }
}

function trimPreviewNumber(text){
    return String(text || '').replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
}

function formatOfferTooltipPrice(value){
    var num = Number(value);
    if(!isFinite(num)){ return '—'; }
    return trimPreviewNumber(num.toFixed(2));
}

function getTooltipOffersForKind(offers, kind, targetValue){
    var rows = (Array.isArray(offers) ? offers : []).filter(function(it){
        return isFinite(Number(it && it.price));
    });
    if(!rows.length){ return []; }
    var target = Number(targetValue);
    if(!isFinite(target)){ return rows.slice(0, 8); }
    if(kind === 'min'){
        return rows.filter(function(it){ return Number(it.price) <= target * 1.02; })
            .sort(function(a, b){ return Number(a.price) - Number(b.price); })
            .slice(0, 8);
    }
    if(kind === 'avg'){
        var spread = Math.max(1, target * 0.05);
        return rows.filter(function(it){ return Math.abs(Number(it.price) - target) <= spread; })
            .sort(function(a, b){ return Math.abs(Number(a.price) - target) - Math.abs(Number(b.price) - target); })
            .slice(0, 8);
    }
    if(kind === 'max'){
        return rows.filter(function(it){ return Number(it.price) >= target * 0.98; })
            .sort(function(a, b){ return Number(b.price) - Number(a.price); })
            .slice(0, 8);
    }
    return rows.slice(0, 8);
}

function renderMarketOffersTooltip(data, kind, targetValue){
    var labels = {min: 'Onliner Мин', avg: 'Onliner Ср', max: 'Onliner Макс'};
    if(!data || data.status !== 'ok'){
        return '<div class="market-offers-tooltip-head"><span>' + escapeHtml(labels[kind] || 'Onliner') + '</span></div>'
            + '<div class="market-offers-tooltip-empty">Не удалось загрузить магазины.</div>';
    }
    var offers = Array.isArray(data.offers) ? data.offers : [];
    var picked = getTooltipOffersForKind(offers, kind, targetValue);
    if(!picked.length){
        picked = offers.filter(function(it){ return isFinite(Number(it && it.price)); }).slice(0, 8);
    }
    var html = '<div class="market-offers-tooltip-head">'
        + '<span>' + escapeHtml(labels[kind] || 'Onliner') + ': ' + escapeHtml(formatOfferTooltipPrice(targetValue)) + '</span>'
        + '<span class="market-offers-tooltip-sub">' + Number(offers.length || 0) + ' офф.</span>'
        + '</div>';
    if(!picked.length){
        return html + '<div class="market-offers-tooltip-empty">API не вернул магазины для этой цены.</div>';
    }
    html += '<div class="market-offers-tooltip-body">';
    picked.forEach(function(it){
        var meta = [];
        if(it.stock){ meta.push(String(it.stock)); }
        if(it.warranty){ meta.push(String(it.warranty)); }
        html += '<div class="market-offers-tooltip-row">'
            + '<div class="market-offers-tooltip-seller">' + escapeHtml(it.seller_name || 'Магазин без имени') + '</div>'
            + '<div class="market-offers-tooltip-price">' + escapeHtml(formatOfferTooltipPrice(it.price)) + '</div>'
            + (meta.length ? '<div class="market-offers-tooltip-meta">' + escapeHtml(meta.join(' · ')) + '</div>' : '')
            + '</div>';
    });
    html += '</div>';
    return html;
}

function fetchMarketOffersForTooltip(onlinerId){
    var oid = String(onlinerId || '').trim();
    if(!oid){ return Promise.resolve(null); }
    if(marketOffersTooltipCache[oid]){ return Promise.resolve(marketOffersTooltipCache[oid]); }
    return fetch('/api/onliner-offers/' + encodeURIComponent(oid))
        .then(function(r){ return r.json(); })
        .then(function(d){
            marketOffersTooltipCache[oid] = d;
            return d;
        });
}

function showMarketOffersTooltip(trigger, e){
    var oid = String((trigger && trigger.getAttribute('data-onliner-id')) || '').trim();
    if(!oid){ return; }
    var kind = String(trigger.getAttribute('data-market-kind') || '');
    var value = Number(trigger.getAttribute('data-market-value'));
    var tip = getMarketOffersTooltip();
    var token = ++marketOffersTooltipToken;
    marketOffersTooltipTarget = trigger;
    tip.innerHTML = '<div class="market-offers-tooltip-head"><span>Загружаю магазины...</span></div>';
    tip.classList.add('active');
    positionMarketOffersTooltip(e);
    fetchMarketOffersForTooltip(oid).then(function(d){
        if(token !== marketOffersTooltipToken || marketOffersTooltipTarget !== trigger){ return; }
        tip.innerHTML = renderMarketOffersTooltip(d, kind, value);
        positionMarketOffersTooltip(e);
    }).catch(function(){
        if(token !== marketOffersTooltipToken || marketOffersTooltipTarget !== trigger){ return; }
        tip.innerHTML = '<div class="market-offers-tooltip-head"><span>Onliner</span></div>'
            + '<div class="market-offers-tooltip-empty">Ошибка загрузки магазинов.</div>';
        positionMarketOffersTooltip(e);
    });
}

function initMarketOffersHover(){
    var tbody = document.querySelector('#preview-full-table tbody');
    if(!tbody){ return; }
    tbody.addEventListener('mouseover', function(e){
        var trigger = e.target.closest('.market-offers-trigger');
        if(!trigger || !tbody.contains(trigger) || marketOffersTooltipTarget === trigger){ return; }
        showMarketOffersTooltip(trigger, e);
    });
    tbody.addEventListener('mousemove', function(e){
        if(e.target.closest('.market-offers-trigger')){ positionMarketOffersTooltip(e); }
    });
    tbody.addEventListener('mouseout', function(e){
        var trigger = e.target.closest('.market-offers-trigger');
        if(!trigger || (e.relatedTarget && trigger.contains(e.relatedTarget))){ return; }
        hideMarketOffersTooltip();
    });
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
    var previewOrder = (previewModalDisplayOrder && previewModalDisplayOrder.length) ? previewModalDisplayOrder : previewModalItems;
    if(selectedPreviewRowIdx < 0 || selectedPreviewRowIdx >= previewOrder.length){
        note.textContent = 'Сначала выберите товар в таблице предпросмотра.';
        document.getElementById('offers-modal').classList.add('active');
        return;
    }
    var item = previewOrder[selectedPreviewRowIdx] || {};
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

function schedulePreviewModalItemsLoad(options){
    options = options || {};
    if(previewModalLoadTimer){
        clearTimeout(previewModalLoadTimer);
        previewModalLoadTimer = null;
    }
    var note = document.getElementById('preview-modal-note');
    if(note && !options.marketOnly){
        note.textContent = 'Выбираю категории...';
    }
    previewModalLoadTimer = setTimeout(function(){
        previewModalLoadTimer = null;
        loadPreviewModalItems(options);
    }, options.marketOnly ? 0 : 180);
}

function finishPreviewModalItemsLoad(requestSeq){
    if(previewModalInFlightSeq !== requestSeq){ return; }
    previewModalInFlight = false;
    previewModalInFlightSeq = 0;
    previewModalFetchController = null;
    var modal = document.getElementById('preview-modal');
    if(previewModalQueuedOptions && modal && modal.classList.contains('active')){
        var nextOptions = previewModalQueuedOptions;
        previewModalQueuedOptions = null;
        schedulePreviewModalItemsLoad(nextOptions);
    } else {
        previewModalQueuedOptions = null;
    }
}

function loadPreviewModalItems(options){
    options = options || {};
    var marketOnly = !!options.marketOnly;
    var categories = getSelectedValues('preview-modal-categories');
    var categoryFilters = getSelectedCategoryFilters('preview-modal-categories');
    if(!categories.length){
        categories = getSelectedValues('markup-categories');
        categoryFilters = getSelectedCategoryFilters('markup-categories');
    }
    var note = document.getElementById('preview-modal-note');
    if(!categories.length && !previewModalInFlight){
        previewModalItems = [];
        selectedPreviewRowIdx = -1;
        renderPreviewModalRows();
        note.textContent = 'Выберите хотя бы одну категорию в основном блоке.';
        setPreviewModalLoading(false);
        return;
    }
    if(previewModalInFlight){
        previewModalQueuedOptions = options;
        previewModalRequestSeq++;
        if(note && !marketOnly){
            note.textContent = 'Жду завершения предыдущей загрузки...';
        }
        return;
    }
    var requestSeq = ++previewModalRequestSeq;
    previewModalInFlight = true;
    previewModalInFlightSeq = requestSeq;
    if(previewModalFetchController && typeof previewModalFetchController.abort === 'function'){
        try { previewModalFetchController.abort(); } catch(_abortErr) {}
    }
    previewModalFetchController = null;
    var previousMarketMap = buildPreviewMarketMap(previewModalItems);
    setPreviewModalLoading(true);
    note.textContent = marketOnly ? 'Обновляю цены Onliner...' : 'Переключаю категории...';
    var catsPreview = categories.slice(0, 4).join(', ') + (categories.length > 4 ? '...' : '');
    var fetchOptions = {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({categories: categories, category_filters: categoryFilters, limit: 10000, with_market: true, allow_stale_market: true, max_market_checks: 400})
    };
    if(window.AbortController){
        previewModalFetchController = new AbortController();
        fetchOptions.signal = previewModalFetchController.signal;
    }
    fetch('/api/category-preview-items', fetchOptions).then(function(r){ return r.json(); }).then(function(d){
        if(requestSeq !== previewModalRequestSeq){ return; }
        previewModalFetchController = null;
        var rawPreviewItems = Array.isArray(d.items) ? d.items : [];
        var itemsWithOnlinerId = rawPreviewItems.filter(function(it){
            return String((it && it.onliner_id) || '').trim();
        });
        var hiddenNoOnlinerId = rawPreviewItems.length - itemsWithOnlinerId.length;
        previewModalItems = applyPreviewMarketTrend(itemsWithOnlinerId, previousMarketMap);
        selectedPreviewRowIdx = -1;
        renderPreviewModalRows({
            onFirstChunk: function(){ setPreviewModalLoading(false); }
        });
        var allMissing = previewModalItems.length > 0 && previewModalItems.every(function(it){
            return !it.market_min && !it.market_avg && !it.market_max;
        });
        var uniqIds = (d.market_unique_onliner_ids != null && d.market_unique_onliner_ids !== undefined)
            ? d.market_unique_onliner_ids : (d.market_checked || 0);
        note.textContent = 'Категории: ' + catsPreview + '. В таблице только товары с OnlinerID: ' + previewModalItems.length
            + ' (уникальных ID в кэше: ' + uniqIds + ')'
            + ', без данных по ID: ' + (d.missing_market_ids || 0)
            + ', скрыто без OnlinerID: ' + hiddenNoOnlinerId
            + '. Несколько строк с одним ID делят одни и те же рыночные цены.'
            + (allMissing ? ' Сейчас API/кэш не вернули рыночные цены ни по одному товару.' : '');
    }).catch(function(err){
        if(err && err.name === 'AbortError'){ return; }
        if(requestSeq !== previewModalRequestSeq){ return; }
        previewModalFetchController = null;
        note.textContent = 'Не удалось загрузить данные для предпросмотра.';
        setPreviewModalLoading(false);
    }).then(function(){
        finishPreviewModalItemsLoad(requestSeq);
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

function formatMarketCell(value, trend, competitors, wholesale, kind, onlinerId){
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
    var oid = String(onlinerId || '').trim();
    var attrs = '';
    if(oid){
        attrs = ' market-offers-trigger"'
            + ' data-market-kind="' + escapeHtml(kind || '') + '"'
            + ' data-onliner-id="' + escapeHtml(oid) + '"'
            + ' data-market-value="' + escapeHtml(String(marketValue)) + '"';
    } else {
        attrs = '"';
    }
    return '<div class="preview-market-cell' + attrs + '>'
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
    setRefreshMarketButtonProgress(btn, 0);
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
            setRefreshMarketButtonIdle(btn);
        }
    }).catch(function(){
        note.textContent = 'Ошибка запуска обновления цен.';
        btn.disabled = false;
        btn.classList.remove('is-updating');
        btn.style.setProperty('--progress', '0%');
        setRefreshMarketButtonIdle(btn);
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
        setRefreshMarketButtonProgress(btn, d.overall_percent || 0);
        var lines = Object.keys(cats).sort(compareCategoriesByUiOrder).map(function(name){
            var s = cats[name];
            var part = name + ': ' + (s.percent || 0) + '% (' + (s.done || 0) + '/' + (s.total || 0) + ')';
            if((s.errors || 0) > 0){
                part += ', ошибок: ' + (s.errors || 0);
            }
            return part;
        });
        var recentErrors = (d.recent_errors || []).slice(-6);
        var total = Number(d.total || 0);
        var done = Number(d.done || 0);
        var html = '';
        if(d.running && total <= 0){
            html = escapeHtml(d.message || 'Собираю список товаров с OnlinerID для обновления цен...');
        } else {
            html = 'Обновление кэша Onliner: ' + (d.overall_percent || 0) + '% (' + done + '/' + total + '), успешно: ' + (d.success || 0) + ', ошибок: ' + (d.errors || 0) + '.';
        }
        html += '<br><span style="color:#64748b;font-size:11px;">done/total и «Категории: …/…» — по <b>уникальным</b> Onliner ID, не по числу строк в прайсе.</span>';
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
        setRefreshMarketButtonIdle(btn);
        var doneHtml = 'Кэш Onliner обработан: ' + (d.done || 0) + ' уникальных ID, успешно: ' + (d.success || 0) + ', ошибок: ' + (d.errors || 0) + '. Обновляю предпросмотр...';
        doneHtml += '<br><span style="color:#64748b;font-size:11px;">Число уникальных ID обычно меньше строк в категории, если у разных позиций один и тот же OnlinerID.</span>';
        if(lines.length){
            doneHtml += '<br>Категории: ' + lines.join(' | ');
        }
        if(recentErrors.length){
            doneHtml += '<br>Лог ошибок: ' + recentErrors.map(escapeHtml).join(' | ');
        }
        note.innerHTML = doneHtml;
        schedulePreviewModalItemsLoad({marketOnly:true});
    }).catch(function(){
        btn.disabled = false;
        btn.classList.remove('is-updating');
        btn.style.setProperty('--progress', '0%');
        setRefreshMarketButtonIdle(btn);
        note.textContent = 'Ошибка чтения прогресса обновления.';
    });
}

function renderPreviewModalRows(options){
    options = options || {};
    var onFirstChunk = typeof options.onFirstChunk === 'function' ? options.onFirstChunk : null;
    var onComplete = typeof options.onComplete === 'function' ? options.onComplete : null;
    var chunkSize = Number(options.chunkSize);
    if(!isFinite(chunkSize) || chunkSize < 8){ chunkSize = 48; }
    ensurePreviewTableLayout();
    var tbody = document.querySelector('#preview-full-table tbody');
    if(!tbody){ return; }
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
    var sortedItems = (previewModalItems || []).filter(function(it){
        return String((it && it.onliner_id) || '').trim();
    }).slice().sort(function(a, b){
        var av = Number(a && a.price);
        var bv = Number(b && b.price);
        var aOk = isFinite(av);
        var bOk = isFinite(bv);
        if(aOk && bOk && av !== bv){ return av - bv; }
        if(aOk && !bOk){ return -1; }
        if(!aOk && bOk){ return 1; }
        return String((a && a.name) || '').localeCompare(String((b && b.name) || ''), 'ru');
    });
    previewModalDisplayOrder = sortedItems;
    var firstChunkNotified = false;
    function notifyFirstChunk(){
        if(firstChunkNotified){ return; }
        firstChunkNotified = true;
        if(onFirstChunk){ onFirstChunk(); }
    }
    function notifyComplete(){
        if(onComplete){ onComplete(); }
    }
    if(!sortedItems.length){
        tbody.innerHTML = '<tr><td colspan="11" style="color:#64748b;padding:18px;text-align:center;">'
            + 'В выбранных категориях нет товаров с OnlinerID для предпросмотра цен.'
            + '</td></tr>';
        notifyFirstChunk();
        notifyComplete();
        return;
    }
    var token = ++previewModalRenderRafToken;
    var i = 0;
    function appendRowAt(rowIdx){
        var it = sortedItems[rowIdx];
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
        tr.setAttribute('data-row-idx', String(rowIdx));
        var oid = String(it.onliner_id || '').trim();
        var minTxt = formatMarketCell(it.market_min, it.market_trend_min, it.min_competitors, wholesale, 'min', oid);
        var avgTxt = formatMarketCell(it.market_avg, it.market_trend_avg, it.avg_competitors, wholesale, 'avg', oid);
        var maxTxt = formatMarketCell(it.market_max, it.market_trend_max, it.market_offers, wholesale, 'max', oid);
        tr.innerHTML = '<td class="preview-category-cell">' + escapeHtml(it.category || '') + '</td>'
            + '<td class="preview-name-cell">' + escapeHtml(it.name || '') + '</td>'
            + '<td class="preview-supplier-cell">' + escapeHtml(it.supplier || '') + '</td>'
            + '<td class="preview-price-cell">' + (it.price || '') + '</td>'
            + '<td>' + minTxt + '</td>'
            + '<td>' + avgTxt + '</td>'
            + '<td>' + maxTxt + '</td>'
            + '<td class="preview-price-cell"><b style="color:' + rrcColor + '">' + (newRrc === '' ? '—' : Number(newRrc).toFixed(2)) + '</b></td>'
            + '<td class="preview-price-cell">' + (noDiscountPrice === '' ? '—' : Number(noDiscountPrice).toFixed(2)) + '</td>'
            + '<td class="preview-price-cell">' + (marginPct === '' ? '' : Number(marginPct).toFixed(2)) + '</td>'
            + '<td class="preview-rule-cell">' + escapeHtml(appliedRule) + '</td>';
        tbody.appendChild(tr);
    }
    function step(){
        if(token !== previewModalRenderRafToken){ return; }
        var end = Math.min(i + chunkSize, sortedItems.length);
        for(; i < end; i++){
            appendRowAt(i);
        }
        if(i > 0){
            notifyFirstChunk();
        }
        if(i < sortedItems.length){
            requestAnimationFrame(step);
        } else {
            notifyComplete();
        }
    }
    requestAnimationFrame(step);
}
