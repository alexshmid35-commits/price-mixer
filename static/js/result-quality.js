function ensureQualityCheckCardUI(){
    var card = document.getElementById('quality-check-card');
    if(!card){ return; }
    var header = card.firstElementChild;
    var body = card.children.length > 1 ? card.children[1] : null;
    if(header && !header.classList.contains('quality-card-head')){
        header.classList.add('quality-card-head');
    }
    if(body && !body.id){
        body.id = 'quality-check-card-body';
    }
    if(body){
        body.style.padding = '12px 14px';
    }
    var btn = document.getElementById('toggle-quality-check-card-btn');
    if(!btn && header){
        btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'toggle-quality-check-card-btn';
        btn.className = 'btn btn-outline quality-card-toggle';
        btn.textContent = 'Скрыть';
        header.appendChild(btn);
        btn.addEventListener('click', function(){
            toggleQualityCheckCard();
        });
    }
    var reapplyBtn = document.getElementById('quality-reapply-markups-btn');
    var details = document.getElementById('quality-check-details');
    if(reapplyBtn){
        reapplyBtn.classList.add('quality-reapply-btn');
        reapplyBtn.classList.remove('btn-outline');
        reapplyBtn.style.marginTop = '12px';
    }
    if(reapplyBtn && details && reapplyBtn.parentElement !== body){
        body.appendChild(reapplyBtn);
    } else if(reapplyBtn && body && reapplyBtn.parentElement === body){
        body.appendChild(reapplyBtn);
    }
    var actionsWrap = card.querySelector('.quality-actions');
    if(actionsWrap){
        actionsWrap.style.display = 'none';
    }
    syncQualityCheckCardCollapsed();
}

function syncQualityCheckCardCollapsed(){
    var body = document.getElementById('quality-check-card-body');
    var btn = document.getElementById('toggle-quality-check-card-btn');
    if(!body || !btn){ return; }
    body.style.display = qualityCheckCardCollapsed ? 'none' : 'block';
    btn.textContent = qualityCheckCardCollapsed ? 'Показать' : 'Скрыть';
}

function toggleQualityCheckCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        qualityCheckCardCollapsed = forceCollapsed;
    } else {
        qualityCheckCardCollapsed = !qualityCheckCardCollapsed;
    }
    syncQualityCheckCardCollapsed();
}

function runPreExportQualityCheck(){
    var card = document.getElementById('quality-check-card');
    var summary = document.getElementById('quality-check-summary');
    var details = document.getElementById('quality-check-details');
    if(card){ card.style.display = 'block'; }
    if(summary){ summary.textContent = 'Проверка качества выполняется...'; }
    if(details){ details.innerHTML = ''; }
    fetch('/api/preexport-quality-check').then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){
            if(summary){ summary.textContent = (d && d.message) ? d.message : 'Не удалось выполнить проверку качества.'; }
            return;
        }
        if(summary){
            summary.textContent = 'Проверено строк: ' + String(d.checked || 0)
                + '. Без ID: ' + String(d.missing_id_count || 0)
                + ', подозрительные цены: ' + String(d.suspicious_price_count || 0)
                + ', дубли: ' + String(d.duplicate_count || 0) + '.';
        }
        setActionBadge('quality-check-badge', d.suspicious_price_count || 0, {
            title: 'Цены, где надо проверить или доприменить наценки: {count}'
        });
        var html = '';
        function block(title, arr){
            var items = Array.isArray(arr) ? arr : [];
            if(!items.length){ return '<div style="margin-top:6px;"><b>' + title + ':</b> нет</div>'; }
            return '<div style="margin-top:8px;"><b>' + title + ':</b><ul style="margin:6px 0 0 18px;">'
                + items.map(function(it){ return '<li>' + escapeHtml(String(it)) + '</li>'; }).join('')
                + '</ul></div>';
        }
        html += block('Примеры подозрительных цен', d.suspicious_price_samples || []);
        html += block('Примеры дублей', d.duplicate_samples || []);
        if(details){
            details.innerHTML = html;
        }
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
