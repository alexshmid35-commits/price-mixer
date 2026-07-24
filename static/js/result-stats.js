function updateWithoutIdCount(rows){
    var el = document.getElementById('without-id-count');
    if(!el){ return; }
    var list = Array.isArray(rows) ? rows : [];
    var categoryCounts = {};
    var count = list.reduce(function(acc, r){
        if(String((r && r[0]) || '').trim()){
            return acc;
        }
        var category = String((r && r[9]) || '').trim() || 'Без категории';
        categoryCounts[category] = Number(categoryCounts[category] || 0) + 1;
        return acc + 1;
    }, 0);
    el.textContent = String(count);
    setWithoutIdCategoryCounts(Object.keys(categoryCounts).sort(function(a, b){
        return a.localeCompare(b, 'ru');
    }).map(function(category){
        return {category: category, count: categoryCounts[category]};
    }));
}

function updateWithoutIdCountValue(count, categoryCounts){
    var el = document.getElementById('without-id-count');
    if(el){ el.textContent = String(Math.max(0, Number(count || 0))); }
    setWithoutIdCategoryCounts(Array.isArray(categoryCounts) ? categoryCounts : []);
}

function setExportProductsCountValue(v){
    var el = document.getElementById('export-products-count');
    if(!el){ return; }
    el.textContent = String(v == null ? 0 : v);
}

function renderExportCategoryAnalytics(){
    var listEl = document.getElementById('export-category-analytics-list');
    var totalEl = document.getElementById('export-category-analytics-total');
    var btn = document.getElementById('export-category-analytics-btn');
    if(!listEl){ return; }
    var items = sortCategoryAnalyticsItems(Array.isArray(exportCategoryCounts) ? exportCategoryCounts.slice() : []);
    var total = items.reduce(function(acc, item){
        return acc + Number((item && item.count) || 0);
    }, 0);
    if(totalEl){ totalEl.textContent = String(total); }
    if(btn){
        btn.title = items.length
            ? ('Категорий в выгрузке: ' + String(items.length) + ', товаров: ' + String(total))
            : 'В выгрузке пока нет товаров';
    }
    if(!items.length){
        listEl.innerHTML = '<span class="stat-export-analytics-row"><span class="stat-export-analytics-cat">Нет товаров для выгрузки</span><span class="stat-export-analytics-count">0</span></span>';
        return;
    }
    listEl.innerHTML = items.map(function(item){
        var category = String((item && item.category) || 'Без категории');
        var count = Number((item && item.count) || 0);
        return '<span class="stat-export-analytics-row">'
            + '<span class="stat-export-analytics-cat" title="' + escapeHtml(category) + '">' + escapeHtml(category) + '</span>'
            + '<span class="stat-export-analytics-count">' + escapeHtml(String(count)) + '</span>'
            + '</span>';
    }).join('');
}

function setExportCategoryCounts(items){
    exportCategoryCounts = Array.isArray(items) ? items : [];
    renderExportCategoryAnalytics();
}

function renderWithoutIdCategoryAnalytics(){
    var listEl = document.getElementById('without-id-category-analytics-list');
    var totalEl = document.getElementById('without-id-category-analytics-total');
    var btn = document.getElementById('without-id-category-analytics-btn');
    if(!listEl){ return; }
    var items = sortCategoryAnalyticsItems(Array.isArray(withoutIdCategoryCounts) ? withoutIdCategoryCounts.slice() : []);
    var total = items.reduce(function(acc, item){
        return acc + Number((item && item.count) || 0);
    }, 0);
    if(totalEl){ totalEl.textContent = String(total); }
    if(btn){
        btn.title = items.length
            ? ('Категорий без ID: ' + String(items.length) + ', товаров: ' + String(total))
            : 'Товаров без OnlinerID нет';
    }
    if(!items.length){
        listEl.innerHTML = '<span class="stat-noid-analytics-row"><span class="stat-noid-analytics-cat">Все товары с OnlinerID</span><span class="stat-noid-analytics-count">0</span></span>';
        return;
    }
    listEl.innerHTML = items.map(function(item){
        var category = String((item && item.category) || 'Без категории');
        var count = Number((item && item.count) || 0);
        return '<span class="stat-noid-analytics-row">'
            + '<span class="stat-noid-analytics-cat" title="' + escapeHtml(category) + '">' + escapeHtml(category) + '</span>'
            + '<span class="stat-noid-analytics-count">' + escapeHtml(String(count)) + '</span>'
            + '</span>';
    }).join('');
}

function setWithoutIdCategoryCounts(items){
    withoutIdCategoryCounts = Array.isArray(items) ? items : [];
    renderWithoutIdCategoryAnalytics();
}

function renderHiddenCategoryAnalytics(){
    var listEl = document.getElementById('hidden-category-analytics-list');
    var totalEl = document.getElementById('hidden-category-analytics-total');
    var countEl = document.getElementById('hidden-category-count');
    var btn = document.getElementById('hidden-category-analytics-btn');
    var items = sortCategoryAnalyticsItems(Array.isArray(hiddenCategoryCounts) ? hiddenCategoryCounts.slice() : []);
    var total = items.reduce(function(acc, item){
        return acc + Number((item && item.count) || 0);
    }, 0);
    if(totalEl){ totalEl.textContent = String(total); }
    if(countEl){ countEl.textContent = String(total); }
    if(btn){
        btn.title = items.length
            ? ('Скрытых категорий: ' + String(items.length) + ', товаров: ' + String(total))
            : 'Скрытых категорий нет';
    }
    if(!listEl){ return; }
    if(!items.length){
        listEl.innerHTML = '<span class="stat-hidden-analytics-row"><span class="stat-hidden-analytics-cat">Скрытых категорий нет</span><span class="stat-hidden-analytics-count">0</span></span>';
        return;
    }
    listEl.innerHTML = items.map(function(item){
        var category = String((item && item.category) || 'Без категории');
        var count = Number((item && item.count) || 0);
        return '<span class="stat-hidden-analytics-row">'
            + '<span class="stat-hidden-analytics-cat" title="' + escapeHtml(category) + '">Скрыто: ' + escapeHtml(category) + '</span>'
            + '<span class="stat-hidden-analytics-count">' + escapeHtml(String(count)) + '</span>'
            + '</span>';
    }).join('');
}

function setHiddenCategoryCounts(items){
    hiddenCategoryCounts = Array.isArray(items) ? items : [];
    renderHiddenCategoryAnalytics();
}

function sortCategoryAnalyticsItems(items){
    return (Array.isArray(items) ? items : []).sort(function(a, b){
        return compareCategoriesByUiOrder(
            String((a && a.category) || ''),
            String((b && b.category) || '')
        );
    });
}

function updateStatsCounters(s){
    if(!s){ return; }
    var withoutIdEl = document.getElementById('without-id-count');
    if(withoutIdEl && s.without_id !== undefined){
        withoutIdEl.textContent = s.without_id;
    }
    if(s.without_id_category_counts !== undefined){
        setWithoutIdCategoryCounts(s.without_id_category_counts);
    }
    if(s.hidden_category_counts !== undefined){
        setHiddenCategoryCounts(s.hidden_category_counts);
    } else if(s.hidden_rows !== undefined) {
        var hiddenEl = document.getElementById('hidden-category-count');
        if(hiddenEl){ hiddenEl.textContent = String(s.hidden_rows || 0); }
    }
    if(s.duplicate_id_rows !== undefined){
        setDuplicateIdCounterValue(s.duplicate_id_rows);
    }
    if(s.export_rows !== undefined){
        setExportProductsCountValue(s.export_rows);
    }
    if(s.export_category_counts !== undefined){
        setExportCategoryCounts(s.export_category_counts);
    }
}

function setDuplicateIdCounterValue(v){
    var el = document.getElementById('duplicate-id-count');
    if(!el){ return; }
    el.style.visibility = '';
    el.textContent = String(v == null ? 0 : v);
}
