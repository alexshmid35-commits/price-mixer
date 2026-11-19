function ensureQualityCheckCardUI(){
    syncQualityCheckCardCollapsed();
}

function syncQualityCheckCardCollapsed(){
    var body = document.getElementById('quality-check-card-body');
    var btn = document.getElementById('toggle-quality-check-card-btn');
    if(!body || !btn){ return; }
    body.hidden = qualityCheckCardCollapsed;
    btn.textContent = qualityCheckCardCollapsed ? 'Развернуть' : 'Свернуть';
    btn.setAttribute('aria-expanded', String(!qualityCheckCardCollapsed));
}

function toggleQualityCheckCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        qualityCheckCardCollapsed = forceCollapsed;
    } else {
        qualityCheckCardCollapsed = !qualityCheckCardCollapsed;
    }
    syncQualityCheckCardCollapsed();
}

function renderQualityIssueRow(kind, sample){
    var parts = /^\[([^\]]*)\]\s+(.*)$/s.exec(String(sample));
    var category = parts ? parts[1] : '';
    var name = parts ? parts[2] : String(sample);
    var reason = kind === 'duplicates' ? 'Дубль' : kind === 'missing' ? 'Нет OnlinerID' : '';
    var numbers = '';
    if(parts && kind === 'prices'){
        var price = /^(.*) \| причина: (.*?) \| опт=(.*)$/s.exec(name);
        if(price){
            name = price[1];
            reason = price[2];
            numbers = 'Опт: ' + price[3].replace(', РРЦ=', ' · РРЦ: ').replace(', маржа=', ' · Маржа: ');
        }
    } else if(parts && kind === 'duplicates'){
        var duplicate = /^(.*) \(x(\d+)\)$/s.exec(name);
        if(duplicate){
            name = duplicate[1];
            reason += ' · ' + duplicate[2] + ' одинаковых строк';
        }
    }
    return '<li class="workspace-quality-row"><div><strong>' + escapeHtml(name) + '</strong>'
        + (category ? '<small>' + escapeHtml(category) + '</small>' : '') + '</div>'
        + '<div><strong>' + escapeHtml(reason) + '</strong>'
        + (numbers ? '<small>' + escapeHtml(numbers) + '</small>' : '') + '</div></li>';
}

function renderQualityIssues(details, report){
    var groups = {
        prices: [report.suspicious_price_count, report.suspicious_price_samples, 'Замечаний по ценам нет.'],
        duplicates: [report.duplicate_count, report.duplicate_samples, 'Дублей не найдено.'],
        missing: [report.missing_id_count, report.missing_id_samples, 'Товаров без OnlinerID нет.']
    };
    var buttons = Array.from(details.querySelectorAll('[data-quality-kind]'));
    var list = document.getElementById('quality-issue-list');
    var note = document.getElementById('quality-issue-note');
    var format = new Intl.NumberFormat('ru-RU');
    function show(kind){
        var group = groups[kind];
        var count = Number(group[0] || 0);
        var items = Array.isArray(group[1]) ? group[1] : [];
        buttons.forEach(function(button){
            button.setAttribute('aria-pressed', String(button.dataset.qualityKind === kind));
        });
        list.dataset.qualityKind = kind;
        list.innerHTML = items.map(function(item){ return renderQualityIssueRow(kind, item); }).join('');
        list.hidden = !items.length;
        note.textContent = !count ? group[2] : !items.length ? 'Примеры недоступны.'
            : items.length < count ? 'Показано ' + format.format(items.length) + ' из ' + format.format(count) : '';
        note.hidden = !note.textContent;
    }
    buttons.forEach(function(button){
        var kind = button.dataset.qualityKind;
        button.querySelector('strong').textContent = format.format(groups[kind][0] || 0);
        button.onclick = function(){ show(kind); };
    });
    var firstWithIssues = buttons.find(function(button){ return Number(groups[button.dataset.qualityKind][0]) > 0; });
    show(firstWithIssues ? firstWithIssues.dataset.qualityKind : 'prices');
    details.hidden = false;
}

function runPreExportQualityCheck(){
    var card = document.getElementById('quality-check-card');
    var summary = document.getElementById('quality-check-summary');
    var details = document.getElementById('quality-check-details');
    if(card){ card.hidden = false; }
    document.getElementById('run-quality-check-btn').setAttribute('aria-expanded', 'true');
    toggleQualityCheckCard(false);
    if(summary){ summary.textContent = 'Проверка качества выполняется...'; }
    if(details){ details.hidden = true; }
    fetch('/api/preexport-quality-check').then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            if(summary){ summary.textContent = (d && d.message) ? d.message : 'Не удалось выполнить проверку качества.'; }
            return;
        }
        if(summary){
            summary.textContent = 'Проверено строк: ' + new Intl.NumberFormat('ru-RU').format(d.checked || 0);
        }
        setActionBadge('quality-check-badge', d.suspicious_price_count || 0, {
            title: 'Цены, где надо проверить или доприменить наценки: {count}'
        });
        if(details){ renderQualityIssues(details, d); }
    }).catch(function(){
        if(summary){ summary.textContent = 'Ошибка запуска проверки качества.'; }
    });
}

function reapplySavedMarkupsFromQuality(){
    var summary = document.getElementById('quality-check-summary');
    var btn = document.getElementById('quality-reapply-markups-btn');
    if(summary){ summary.textContent = 'Доприменяю сохранённые наценки по категориям...'; }
    if(btn){ btn.disabled = true; }
    fetch('/api/reapply-saved-markups', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({source: 'quality_check'})
    }).then(function(r){
        return r.json().then(function(d){ return {ok:r.ok, data:d}; });
    }).then(function(resp){
        var d = resp.data || {};
        if(!resp.ok || d.status !== 'ok'){
            if(summary){ summary.textContent = d.message || 'Не удалось доприменить наценки.'; }
            if(btn){ btn.disabled = false; }
            return;
        }
        if(summary){
            summary.textContent = 'Наценки доприменены. Обновлено строк: ' + String(d.updated_rows || 0) + '. Перепроверяю...';
        }
        if(tblMain && tblMain.ajax && tblMain.ajax.reload){ tblMain.ajax.reload(null, false); }
        runPreExportQualityCheck();
        refreshQualityCheckBadge();
        if(btn){ btn.disabled = false; }
    }).catch(function(){
        if(summary){ summary.textContent = 'Ошибка доприменения наценок.'; }
        if(btn){ btn.disabled = false; }
    });
}
