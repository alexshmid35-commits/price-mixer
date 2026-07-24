(function(){
    'use strict';

    var profiles = {
        ntech: {
            label: 'N-Tech ПЭВМ',
            startUrl: '/api/autofill-ntech-pc-ids',
            statusUrl: '/api/autofill-ntech-pc-status',
            buttonId: 'autofill-ntech-pc-btn'
        },
        iven: {
            label: 'IVEN ПЭВМ',
            startUrl: '/api/autofill-iven-pc-ids',
            statusUrl: '/api/autofill-iven-pc-status',
            buttonId: 'autofill-iven-pc-btn'
        }
    };
    var active = false;

    function byId(id){
        return document.getElementById(id);
    }

    function requestJson(url, options){
        return fetch(url, options || {cache: 'no-store'}).then(function(response){
            return response.json().catch(function(){ return {}; }).then(function(payload){
                if(!response.ok){
                    throw new Error(payload.message || ('HTTP ' + response.status));
                }
                return payload;
            });
        });
    }

    function setButtonsDisabled(disabled){
        Object.keys(profiles).forEach(function(key){
            var button = byId(profiles[key].buttonId);
            if(button){ button.disabled = !!disabled; }
        });
        var allButton = byId('run-all-pevm-checks-btn');
        if(allButton){ allButton.disabled = !!disabled; }
    }

    function setProgress(percent, running){
        var wrap = byId('pevm-autofill-progress');
        var value = byId('pevm-autofill-progress-value');
        if(!wrap || !value){ return; }
        wrap.style.display = 'block';
        value.style.width = Math.max(0, Math.min(100, Number(percent || 0))) + '%';
        value.style.background = running ? '#2563eb' : '#16a34a';
    }

    function setStatus(text, isError){
        var status = byId('pevm-autofill-status');
        if(!status){ return; }
        status.textContent = text || '';
        status.style.color = isError ? '#b91c1c' : '#6b7280';
    }

    function renderResult(profile, status){
        var host = byId('pevm-autofill-results');
        if(!host){ return; }
        var matched = Number(status.applied || 0);
        var skipped = Number(status.skipped || 0);
        var total = Number(status.total || 0);
        host.style.display = 'block';
        host.textContent = profile.label + ': подставлено ' + matched +
            ' из ' + total + ', оставлено на ручную проверку ' + skipped + '.';
    }

    function refreshTableAndBadges(){
        if(typeof tblMain !== 'undefined' && tblMain && tblMain.ajax &&
                typeof tblMain.ajax.reload === 'function'){
            tblMain.ajax.reload(null, false);
        }
        if(typeof refreshActionBadges === 'function'){
            window.setTimeout(refreshActionBadges, 200);
        }
    }

    function waitForCompletion(profile){
        return new Promise(function(resolve, reject){
            var attempts = 0;
            function poll(){
                attempts += 1;
                requestJson(profile.statusUrl + '?_ts=' + Date.now(), {cache: 'no-store'})
                    .then(function(status){
                        var percent = Number(status.percent || 0);
                        setProgress(percent, !!status.running);
                        setStatus(status.message || (
                            'Обработано ' + Number(status.done || 0) +
                            ' из ' + Number(status.total || 0)
                        ));
                        if(status.running){
                            window.setTimeout(poll, 900);
                            return;
                        }
                        if(status.finished_at){
                            renderResult(profile, status);
                            resolve(status);
                            return;
                        }
                        if(attempts > 20){
                            reject(new Error('Сервер не подтвердил запуск проверки.'));
                            return;
                        }
                        window.setTimeout(poll, 500);
                    })
                    .catch(reject);
            }
            poll();
        });
    }

    function runProfile(key, manageBusyState){
        var profile = profiles[key];
        if(!profile){ return Promise.reject(new Error('Неизвестный профиль ПЭВМ.')); }
        if(manageBusyState){
            active = true;
            setButtonsDisabled(true);
        }
        setStatus('Запускаю ' + profile.label + '...');
        setProgress(2, true);
        return requestJson(profile.startUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}'
        }).then(function(payload){
            if(payload.status !== 'started' && payload.status !== 'already_running'){
                throw new Error(payload.message || 'Не удалось запустить проверку.');
            }
            return waitForCompletion(profile);
        }).then(function(status){
            refreshTableAndBadges();
            return status;
        }).catch(function(error){
            setStatus(profile.label + ': ' + error.message, true);
            throw error;
        }).finally(function(){
            if(manageBusyState){
                active = false;
                setButtonsDisabled(false);
            }
        });
    }

    function runAll(){
        if(active){ return; }
        active = true;
        setButtonsDisabled(true);
        var completed = 0;
        ['ntech', 'iven'].reduce(function(chain, key){
            return chain.then(function(){
                setStatus('Проверка ' + (completed + 1) + ' из 2: ' + profiles[key].label);
                return runProfile(key, false).then(function(){
                    completed += 1;
                });
            });
        }, Promise.resolve()).then(function(){
            setProgress(100, false);
            setStatus('Обе проверки ПЭВМ завершены.');
        }).catch(function(error){
            setStatus('Проверки остановлены: ' + error.message, true);
        }).finally(function(){
            active = false;
            setButtonsDisabled(false);
            refreshTableAndBadges();
        });
    }

    document.addEventListener('DOMContentLoaded', function(){
        Object.keys(profiles).forEach(function(key){
            var button = byId(profiles[key].buttonId);
            if(button){
                button.addEventListener('click', function(){
                    if(active){ return; }
                    runProfile(key, true).catch(function(){});
                });
            }
        });
        var allButton = byId('run-all-pevm-checks-btn');
        if(allButton){ allButton.addEventListener('click', runAll); }
    });
})();
