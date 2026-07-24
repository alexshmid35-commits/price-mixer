function initMainTableFallback(){
    mainTableServerSide = false;
    var tbody = document.getElementById('tbl-main-body');
    if(!tbody){ return; }
    ensureNoIdCategoryFilterControl();
    fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
        mainTableRows = (d && d.data) ? d.data : [];
        rebuildDuplicateIdFilterSet(mainTableRows);
        updateWithoutIdCount(mainTableRows);
        updateNtechCheckCategoryBadges(mainTableRows);
        updateNoIdCategoryFilterOptions(mainTableRows);
        renderMainTableFallback();
    }).catch(function(){
        tbody.innerHTML = '<tr><td colspan="8" style="padding:14px;color:#b91c1c;">Ошибка загрузки данных</td></tr>';
    });
    tblMain = {
        ajax: {
            reload: function(cb){
                fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(d){
                    mainTableRows = (d && d.data) ? d.data : [];
                    rebuildDuplicateIdFilterSet(mainTableRows);
                    updateWithoutIdCount(mainTableRows);
                    updateNtechCheckCategoryBadges(mainTableRows);
                    updateNoIdCategoryFilterOptions(mainTableRows);
                    renderMainTableFallback();
                    if(typeof cb === 'function'){ cb(); }
                }).catch(function(){
                    if(typeof cb === 'function'){ cb(); }
                });
            }
        }
    };
}

function applyMainTableServerMeta(meta){
    meta = meta || {};
    var rawDuplicates = (meta.duplicate_ids && typeof meta.duplicate_ids === 'object') ? meta.duplicate_ids : {};
    var nextSet = {};
    var nextPrices = {};
    Object.keys(rawDuplicates).forEach(function(oid){
        var values = Array.isArray(rawDuplicates[oid]) ? rawDuplicates[oid] : [];
        nextSet[String(oid)] = true;
        nextPrices[String(oid)] = {
            min: Number(values[1]),
            max: Number(values[2])
        };
    });
    duplicateIdFilterSet = nextSet;
    duplicateIdPriceStats = nextPrices;
    loadedSupplierCount = Math.max(1, Number(meta.supplier_count || loadedSupplierCount || 1));
    setDuplicateIdCounterValue(Number(
        meta.duplicate_row_count !== undefined
            ? meta.duplicate_row_count
            : Object.keys(nextSet).length
    ));

    mainTableNoIdCategoryBuckets = Array.isArray(meta.without_id_category_counts)
        ? meta.without_id_category_counts.slice()
        : [];
    if(typeof updateWithoutIdCountValue === 'function'){
        updateWithoutIdCountValue(Number(meta.without_id_count || 0), mainTableNoIdCategoryBuckets);
    }
    mainTableBadgeCounts = (meta.badge_counts && typeof meta.badge_counts === 'object')
        ? meta.badge_counts
        : {};
    if(typeof applyNtechCheckBadgeCounts === 'function'){
        applyNtechCheckBadgeCounts(mainTableBadgeCounts);
    }
    updateNoIdCategoryFilterOptions(mainTableRows || []);
}

function renderMainTableFallback(){
    var tbody = document.getElementById('tbl-main-body');
    if(!tbody){ return; }
    var rows = (mainTableRows || []).slice().sort(function(a,b){
        if(showOnlyDuplicateIdRows){
            var ao = String((a && a[0]) || '').trim();
            var bo = String((b && b[0]) || '').trim();
            if(ao !== bo){ return ao.localeCompare(bo, 'ru'); }
            var ap = Number((a && a[2]) || NaN);
            var bp = Number((b && b[2]) || NaN);
            var aOk = isFinite(ap);
            var bOk = isFinite(bp);
            if(aOk && bOk && ap !== bp){ return ap - bp; }
            if(aOk && !bOk){ return -1; }
            if(!aOk && bOk){ return 1; }
        }
        return String(a[1] || '').localeCompare(String(b[1] || ''), 'ru');
    });
    if(showOnlyNoIdRows){
        rows = rows.filter(function(r){
            if(String(r[0] || '').trim()){ return false; }
            if(shouldHideNoIdCategoryFilterOption(r[9])){ return false; }
            if(!selectedNoIdCategory){ return true; }
            return normalizeNoIdCategoryName(r[9]) === normalizeNoIdCategoryName(selectedNoIdCategory);
        });
    }
    if(showOnlyExportRows){
        rows = rows.filter(function(r){
            return isMainTableRowInGoogleExport(r);
        });
    }
    if(showOnlyDuplicateIdRows){
        rows = rows.filter(function(r){
            var oid = String((r && r[0]) || '').trim();
            return !!(oid && duplicateIdFilterSet[oid]);
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
    rows.forEach(function(r, idx){
        var oid = String(r[0] || '').trim();
        var rowIdx = Number(r[8] || -1);
        var name = renderMainTableNameCell(r[1] || '', r);
        var price = renderMainPriceCell(r[2], r);
        var supplier = escapeHtml(r[3] || '');
        var warranty = escapeHtml(r[4] || '');
        var lead = escapeHtml(r[5] || '');
        var rrc = (r[6] || r[6]===0) ? Number(r[6]).toFixed(2) : '';
        var noDiscount = (r[7] || r[7]===0) ? Number(r[7]).toFixed(2) : '';
        var rowClass = getDuplicateGroupRowClass(rows, idx);
        html += '<tr' + (rowClass ? (' class="' + rowClass + '"') : '') + '>'
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

function normalizeNoIdCategoryName(value){
    return String(value || '').trim() || 'Без категории';
}

function getNoIdCategoryBuckets(rows){
    if(mainTableServerSide && Array.isArray(mainTableNoIdCategoryBuckets)){
        return mainTableNoIdCategoryBuckets.map(function(item){
            return {
                category: normalizeNoIdCategoryName(item && item.category),
                count: Number((item && item.count) || 0)
            };
        }).filter(function(item){
            return !shouldHideNoIdCategoryFilterOption(item.category);
        }).sort(function(a, b){
            return compareNoIdCategoryFilterOrder(a.category, b.category);
        });
    }
    var buckets = {};
    (Array.isArray(rows) ? rows : []).forEach(function(r){
        if(String((r && r[0]) || '').trim()){ return; }
        var category = normalizeNoIdCategoryName(r && r[9]);
        if(shouldHideNoIdCategoryFilterOption(category)){ return; }
        buckets[category] = Number(buckets[category] || 0) + 1;
    });
    return Object.keys(buckets).sort(compareNoIdCategoryFilterOrder).map(function(category){
        return {category: category, count: buckets[category]};
    });
}

function shouldHideNoIdCategoryFilterOption(category){
    var text = normalizeNoIdCategoryName(category);
    if(text.indexOf('Требует сортировки') === 0){ return true; }
    if(typeof shouldShowMarkupCategoryName === 'function' && !shouldShowMarkupCategoryName(text)){ return true; }
    return false;
}

function compareNoIdCategoryFilterOrder(a, b){
    if(typeof compareCategoriesByUiOrder === 'function'){
        return compareCategoriesByUiOrder(a, b);
    }
    return String(a).localeCompare(String(b), 'ru');
}

function ensureNoIdCategoryFilterControl(){
    var existing = document.getElementById('noid-category-filter-wrap');
    if(existing){ return existing; }
    var table = document.getElementById('tbl-main');
    if(!table){ return null; }
    var wrap = document.createElement('div');
    wrap.id = 'noid-category-filter-wrap';
    wrap.className = 'noid-category-filter';
    wrap.hidden = true;
    wrap.innerHTML = ''
        + '<label class="noid-category-filter-label" for="noid-category-filter-select">'
        + '<span>Категория без ID</span>'
        + '<select id="noid-category-filter-select"><option value="">Все категории без ID</option></select>'
        + '</label>'
        + '<button type="button" id="noid-category-filter-clear" class="noid-category-filter-clear" title="Сбросить категорию" aria-label="Сбросить категорию">×</button>';

    var dtLength = document.querySelector('#tbl-main_wrapper .dataTables_length');
    if(dtLength && dtLength.parentNode){
        dtLength.parentNode.insertBefore(wrap, dtLength.nextSibling);
    } else {
        table.parentNode.insertBefore(wrap, table);
    }

    var select = wrap.querySelector('#noid-category-filter-select');
    if(select){
        select.addEventListener('change', function(){
            selectedNoIdCategory = String(select.value || '');
            closeNoIdInlinePicker(false);
            redrawMainTable();
        });
    }
    var clearBtn = wrap.querySelector('#noid-category-filter-clear');
    if(clearBtn){
        clearBtn.addEventListener('click', function(){
            selectedNoIdCategory = '';
            if(select){ select.value = ''; }
            closeNoIdInlinePicker(false);
            redrawMainTable();
        });
    }
    return wrap;
}

function updateNoIdCategoryFilterOptions(rows){
    var wrap = ensureNoIdCategoryFilterControl();
    if(!wrap){ return; }
    var select = document.getElementById('noid-category-filter-select');
    if(!select){ return; }
    var buckets = getNoIdCategoryBuckets(rows);
    var current = String(selectedNoIdCategory || '');
    var hasCurrent = !current || buckets.some(function(item){ return item.category === current; });
    if(!hasCurrent){
        current = '';
        selectedNoIdCategory = '';
    }
    var total = buckets.reduce(function(acc, item){ return acc + Number(item.count || 0); }, 0);
    var html = '<option value="">Все категории без ID · ' + String(total) + '</option>';
    html += buckets.map(function(item){
        var category = String(item.category || 'Без категории');
        var count = Number(item.count || 0);
        return '<option value="' + escapeHtml(category) + '">' + escapeHtml(category) + ' · ' + escapeHtml(String(count)) + '</option>';
    }).join('');
    select.innerHTML = html;
    select.value = current;
    wrap.hidden = !showOnlyNoIdRows || buckets.length === 0;
}

function setNoIdCategoryFilterVisible(visible){
    var wrap = ensureNoIdCategoryFilterControl();
    if(!wrap){ return; }
    wrap.hidden = !visible;
    if(visible){
        updateNoIdCategoryFilterOptions(mainTableRows || []);
    }
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

function rebuildDuplicateIdFilterSet(rows){
    var counts = {};
    var supplierSet = {};
    var stats = {};
    (Array.isArray(rows) ? rows : []).forEach(function(r){
        var supplier = String((r && r[3]) || '').trim();
        if(supplier){ supplierSet[supplier] = true; }
        var oid = String((r && r[0]) || '').trim();
        if(!oid){ return; }
        counts[oid] = (counts[oid] || 0) + 1;
        var price = Number((r && r[2]) || NaN);
        if(isFinite(price)){
            if(!stats[oid]){
                stats[oid] = {min: price, max: price};
            } else {
                if(price < stats[oid].min){ stats[oid].min = price; }
                if(price > stats[oid].max){ stats[oid].max = price; }
            }
        }
    });
    var next = {};
    var priceMap = {};
    Object.keys(counts).forEach(function(oid){
        if(counts[oid] > 1){
            next[oid] = true;
            if(stats[oid]){ priceMap[oid] = stats[oid]; }
        }
    });
    duplicateIdFilterSet = next;
    duplicateIdPriceStats = priceMap;
    loadedSupplierCount = Math.max(1, Object.keys(supplierSet).length || loadedSupplierCount || 1);
    setDuplicateIdCounterValue(Object.keys(next).length);
}

function getDuplicatePriceTone(oid, priceValue){
    var id = String(oid || '').trim();
    if(!showOnlyDuplicateIdRows || !id || !duplicateIdFilterSet[id]){
        return '';
    }
    var price = Number(priceValue);
    var stats = duplicateIdPriceStats[id];
    if(!isFinite(price) || !stats || !isFinite(stats.min)){
        return '';
    }
    if(Math.abs(price - stats.min) < 0.0001){ return 'min'; }
    return 'high';
}

function renderMainPriceCell(value, row){
    var n = Number(value);
    if(!isFinite(n)){ return ''; }
    var oid = String((row && row[0]) || '').trim();
    var tone = getDuplicatePriceTone(oid, n);
    if(tone === 'min'){
        return '<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#dcfce7;color:#166534;font-weight:700;">' + n.toFixed(2) + '</span>';
    }
    if(tone === 'high'){
        return '<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#fee2e2;color:#b91c1c;font-weight:700;">' + n.toFixed(2) + '</span>';
    }
    return '<b style="color:#2e7d32">' + n.toFixed(2) + '</b>';
}

function getDuplicateGroupRowClass(rows, idx){
    if(!showOnlyDuplicateIdRows){ return ''; }
    var cur = String((rows[idx] && rows[idx][0]) || '').trim();
    if(!cur || !duplicateIdFilterSet[cur]){ return ''; }
    var prev = idx > 0 ? String((rows[idx - 1] && rows[idx - 1][0]) || '').trim() : '';
    var next = idx < rows.length - 1 ? String((rows[idx + 1] && rows[idx + 1][0]) || '').trim() : '';
    var hasPrev = prev === cur;
    var hasNext = next === cur;
    if(hasPrev && hasNext){ return 'dup-group-mid'; }
    if(hasPrev){ return 'dup-group-end'; }
    if(hasNext){ return 'dup-group-start'; }
    return 'dup-group-single';
}

function getMainTableRowIndex(row){
    if(!Array.isArray(row)){ return ''; }
    var raw = row.length > 8 ? row[8] : '';
    var idx = Number(raw);
    if(!isFinite(idx)){ return ''; }
    return String(Math.trunc(idx));
}

function getMainTableFilterRowData(rowData, settings, dataIndex){
    if(Array.isArray(rowData)){ return rowData; }
    if(settings && settings.aoData && settings.aoData[dataIndex] && Array.isArray(settings.aoData[dataIndex]._aData)){
        return settings.aoData[dataIndex]._aData;
    }
    return null;
}

function isMainTableRowInGoogleExport(rowData, settings, dataIndex){
    var row = getMainTableFilterRowData(rowData, settings, dataIndex);
    var idx = getMainTableRowIndex(row);
    return !!(idx && exportRowIndexSet && exportRowIndexSet[idx]);
}
