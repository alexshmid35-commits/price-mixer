var _reviewQueueData = {};

function highlightCpuModelMatch(candidateName, cpuModel){
    var text = String(candidateName || '');
    var model = String(cpuModel || '').trim();
    if(!model){
        return escapeHtml(text);
    }
    var escapedText = escapeHtml(text);
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(!compactModel){
        return escapedText;
    }
    var patterns = [
        model,
        model.replace(/\s+/g, ''),
        model.replace(/([a-z]+)(\d)/ig, '$1 $2'),
        model.replace(/([a-z]+)\s*(\d)/ig, '$1-$2')
    ].filter(function(v, idx, arr){
        return v && arr.indexOf(v) === idx;
    });
    for(var i = 0; i < patterns.length; i++){
        var raw = String(patterns[i] || '');
        if(!raw){ continue; }
        var escapedPattern = raw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s*');
        var re = new RegExp('(' + escapedPattern + ')', 'i');
        if(re.test(text)){
            return escapedText.replace(re, '<span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 4px;font-weight:700;">$1</span>');
        }
    }
    var compactText = text.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(compactText.indexOf(compactModel) >= 0){
        return escapedText + ' <span style="display:inline-flex;align-items:center;gap:4px;background:#dcfce7;color:#166534;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:700;vertical-align:middle;">модель совпала</span>';
    }
    return escapedText;
}

function parseCpuBrandModel(candidateName){
    var text = String(candidateName || '').toLowerCase();
    var brand = '';
    if(/intel|xeon|pentium|celeron/.test(text)){ brand = 'INTEL'; }
    else if(/amd|ryzen|athlon/.test(text)){ brand = 'AMD'; }
    var patterns = [
        /\b(i[3579]-\d{4,5}[a-z]{0,2})\b/i,
        /\b(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})\b/i,
        /\b(pentium\s+[a-z]?\d{4,5})\b/i,
        /\b(celeron\s+[a-z]?\d{4,5})\b/i,
        /\b(athlon\s+\d{4,5}[a-z]{0,2})\b/i,
        /\b(xeon\s+[ew]?-?\d{1,2}-?\d{4,5}\s*v?\d?)\b/i
    ];
    var model = '';
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            model = String(m[1]).toUpperCase().replace(/\s+/g, ' ').trim();
            break;
        }
    }
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    return { brand: brand, model: model, compactModel: compactModel };
}

function cpuCandidateTone(item, candidate){
    var expectedBrand = String((item && item.cpu_brand) || '').trim().toUpperCase();
    var expectedModel = String((item && item.cpu_model) || '').trim().toUpperCase();
    var parsed = parseCpuBrandModel(String((candidate && candidate.name) || ''));
    var sameBrand = !!expectedBrand && parsed.brand === expectedBrand;
    var sameModel = !!expectedModel && !!parsed.compactModel && parsed.compactModel === expectedModel.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(sameBrand && sameModel){
        return {
            bg: '#dcfce7',
            color: '#166534',
            border: '#86efac',
            label: 'точное CPU'
        };
    }
    if(sameModel){
        return {
            bg: '#fef3c7',
            color: '#92400e',
            border: '#fcd34d',
            label: 'модель ок'
        };
    }
    return {
        bg: '#fee2e2',
        color: '#991b1b',
        border: '#fca5a5',
        label: 'проверить'
    };
}

function cpuCandidatePriority(item, candidate){
    var tone = cpuCandidateTone(item, candidate);
    if(tone.label === 'точное CPU'){ return 0; }
    if(tone.label === 'модель ок'){ return 1; }
    return 2;
}

window.loadReviewQueue = function(){
    fetch('/api/review-queue?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(data){
        var items = Array.isArray(data.items) ? data.items : [];
        var card  = document.getElementById('review-queue-card');
        var badge = document.getElementById('review-queue-count-badge');
        var list  = document.getElementById('review-queue-list');
        var note  = document.getElementById('review-queue-note');
        var qBtn  = document.getElementById('show-review-queue-btn');

        if(badge){
            if(items.length > 0){ badge.textContent = items.length; badge.style.display = 'inline-block'; }
            else { badge.style.display = 'none'; }
        }
        if(qBtn){ qBtn.style.background = items.length > 0 ? '#ede9fe' : ''; }
        if(!list) return;

        if(!items.length){
            list.innerHTML = '<div class="markup-note" style="color:#6b7280;">Очередь пуста — нет товаров ожидающих ручной проверки.</div>';
            if(note) note.textContent = 'Запустите «Валидация и очистка ID» — неверно сопоставленные товары появятся здесь с кандидатами на выбор.';
            return;
        }
        if(card) card.style.display = 'block';
        if(note) note.textContent = 'Выберите правильный ID из кандидатов или нажмите «Пропустить». После выбора — запустите автоподбор снова.';

        // Сохраняем данные в глобальный map по индексу — без небезопасных inline-аргументов
        _reviewQueueData = {};
        items.forEach(function(item, idx){ _reviewQueueData[idx] = item; });

        var html = '';
        items.forEach(function(item, idx){
            var name      = escapeHtml(item.name||'');
            var cpuBrand  = escapeHtml(String(item.cpu_brand||'').trim());
            var cpuModel  = escapeHtml(String(item.cpu_model||'').trim());
            var clearedId = escapeHtml(String(item.cleared_id||''));
            var clearedSc = item.cleared_score !== undefined ? String(Math.round(Number(item.cleared_score)*100))+'%' : '';
            var onlName   = escapeHtml(item.onliner_name||'');
            var cands     = Array.isArray(item.candidates) ? item.candidates : [];

            html += '<div class="review-queue-item" data-rqi="'+idx+'" style="border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#fafaf9;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap;margin-bottom:10px;">';
            html += '<div style="font-size:13px;font-weight:700;color:#111827;flex:1;min-width:0;">'+ name +'</div>';
            html += '<button data-rqi-skip="'+idx+'" style="padding:4px 12px;font-size:11px;border:1px solid #d1d5db;border-radius:6px;background:#fff;cursor:pointer;color:#6b7280;white-space:nowrap;">Пропустить</button>';
            html += '</div>';

            if(cpuBrand || cpuModel){
                html += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">';
                if(cpuBrand){
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:#eef2ff;color:#4338ca;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;">Производитель: '+cpuBrand+'</span>';
                }
                if(cpuModel){
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:#f5f3ff;color:#6d28d9;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:700;font-family:monospace;">Модель: '+cpuModel+'</span>';
                }
                html += '</div>';
            }

            if(clearedId){
                html += '<div style="font-size:11px;color:#9ca3af;margin-bottom:8px;">Был ID: <span style="font-family:monospace;color:#dc2626;">'+clearedId+'</span>';
                if(clearedSc) html += ' <span style="color:#b45309;">(совпадение '+clearedSc+')</span>';
                if(onlName)   html += ' — Onliner: <em>'+onlName+'</em>';
                html += '</div>';
            }

            if(cands.length){
                cands = cands.slice().sort(function(a, b){
                    var pa = cpuCandidatePriority(item, a);
                    var pb = cpuCandidatePriority(item, b);
                    if(pa !== pb){ return pa - pb; }
                    var sa = Number((a && a.score) || 0);
                    var sb = Number((b && b.score) || 0);
                    if(sa !== sb){ return sb - sa; }
                    return String((a && a.name) || '').localeCompare(String((b && b.name) || ''), 'ru');
                });
                html += '<div style="font-size:11px;color:#374151;font-weight:600;margin-bottom:6px;">Кандидаты:</div>';
                html += '<div style="display:flex;flex-direction:column;gap:6px;">';
                cands.forEach(function(c, ci){
                    var cId    = escapeHtml(String(c.id||''));
                    var cName  = highlightCpuModelMatch(String(c.name||''), String(item.cpu_model||''));
                    var cSc    = c.score !== undefined ? Math.round(Number(c.score)*100) : 0;
                    var scCol  = cSc >= 90 ? '#15803d' : cSc >= 70 ? '#b45309' : '#dc2626';
                    var cUrl   = escapeHtml(String(c.url||''));
                    var tone   = cpuCandidateTone(item, c);
                    html += '<div style="display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px;">';
                    html += '<span style="background:#ede9fe;color:#5b21b6;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;font-family:monospace;white-space:nowrap;">'+cId+'</span>';
                    html += '<span style="flex:1;font-size:12px;color:#1f2937;">'+cName+'</span>';
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:'+tone.bg+';color:'+tone.color+';border:1px solid '+tone.border+';border-radius:999px;padding:2px 7px;font-size:10px;font-weight:700;white-space:nowrap;">'+escapeHtml(tone.label)+'</span>';
                    html += '<span style="font-size:11px;color:'+scCol+';font-weight:600;white-space:nowrap;">'+cSc+'%</span>';
                    if(cUrl){ html += '<a href="'+cUrl+'" target="_blank" style="font-size:11px;color:#6366f1;text-decoration:none;white-space:nowrap;">↗</a>'; }
                    html += '<button data-rqi-pick="'+idx+'" data-rqi-ci="'+ci+'" style="padding:4px 12px;font-size:11px;border:none;border-radius:6px;background:#6366f1;color:#fff;cursor:pointer;white-space:nowrap;">Выбрать</button>';
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html += '<div class="markup-note">Кандидатов не найдено — запустите автоподбор после валидации.</div>';
            }
            html += '</div>';
        });
        list.innerHTML = html;

        // Навешиваем обработчики один раз через делегирование
        list.onclick = function(e){
            var skipBtn = e.target.closest('[data-rqi-skip]');
            var pickBtn = e.target.closest('[data-rqi-pick]');
            if(skipBtn){
                var idx = Number(skipBtn.getAttribute('data-rqi-skip'));
                var item = _reviewQueueData[idx];
                if(item) _doReviewPick(item.name_key||'', '', '', '', item.name||'');
                var wrap = skipBtn.closest('[data-rqi]');
                if(wrap){ wrap.style.opacity='0.4'; wrap.style.pointerEvents='none'; }
            } else if(pickBtn){
                var idx = Number(pickBtn.getAttribute('data-rqi-pick'));
                var ci  = Number(pickBtn.getAttribute('data-rqi-ci'));
                var item = _reviewQueueData[idx];
                if(item){
                    var cand = (item.candidates||[])[ci] || {};
                    _doReviewPick(item.name_key||'', cand.id||'', cand.name||'', cand.url||'', item.name||'');
                    var wrap = pickBtn.closest('[data-rqi]');
                    if(wrap){ wrap.style.opacity='0.4'; wrap.style.pointerEvents='none'; }
                }
            }
        };
    }).catch(function(){
        var list = document.getElementById('review-queue-list');
        if(list) list.innerHTML = '<div class="markup-note" style="color:#dc2626;">Не удалось загрузить очередь.</div>';
    });
};

