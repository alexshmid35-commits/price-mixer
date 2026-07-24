function initOnlinerDbWidget(){
    var countEl  = document.getElementById('db-products-count');
    var detailEl = document.getElementById('db-stats-detail');
    var noteEl   = document.getElementById('db-stats-note');
    var searchInput = document.getElementById('db-search-query');
    var searchResults = document.getElementById('db-search-results');

    function loadDbStats(){
        fetch('/api/onliner-db-stats?_ts=' + Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(s){
            if(countEl) countEl.textContent = (s.total_products || 0).toLocaleString();
            var lines = [];
            lines.push((s.total_names || 0).toLocaleString() + ' вариантов названий');
            var src = s.by_source || {};
            Object.keys(src).slice(0,4).forEach(function(k){
                lines.push(k + ': ' + src[k].toLocaleString());
            });
            if(detailEl) detailEl.innerHTML = lines.join('<br>');
        }).catch(function(){ if(countEl) countEl.textContent = '?'; });
    }

    var importWrap = document.getElementById('db-import-progress-wrap');
    var importBar  = document.getElementById('db-import-progress-bar');
    var importMsg  = document.getElementById('db-import-msg');
    var importPollTimer = null;

    function stopImportPoll(){ if(importPollTimer){ clearInterval(importPollTimer); importPollTimer = null; } }

    function pollImportStatus(){
        fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var pct = parseInt(st.percent || 0);
            if(importBar)  importBar.style.width  = Math.max(2, pct) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            if(importWrap) importWrap.style.display = 'block';
            if(!st.running && st.finished_at){
                stopImportPoll();
                if(gsheetBtn){ gsheetBtn.disabled = false; gsheetBtn.textContent = '▶ Импорт GSheets'; }
                importBar && (importBar.style.background = st.message && st.message.indexOf('Ошибка') === 0
                    ? 'linear-gradient(90deg,#f87171,#dc2626)'
                    : 'linear-gradient(90deg,#0891b2,#0e7490)');
                loadDbStats();
            }
        }).catch(function(){});
    }

    // ── Google Sheets direct import ─────────────────────────────────────
    var gsheetBtn        = document.getElementById('db-gsheet-btn');

    if(gsheetBtn){
        gsheetBtn.addEventListener('click', function(){
            gsheetBtn.disabled = true;
            gsheetBtn.textContent = 'Загружаю настройки...';

            // Fetch settings first (result.html doesn't share uploadAppSettings from upload.html)
            fetch('/api/app-settings')
            .then(function(r){ return r.json(); })
            .then(function(d){
                var settings = (d && d.settings) || {};
                var dbImport = settings.onliner_db_import || {};
                var sid = String(dbImport.google_sheet_id || '').trim();
                var sname = String(dbImport.google_sheet_name || '').trim() || 'All_Catalog';
                if(!sid){
                    throw new Error('ID Google таблицы не настроен. Проверьте .env (ONLINER_DB_SHEET_NAME) или обратитесь к администратору.');
                }

                gsheetBtn.textContent = 'Скачиваю...';
                if(importWrap) importWrap.style.display = 'block';
                if(importBar)  importBar.style.width = '2%';
                if(importMsg)  importMsg.textContent  = 'Подключаюсь к Google Sheets…';

                return fetch('/api/onliner-db-import-gsheet', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({sheet_id: sid, sheet_name: sname, force_refresh: true})
                });
            })
            .then(function(r){ return r.json(); })
            .then(function(d){
                if(d.status !== 'started' && d.status !== 'already_running'){
                    throw new Error(d.message || 'start_failed');
                }
                gsheetBtn.textContent = 'Импортирую...';
                stopImportPoll();
                importPollTimer = setInterval(pollImportStatus, 1200);
                pollImportStatus();
            }).catch(function(e){
                gsheetBtn.disabled = false;
                gsheetBtn.textContent = '▶ Импорт GSheets';
                if(importMsg) importMsg.textContent = 'Ошибка: ' + (e.message || e);
            });
        });
    }

    function renderDbSearchResults(items, query){
        if(!searchResults) return;
        var rows = Array.isArray(items) ? items : [];
        if(!query){
            searchResults.style.display = 'none';
            searchResults.innerHTML = '';
            return;
        }
        searchResults.style.display = 'block';
        if(!rows.length){
            searchResults.innerHTML = '<div style="font-size:12px;color:#92400e;">По запросу <b>' + escapeHtml(query) + '</b> ничего не найдено.</div>';
            return;
        }
        var html = '<div style="font-size:12px;color:#92400e;font-weight:700;margin-bottom:6px;">Найдено: ' + rows.length + '</div>';
        rows.forEach(function(item){
            var oid = escapeHtml(String(item.id || ''));
            var name = escapeHtml(String(item.name || ''));
            var source = escapeHtml(String(item.source || 'db'));
            var url = String(item.url || '').trim();
            html += '<div style="padding:6px 0;border-top:1px dashed #fcd34d;">';
            html += '<div style="display:flex;gap:8px;align-items:flex-start;">';
            html += '<span style="display:inline-flex;align-items:center;gap:4px;background:#fff;color:#92400e;border:1px solid #fcd34d;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700;white-space:nowrap;">' + oid + '</span>';
            html += '<div style="flex:1;min-width:0;font-size:12px;color:#374151;line-height:1.35;">' + name + '<div style="margin-top:2px;font-size:11px;color:#a16207;">Источник: ' + source + '</div></div>';
            if(url){
                html += '<a href="' + escapeHtml(url) + '" target="_blank" style="font-size:11px;color:#2563eb;text-decoration:none;white-space:nowrap;">Открыть</a>';
            }
            html += '</div></div>';
        });
        searchResults.innerHTML = html;
    }

    function runDbSearch(queryOverride){
        var query = String(queryOverride !== undefined ? queryOverride : (searchInput ? searchInput.value : '')).trim();
        if(!query){
            renderDbSearchResults([], '');
            return;
        }
        if(searchResults){
            searchResults.style.display = 'block';
            searchResults.innerHTML = '<div style="font-size:12px;color:#92400e;">Ищу в локальной базе…</div>';
        }
        fetch('/api/onliner-db-search?q=' + encodeURIComponent(query) + '&_ts=' + Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(data){
            renderDbSearchResults((data && data.items) || [], query);
        }).catch(function(err){
            if(searchResults){
                searchResults.style.display = 'block';
                searchResults.innerHTML = '<div style="font-size:12px;color:#b91c1c;">Ошибка поиска: ' + escapeHtml(String((err && err.message) || err || 'unknown')) + '</div>';
            }
        }).finally(function(){
            if(searchBtn){ searchBtn.disabled = false; searchBtn.textContent = 'Найти в БД'; }
        });
    }

    // Live search with debounce
    var searchDebounceTimer = null;
    function liveSearchDb(query){
        if(searchDebounceTimer){ clearTimeout(searchDebounceTimer); }
        var q = String(query || '').trim();
        if(!q || q.length < 2){
            if(searchResults){ searchResults.style.display = 'none'; searchResults.innerHTML = ''; }
            return;
        }
        searchDebounceTimer = setTimeout(function(){
            runDbSearch(q);
        }, 350);
    }
    if(searchInput){
        searchInput.addEventListener('input', function(e){ liveSearchDb(e.target.value); });
        searchInput.addEventListener('keydown', function(e){
            if(e.key === 'Enter'){
                e.preventDefault();
                if(searchDebounceTimer){ clearTimeout(searchDebounceTimer); }
                runDbSearch(searchInput.value);
            }
        });
    }

    // Also re-enable gsheetBtn when import finishes (patch pollImportStatus)
    var _origPollImport = pollImportStatus;
    pollImportStatus = function(){
        fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
        .then(function(r){ return r.json(); })
        .then(function(st){
            var pct = parseInt(st.percent || 0);
            if(importBar)  importBar.style.width  = Math.max(2, pct) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            if(importWrap) importWrap.style.display = 'block';
            if(!st.running && st.finished_at){
                stopImportPoll();
                if(gsheetBtn){ gsheetBtn.disabled = false; gsheetBtn.textContent = '▶ Импорт GSheets'; }
                importBar && (importBar.style.background = st.message && st.message.indexOf('Ошибка') === 0
                    ? 'linear-gradient(90deg,#f87171,#dc2626)'
                    : 'linear-gradient(90deg,#0891b2,#0e7490)');
                loadDbStats();
            }
        }).catch(function(){});
    };

    // Resume poll if import was running before page load
    fetch('/api/onliner-db-import-status?_ts='+Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(st){
        if(st.running){
            if(typeof importBtn !== 'undefined' && importBtn){ importBtn.disabled = true; importBtn.textContent = 'Импортирую...'; }
            if(gsheetBtn){ gsheetBtn.disabled = true; gsheetBtn.textContent = 'Импортирую...'; }
            if(importWrap) importWrap.style.display = 'block';
            if(importBar)  importBar.style.width = Math.max(2, parseInt(st.percent||0)) + '%';
            if(importMsg)  importMsg.textContent  = st.message || '';
            stopImportPoll();
            importPollTimer = setInterval(pollImportStatus, 1200);
        } else if(st.finished_at && st.message){
            if(importWrap) importWrap.style.display = 'block';
            if(importMsg)  importMsg.textContent  = st.message;
            if(importBar)  importBar.style.width  = '100%';
        }
    }).catch(function(){});

    loadDbStats();
}
