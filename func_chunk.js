    var settingsModal = document.getElementById('settings-modal');
    if(!settingsModal){ return; }
    settingsModal.innerHTML =
        '<div class="settings-sheet">' +
            '<div class="settings-head">' +
                '<div class="settings-title">Настройки</div>' +
                '<button type="button" class="btn btn-outline settings-close" id="close-settings-btn">Закрыть</button>' +
            '</div>' +
            '<div class="settings-form">' +
                '<div class="settings-section"><h3>1. Выгрузка</h3><div class="settings-grid">' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-export-include-without-id"> Выгружать товары без ID</label></div>' +
                    '<div class="settings-field"><label for="st-export-price-name">Имя выгружаемого прайса</label><input id="st-export-price-name" type="text" placeholder="consolidated_price"></div>' +
                '</div></div>' +
                '<div class="settings-section"><h3>2. Кэш и API</h3><div class="settings-grid">' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-api-allow-direct"> Разрешить прямые запросы к Onliner</label></div>' +
                    '<div class="settings-field"><label for="st-api-retry-attempts">Повторов запроса</label><input id="st-api-retry-attempts" type="number" min="1" max="12"></div>' +
                    '<div class="settings-field"><label for="st-api-backoff-sec">Пауза между повторами, сек</label><input id="st-api-backoff-sec" type="number" min="0" max="5" step="0.1"></div>' +
                    '<div class="settings-field"><label for="st-api-proxy-cooldown">Cooldown прокси, сек</label><input id="st-api-proxy-cooldown" type="number" min="10" max="3600"></div>' +
                    '<div class="settings-field"><label for="st-api-max-workers">Параллельных запросов</label><input id="st-api-max-workers" type="number" min="1" max="24"></div>' +
                '</div></div>' +
                '<div class="settings-section"><h3>3. Поставщики</h3><div class="settings-grid">' +
                    '<div class="settings-field wide"><label for="st-supplier-rules">?????????????? ?????????????????????????????? ???????????????????? ???? ?????????? ??????????</label><textarea id="st-supplier-rules" spellcheck="false"></textarea><div class="settings-help">???????????? ????????????: ??????????_??????????_??????????=??????????????????????????\n????????????:\nprice_bn=TGPC\ntradex=Tradex\n1374=BN-1374</div></div>' +
                '</div></div>' +
                '<div class="settings-section"><h3>4. Подбор Без OnlinerID</h3><div class="settings-grid">' +
                    '<div class="settings-field"><label for="st-noid-max-candidates">Кандидатов показывать</label><input id="st-noid-max-candidates" type="number" min="10" max="150"></div>' +
                    '<div class="settings-field"><label for="st-noid-max-queries">Запросов на поиск</label><input id="st-noid-max-queries" type="number" min="1" max="8"></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-prefer-paren-model"> Сначала учитывать модель в скобках</label></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-prefer-article"> Учитывать article-like токены и модели</label></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-include-brand"> Добавлять бренд в поисковые запросы</label></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-require-category-hint"> Жёстко фильтровать кандидатов по категории</label></div>' +
                    '<div class="settings-field wide"><label for="st-noid-category-rules">?????????????? ???? ???????????????????? ?? ??????????????????????????</label><textarea id="st-noid-category-rules" spellcheck="false"></textarea><div class="settings-help">?????? JSON ???? ????????????????????. ????????:\nquery_hint ??? ?????????????????? ?? ??????????????\nmust_contain ??? ??????????, ?????????????? ???????????????????? ???????????? ?? Onliner\nignore_words ??? ??????????, ?????????????? ?????????? ????????????????\n\n???????????????????? ?????? ???????? ??????????????????.</div></div>' +
                '</div></div>' +
                '<div class="settings-section"><h3>5. Проверка ID</h3><div class="settings-grid">' +
                    '<div class="settings-field"><label for="st-verify-threshold">Порог совпадения названия</label><input id="st-verify-threshold" type="number" min="0.1" max="0.99" step="0.01"></div>' +
                    '<div class="settings-field"><label for="st-verify-api-no-name-status">Если API не вернул название</label><select id="st-verify-api-no-name-status"><option value="review">Проверить</option><option value="mismatch">Несовпадение</option></select></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-trust-manual"> Ручное подтверждение считать абсолютным OK</label></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-force-refresh"> При проверке ID всегда заново ходить в API</label></div>' +
                    '<div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-require-priority"> Совпадением считать только article/model причины</label></div>' +
                '</div></div>' +
                '<div class="settings-actions">' +
                    '<button type="button" class="btn btn-outline" id="reset-settings-btn">Сбросить</button>' +
                    '<button type="button" class="btn" id="save-settings-btn">Сохранить настройки</button>' +
                '</div>' +
                '<div class="settings-note" id="settings-save-note"></div>' +
            '</div>' +
        '</div>';

    function rulesToText(rules){
        if(!Array.isArray(rules)){ return ''; }
        return rules.map(function(it){
            return String((it && it.pattern) || '').trim() + '=' + String((it && it.supplier) || '').trim();
        }).filter(Boolean).join('\n');
    }

    function textToRules(text){
        return String(text || '').split(/\r?\n/).map(function(line){
            var raw = String(line || '').trim();
            if(!raw || raw.indexOf('=') < 0){ return null; }
            var parts = raw.split('=');
            var pattern = String(parts.shift() || '').trim();
            var supplier = String(parts.join('=') || '').trim();
            if(!pattern || !supplier){ return null; }
            return {pattern: pattern, supplier: supplier};
        }).filter(Boolean);
    }

    function applySettingsToForm(settings){
        uploadAppSettings = settings || {};
        var exportCfg = uploadAppSettings.export || {};
        var cacheApi = uploadAppSettings.cache_api || {};
        var suppliers = uploadAppSettings.suppliers || {};
        var noId = uploadAppSettings.no_id_search || {};
        var verifyId = uploadAppSettings.verify_id || {};
        document.getElementById('st-export-include-without-id').checked = !!exportCfg.include_without_id;
        document.getElementById('st-export-price-name').value = exportCfg.price_name || 'consolidated_price';
        document.getElementById('st-api-allow-direct').checked = !!cacheApi.allow_direct;
        document.getElementById('st-api-retry-attempts').value = cacheApi.retry_attempts || 3;
        document.getElementById('st-api-backoff-sec').value = cacheApi.backoff_sec || 0.6;
        document.getElementById('st-api-proxy-cooldown').value = cacheApi.proxy_cooldown_sec || 180;
        document.getElementById('st-api-max-workers').value = cacheApi.max_parallel_workers || 10;
        document.getElementById('st-supplier-rules').value = rulesToText(suppliers.filename_rules || []);
        document.getElementById('st-noid-max-candidates').value = noId.max_candidates || 80;