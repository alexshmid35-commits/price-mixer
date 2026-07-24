// ============================================================
// ─── Проверка ID через API ────────────────────────────────────────────────
(function(){
    var startBtn    = document.getElementById('validate-ids-start-btn');
    var startDbBtn  = document.getElementById('validate-ids-db-start-btn');
    var cancelBtn   = document.getElementById('validate-ids-cancel-btn');
    var reportBtn   = document.getElementById('validate-ids-report-btn');
    var progressWrap= document.getElementById('validate-ids-progress-wrap');
    var progressBar = document.getElementById('validate-ids-progress-bar');
    var msgEl       = document.getElementById('validate-ids-msg');
    var modal       = document.getElementById('validate-ids-modal');
    var closeBtn1   = document.getElementById('validate-ids-modal-close');
    var closeBtn2   = document.getElementById('validate-ids-modal-close2');
    var tbody       = document.getElementById('validate-modal-tbody');
    var showConfEl  = document.getElementById('vld-show-confirmed');

    var vldStatus   = null;
    var pollTimer   = null;
    var activeValidateMode = 'api';

    function openModal(){ if(modal){ modal.style.display='block'; document.body.style.overflow='hidden'; } }
    function closeModal(){ if(modal){ modal.style.display='none'; document.body.style.overflow=''; } }
    if(closeBtn1) closeBtn1.addEventListener('click', closeModal);
    if(closeBtn2) closeBtn2.addEventListener('click', closeModal);
    if(modal) modal.addEventListener('click', function(e){ if(e.target===modal) closeModal(); });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeModal(); });

    function scoreBadge(sc){
        var bg = sc>=0.95?'#dcfce7':sc>=0.75?'#dbeafe':sc>=0.60?'#fef9c3':'#fee2e2';
        var col= sc>=0.95?'#166534':sc>=0.75?'#1d4ed8':sc>=0.60?'#92400e':'#b91c1c';
        return '<span style="display:inline-block;padding:2px 7px;border-radius:20px;font-weight:700;font-size:12px;background:'+bg+';color:'+col+';">'+(sc||'—')+'</span>';
    }

    function renderModal(){
        var st = vldStatus;
        if(!st || !tbody) return;
        var allRows   = (st.cleared_rows  || []);
        var confRows  = (st.confirmed_rows || []);
        var showConf  = showConfEl && showConfEl.checked;

        var el = function(id){ return document.getElementById(id); };
        var setTxt = function(id,v){ var e=el(id); if(e) e.textContent=v; };
        setTxt('vld-stat-checked',  (st.done||0));
        setTxt('vld-stat-confirmed',(st.confirmed||0));
        setTxt('vld-stat-cleared',  (st.cleared||0));
        setTxt('vld-stat-skipped',  (st.skipped_api||0));
        setTxt('vld-stat-errors',   (st.errors||0));
        var sub = el('validate-modal-subtitle');
        var modeLabel = st.mode_label || 'Onliner API';
        var skippedLabel = st.skipped_label || 'Пропуск = API не ответил, ID не меняли.';
        if(sub) sub.textContent = 'Режим: ' + modeLabel + '. Проверено: ' + (st.done||0) + ' из ' + (st.total||0) + ' товаров с ID (ПЭВМ TGPC пропущены). ' + skippedLabel;

        tbody.innerHTML = '';

        var skipRows = (st.skipped_rows || []);
        if(skipRows.length > 0){
            var hdrS = document.createElement('tr');
            hdrS.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fef9c3;color:#854d0e;font-size:12px;font-weight:700;border-top:2px solid #fde047;">Пропущено без изменений — ' + skipRows.length + ':</td>';
            tbody.appendChild(hdrS);
            skipRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#fefce8')+';border-bottom:1px solid #fef9c3;vertical-align:top;';
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td colspan="2" style="padding:7px 14px;color:#92400e;font-size:11px;">'+(r.reason||'api_unreachable')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#ca8a04;font-weight:700;font-size:12px;">— пропуск</span></td>';
                tbody.appendChild(tr);
            });
        }

        // Cleared / wrong IDs section
        if(allRows.length > 0){
            var hdr = document.createElement('tr');
            hdr.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#fee2e2;color:#991b1b;font-size:12px;font-weight:700;border-top:2px solid #fca5a5;">Очищено (неверный ID) — ' + allRows.length + ':</td>';
            tbody.appendChild(hdr);
            allRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#fff7f7')+';border-bottom:1px solid #fee2e2;vertical-align:top;';
                var sc = parseFloat(r.score)||0;
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#dc2626;text-decoration:line-through;font-size:11px;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td style="padding:7px 14px;color:#6b7280;font-size:12px;">'+(r.api_name||'—')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+scoreBadge(sc)+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#dc2626;font-weight:700;font-size:12px;">✗ Очищен</span></td>';
                tbody.appendChild(tr);
            });
        }

        // Confirmed section (optional)
        if(showConf && confRows.length > 0){
            var hdr2 = document.createElement('tr');
            hdr2.innerHTML = '<td colspan="5" style="padding:8px 14px;background:#dcfce7;color:#166534;font-size:12px;font-weight:700;border-top:2px solid #86efac;">Подтверждено — ' + confRows.length + ':</td>';
            tbody.appendChild(hdr2);
            confRows.forEach(function(r, i){
                var tr = document.createElement('tr');
                tr.style.cssText = 'background:'+(i%2===0?'#fff':'#f0fdf4')+';border-bottom:1px solid #dcfce7;vertical-align:top;';
                var sc = parseFloat(r.score)||0;
                var idCell = r.onliner_id
                    ? '<a href="https://catalog.onliner.by/p/'+r.onliner_id+'" target="_blank" style="color:#2563eb;font-size:11px;font-weight:600;">'+r.onliner_id+'</a>'
                    : '—';
                tr.innerHTML =
                    '<td style="padding:7px 14px;color:#1f2937;font-size:12px;max-width:240px;line-height:1.4;">'+(r.name||'')+'</td>'+
                    '<td style="padding:7px 14px;color:#374151;font-size:12px;">'+(r.api_name||'')+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+scoreBadge(sc)+'</td>'+
                    '<td style="padding:7px;text-align:center;">'+idCell+'</td>'+
                    '<td style="padding:7px;text-align:center;"><span style="color:#16a34a;font-weight:700;font-size:12px;">✓ Верно</span></td>';
                tbody.appendChild(tr);
            });
        }

        if(allRows.length === 0 && skipRows.length === 0 && (!showConf || confRows.length === 0)){
            var empty = document.createElement('tr');
            empty.innerHTML = '<td colspan="5" style="padding:20px;text-align:center;color:#9ca3af;font-size:13px;">'+(st.running?'Идёт проверка...':'Нет строк для отчёта (всё подтверждено или нет изменений)')+'</td>';
            tbody.appendChild(empty);
        }
    }

    if(showConfEl) showConfEl.addEventListener('change', renderModal);

    function stopPoll(){ if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; } }

    function pollValidate(){
        fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            vldStatus = st;
            var pct = st.total>0 ? Math.round((st.done||0)/st.total*100) : 0;
            if(progressBar) progressBar.style.width = pct + '%';
            if(msgEl) msgEl.textContent = st.message || '';
            if(st.running){
                if(progressWrap) progressWrap.style.display='block';
                if(startBtn){ startBtn.disabled=true; startBtn.textContent='Проверяю API...'; }
                if(startDbBtn){ startDbBtn.disabled=true; startDbBtn.textContent='Проверяю БД...'; }
                if(cancelBtn){
                    cancelBtn.style.display='inline-flex';
                    cancelBtn.disabled=!!st.cancel_requested;
                    cancelBtn.textContent=st.cancel_requested ? 'Останавливаю...' : '■ Прервать проверку';
                }
                pollTimer = setTimeout(pollValidate, 2000);
            } else {
                if(progressWrap) progressWrap.style.display='block';
                if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
                if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
                if(cancelBtn){
                    cancelBtn.style.display='none';
                    cancelBtn.disabled=false;
                    cancelBtn.textContent='■ Прервать проверку';
                }
                if(st.done > 0 && reportBtn){
                    reportBtn.style.display='inline-flex';
                    stopPoll();
                }
                // После валидации сервер уже перезаписал consolidated — перезагружаем таблицу,
                // иначе в DataTables остаются старые OnlinerID («очищен», а в таблице есть).
                if(st.finished_at && (Number(st.cleared||0) > 0 || Number(st.confirmed||0) > 0 || Number(st.skipped_api||0) > 0)){
                    if(typeof tblMain !== 'undefined' && tblMain && tblMain.ajax && typeof tblMain.ajax.reload === 'function'){
                        tblMain.ajax.reload(null, false);
                    }
                    fetch('/api/stats?_ts='+Date.now(), {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(s){
                        updateStatsCounters(s);
                        refreshActionBadges();
                    }).catch(function(){});
                }
            }
        }).catch(function(){ pollTimer = setTimeout(pollValidate, 4000); });
    }

    function launchValidate(mode){
        var isDb = mode === 'db';
        var btn = isDb ? startDbBtn : startBtn;
        var endpoint = isDb ? '/api/validate-clean-ids-db-start' : '/api/validate-clean-ids-start';
        if(!btn || btn.disabled) return;
        activeValidateMode = mode;
        btn.disabled = true;
        btn.textContent = 'Запускаю...';
        if(!isDb && startDbBtn){ startDbBtn.disabled = true; }
        if(isDb && startBtn){ startBtn.disabled = true; }
        if(progressWrap) progressWrap.style.display='block';
        if(progressBar) progressBar.style.width='0%';
        if(msgEl) msgEl.textContent = isDb ? 'Подготовка локальной сверки...' : 'Подготовка API-проверки...';
        if(reportBtn) reportBtn.style.display='none';
        if(cancelBtn){
            cancelBtn.style.display='inline-flex';
            cancelBtn.disabled=false;
            cancelBtn.textContent='■ Прервать проверку';
        }
        fetch(endpoint, {method:'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(d.status==='already_running' || d.status==='started'){
                stopPoll();
                pollValidate();
            } else {
                if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
                if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
                if(cancelBtn) cancelBtn.style.display='none';
                alert('Ошибка запуска: '+(d.message||d.status||'?'));
            }
        }).catch(function(err){
            if(startBtn){ startBtn.disabled=false; startBtn.textContent='🔍 Проверить ID'; }
            if(startDbBtn){ startDbBtn.disabled=false; startDbBtn.textContent='⚡ Проверить по БД'; }
            if(cancelBtn) cancelBtn.style.display='none';
            alert('Ошибка: '+err);
        });
    }

    if(cancelBtn){
        cancelBtn.addEventListener('click', function(){
            if(cancelBtn.disabled) return;
            cancelBtn.disabled = true;
            cancelBtn.textContent = 'Останавливаю...';
            if(msgEl) msgEl.textContent = 'Останавливаю проверку...';
            fetch('/api/validate-clean-ids-cancel', {method:'POST'})
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(d.status !== 'cancelling' && d.status !== 'not_running'){
                    throw new Error(d.message || d.status || 'cancel_failed');
                }
                stopPoll();
                pollValidate();
            }).catch(function(err){
                cancelBtn.disabled = false;
                cancelBtn.textContent = '■ Прервать проверку';
                if(msgEl) msgEl.textContent = 'Не удалось остановить проверку: ' + err;
            });
        });
    }

    if(startBtn){
        startBtn.addEventListener('click', function(){
            launchValidate('api');
        });
    }

    if(startDbBtn){
        startDbBtn.addEventListener('click', function(){
            launchValidate('db');
        });
    }

    if(reportBtn){
        reportBtn.addEventListener('click', function(){
            renderModal();
            openModal();
        });
    }

    // Check if validation was running on page load
    fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(st){
        vldStatus = st;
        if(st.running){
            if(progressWrap) progressWrap.style.display='block';
            if(startBtn){ startBtn.disabled=true; startBtn.textContent='Проверяю API...'; }
            if(startDbBtn){ startDbBtn.disabled=true; startDbBtn.textContent='Проверяю БД...'; }
            if(cancelBtn){
                cancelBtn.style.display='inline-flex';
                cancelBtn.disabled=!!st.cancel_requested;
                cancelBtn.textContent=st.cancel_requested ? 'Останавливаю...' : '■ Прервать проверку';
            }
            pollValidate();
        } else if(st.done > 0){
            if(progressWrap) progressWrap.style.display='block';
            if(progressBar) progressBar.style.width='100%';
            if(msgEl) msgEl.textContent = st.message || '';
            if(reportBtn) reportBtn.style.display='inline-flex';
            if(startBtn){ startBtn.textContent='🔍 Проверить ID'; }
            if(startDbBtn){ startDbBtn.textContent='⚡ Проверить по БД'; }
        }
    }).catch(function(){});
})();
// ============================================================
(function(){
    var validatePollTimer = null;
    var validateLabel = 'Запустить';

    function stopValidatePoll(){
        if(validatePollTimer){ clearInterval(validatePollTimer); validatePollTimer = null; }
    }

    function renderValidateChips(st){
        var chips = document.getElementById('validate-clean-chips');
        if(!chips) return;
        var confirmed = Number(st.confirmed||0);
        var cleared   = Number(st.cleared||0);
        var queued    = Number(st.queued||0);
        var errors    = Number(st.errors||0);
        var html = '';
        if(confirmed > 0) html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#dcfce7;color:#15803d;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✓ '+confirmed+' подтверждено</span>';
        if(cleared > 0)   html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fee2e2;color:#dc2626;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">✕ '+cleared+' очищено</span>';
        if(queued > 0)    html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#ede9fe;color:#5b21b6;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">⋯ '+queued+' в очереди</span>';
        if(errors > 0)    html += '<span style="display:inline-flex;align-items:center;gap:3px;background:#fef3c7;color:#b45309;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:600;">! '+errors+' ошибок</span>';
        chips.innerHTML = html;
        chips.style.display = html ? 'flex' : 'none';
    }

    function pollValidateStatus(){
        fetch('/api/validate-clean-ids-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var btn  = document.getElementById('run-validate-clean-btn');
            var note = document.getElementById('validate-clean-note');
            var bar  = document.getElementById('validate-clean-progress-bar');
            var wrap = document.getElementById('validate-clean-progress-wrap');
            var total = Number(st.total||0);
            var done  = Number(st.done||0);
            var pct   = total > 0 ? Math.round(done/total*100) : 0;
            if(wrap) wrap.style.display = 'block';
            if(bar)  bar.style.width = pct + '%';
            if(note && st.message) note.textContent = st.message;
            renderValidateChips(st);
            if(btn && st.running){
                var phase2 = st.message && String(st.message).indexOf('Фаза 2') === 0;
                btn.textContent = phase2 ? 'Кандидаты...' : ('Проверяю ' + pct + '%');
            }
            if(!st.running){
                stopValidatePoll();
                if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
                hideBusyOverlay();
                // Обновляем таблицу и счётчик
                if(st.finished_at && Number(st.cleared||0) > 0){
                    if(tblMain && typeof tblMain.ajax !== 'undefined'){
                        tblMain.ajax.reload(null, false);
                    } else {
                        fetch('/api/consolidated').then(function(r){ return r.json(); }).then(function(resp){
                            mainTableRows = (resp && resp.data) ? resp.data : [];
                            updateWithoutIdCount(mainTableRows);
                            updateNtechCheckCategoryBadges(mainTableRows);
                            renderMainTableFallback();
                        });
                    }
                }
                if(st.finished_at && Number(st.queued||0) > 0){
                    // Показываем кнопку очереди подсвеченной
                    var qBtn = document.getElementById('show-review-queue-btn');
                    if(qBtn) qBtn.style.background = '#ede9fe';
                    loadReviewQueue();
                }
                if(bar && st.finished_at){
                    bar.style.background = Number(st.cleared||0) > 0 ? 'linear-gradient(90deg,#f87171,#dc2626)' : 'linear-gradient(90deg,#6366f1,#4f46e5)';
                }
                runPreExportQualityCheck();
            } else {
                updateBusyOverlay('Валидация ID', st.message || ('Проверено ' + done + ' из ' + total + '...'));
            }
        }).catch(function(){
            stopValidatePoll();
            var btn = document.getElementById('run-validate-clean-btn');
            if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
            hideBusyOverlay();
        });
    }

    window.startValidateClean = function(){
        var btn = document.getElementById('run-validate-clean-btn');
        if(btn && btn.disabled) return;
        if(btn){ btn.disabled = true; btn.textContent = 'Проверяю 0%'; }
        var chips = document.getElementById('validate-clean-chips');
        if(chips){ chips.innerHTML = ''; chips.style.display = 'none'; }
        var bar = document.getElementById('validate-clean-progress-bar');
        var wrap = document.getElementById('validate-clean-progress-wrap');
        if(wrap) wrap.style.display = 'block';
        if(bar){ bar.style.width = '2%'; bar.style.background = 'linear-gradient(90deg,#6366f1,#4f46e5)'; }
        var note = document.getElementById('validate-clean-note');
        if(note) note.textContent = 'Запускаем валидацию...';
        showBusyOverlay('Валидация ID', 'Проверяем каждый OnlinerID по Onliner API...');
        fetch('/api/validate-clean-ids-start', {method:'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){
            if(!d || (d.status !== 'started' && d.status !== 'already_running')){
                throw new Error((d&&d.message)||'start_failed');
            }
            stopValidatePoll();
            validatePollTimer = setInterval(pollValidateStatus, 1500);
            pollValidateStatus();
        }).catch(function(err){
            if(btn){ btn.disabled = false; btn.textContent = validateLabel; }
            hideBusyOverlay();
            if(note) note.textContent = 'Не удалось запустить валидацию.';
        });
    };
})();
