
var dt = new DataTransfer();
var fileInput = document.getElementById('file-input');
var dropZone = document.getElementById('drop-zone');
var fileList = document.getElementById('file-list');
var actionsArea = document.getElementById('actions-area');

(function setupUploadSettingsUI(){
    var container = document.querySelector('.container');
    if(!container){ return; }
    var h1 = container.querySelector('h1');
    var subtitle = container.querySelector('.subtitle');
    if(h1 && subtitle && !container.querySelector('.upload-head')){
        var head = document.createElement('div');
        head.className = 'upload-head';
        var titleWrap = document.createElement('div');
        h1.parentNode.insertBefore(head, h1);
        titleWrap.appendChild(h1);
        titleWrap.appendChild(subtitle);
        head.appendChild(titleWrap);
        var actions = document.createElement('div');
        actions.className = 'upload-head-actions';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline';
        btn.id = 'open-settings-btn';
        btn.textContent = 'Настройки';
        actions.appendChild(btn);
        head.appendChild(actions);
    }

    if(!document.getElementById('settings-modal')){
        var modal = document.createElement('div');
        modal.id = 'settings-modal';
        modal.className = 'settings-modal';
        modal.innerHTML =
            '<div class="settings-sheet">' +
                '<div class="settings-head">' +
                    '<div class="settings-title">Настройки</div>' +
                    '<button type="button" class="btn btn-outline settings-close" id="close-settings-btn">Закрыть</button>' +
                '</div>' +
                '<div class="settings-card">' +
                    '<div class="settings-note">Здесь будут жить дополнительные настройки миксера.</div>' +
                    '<ul class="settings-list">' +
                        '<li>параметры поиска и проверки ID</li>' +
                        '<li>рабочие переключатели для отдельных поставщиков</li>' +
                        '<li>другие будущие опции, которые ты захочешь вынести отдельно</li>' +
                    '</ul>' +
                '</div>' +
            '</div>';
        document.body.appendChild(modal);
    }

    var settingsModal = document.getElementById('settings-modal');
    var openBtn = document.getElementById('open-settings-btn');
    var closeBtn = document.getElementById('close-settings-btn');
    if(openBtn && settingsModal){
        openBtn.addEventListener('click', function(){
            settingsModal.classList.add('active');
        });
    }
    if(closeBtn && settingsModal){
        closeBtn.addEventListener('click', function(){
            settingsModal.classList.remove('active');
        });
    }
    if(settingsModal){
        settingsModal.addEventListener('click', function(e){
            if(e.target && e.target.id === 'settings-modal'){
                settingsModal.classList.remove('active');
            }
        });
    }
})();

var uploadAppSettings = null;

(function enhanceUploadSettingsUI(){
    var settingsModal = document.getElementById('settings-modal');
    if(!settingsModal){ return; }
    settingsModal.innerHTML = `
        <div class="settings-sheet">
            <div class="settings-head">
                <div class="settings-title">Настройки</div>
                <button type="button" class="btn btn-outline settings-close" id="close-settings-btn">Закрыть</button>
            </div>
            <div class="settings-form">
                <div class="settings-section">
                    <h3>1. Выгрузка</h3>
                    <div class="settings-grid">
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-export-include-without-id"> Выгружать товары без ID</label></div>
                        <div class="settings-field"><label for="st-export-price-name">Имя выгружаемого прайса</label><input id="st-export-price-name" type="text" placeholder="consolidated_price"></div>
                        <div class="settings-field wide">
                            <label for="st-export-skip-duplicate-suppliers">Не включать в выгрузку товары с одинаковыми OnlinerID для поставщиков</label>
                            <textarea id="st-export-skip-duplicate-suppliers" spellcheck="false" placeholder="Например: TGPC"></textarea>
                            <div class="settings-help">По одному поставщику на строку. Если у поставщика один и тот же OnlinerID стоит у разных товаров, такие конфликтные строки не попадут в скачиваемый прайс.</div>
                        </div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>2. Кэш и API</h3>
                    <div class="settings-grid">
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-api-allow-direct"> Разрешить прямые запросы к Onliner</label></div>
                        <div class="settings-field"><label for="st-api-retry-attempts">Повторов запроса</label><input id="st-api-retry-attempts" type="number" min="1" max="12"></div>
                        <div class="settings-field"><label for="st-api-backoff-sec">Пауза между повторами, сек</label><input id="st-api-backoff-sec" type="number" min="0" max="5" step="0.1"></div>
                        <div class="settings-field"><label for="st-api-proxy-cooldown">Cooldown прокси, сек</label><input id="st-api-proxy-cooldown" type="number" min="10" max="3600"></div>
                        <div class="settings-field"><label for="st-api-max-workers">Параллельных запросов</label><input id="st-api-max-workers" type="number" min="1" max="24"></div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>3. Поставщики</h3>
                    <div class="settings-grid">
                        <div class="settings-field wide">
                            <label for="st-supplier-rules">Правила автоопределения поставщика по имени файла</label>
                            <textarea id="st-supplier-rules" spellcheck="false"></textarea>
                            <div class="settings-help">Каждая строка: часть_имени_файла=ИмяПоставщика
Пример:
price_bn=TGPC
tradex=Tradex
1374=BN-1374</div>
                        </div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>4. Источники API</h3>
                    <div class="settings-grid">
                        <div class="settings-field wide">
                            <label class="settings-checkbox"><input type="checkbox" id="st-src-iven-enabled"> IVEN активен</label>
                        </div>
                        <div class="settings-field"><label for="st-src-iven-supplier">Имя поставщика IVEN</label><input id="st-src-iven-supplier" type="text"></div>
                        <div class="settings-field"><label for="st-src-iven-url">URL файла IVEN</label><input id="st-src-iven-url" type="text" placeholder="https://...xlsx"></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-src-iven-verify-ssl"> Проверять SSL у IVEN</label></div>
                        <div class="settings-field wide">
                            <label class="settings-checkbox"><input type="checkbox" id="st-src-tradex-enabled"> Tradex активен</label>
                        </div>
                        <div class="settings-field"><label for="st-src-tradex-supplier">Имя поставщика Tradex</label><input id="st-src-tradex-supplier" type="text"></div>
                        <div class="settings-field"><label for="st-src-tradex-url">URL файла Tradex</label><input id="st-src-tradex-url" type="text" placeholder="https://...xlsx"></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-src-tradex-verify-ssl"> Проверять SSL у Tradex</label></div>
                        <div class="settings-field wide">
                            <label class="settings-checkbox"><input type="checkbox" id="st-src-ntech-enabled"> N-Tech активен</label>
                        </div>
                        <div class="settings-field"><label for="st-src-ntech-supplier">Имя поставщика N-Tech</label><input id="st-src-ntech-supplier" type="text"></div>
                        <div class="settings-field"><label for="st-src-ntech-auth-url">Auth URL N-Tech</label><input id="st-src-ntech-auth-url" type="text"></div>
                        <div class="settings-field"><label for="st-src-ntech-price-url">Price URL N-Tech</label><input id="st-src-ntech-price-url" type="text"></div>
                        <div class="settings-field"><label for="st-src-ntech-username">Логин N-Tech</label><input id="st-src-ntech-username" type="text"></div>
                        <div class="settings-field"><label for="st-src-ntech-password">Пароль N-Tech</label><input id="st-src-ntech-password" type="password"></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-src-ntech-verify-ssl"> Проверять SSL у N-Tech</label></div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>5. Подбор Без OnlinerID</h3>
                    <div class="settings-grid">
                        <div class="settings-field"><label for="st-noid-max-candidates">Кандидатов показывать</label><input id="st-noid-max-candidates" type="number" min="10" max="150"></div>
                        <div class="settings-field"><label for="st-noid-max-queries">Запросов на поиск</label><input id="st-noid-max-queries" type="number" min="1" max="8"></div>
                        <div class="settings-field"><label for="st-noid-tgpc-test-limit">Сколько TGPC ПЭВМ брать в тест</label><input id="st-noid-tgpc-test-limit" type="number" min="5" max="500"></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-prefer-paren-model"> Сначала учитывать модель в скобках</label></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-prefer-article"> Учитывать article-like токены и модели</label></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-include-brand"> Добавлять бренд в поисковые запросы</label></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-noid-require-category-hint"> Жестко фильтровать кандидатов по категории</label></div>
                        <div class="settings-field wide">
                            <label for="st-noid-category-rules">Правила по категориям и комплектующим</label>
                            <textarea id="st-noid-category-rules" spellcheck="false"></textarea>
                            <div class="settings-help">Это JSON по категориям. Поля:
query_hint - подсказка к запросу
must_contain - слова, которые желательно видеть в Onliner
ignore_words - слова, которые нужно занижать

Редактируй под свои категории.</div>
                        </div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>6. Очистка Uploads</h3>
                    <div class="settings-grid">
                        <div class="settings-field"><label for="st-cleanup-keep-sessions">Хранить последних сессий</label><input id="st-cleanup-keep-sessions" type="number" min="3" max="200"></div>
                        <div class="settings-field"><label for="st-cleanup-keep-days">Хранить сессии, дней</label><input id="st-cleanup-keep-days" type="number" min="1" max="90"></div>
                        <div class="settings-field"><label for="st-cleanup-keep-api-hours">Хранить временные API-файлы, часов</label><input id="st-cleanup-keep-api-hours" type="number" min="1" max="168"></div>
                        <div class="settings-help">Чистим только старые папки в uploads. Глобальные кэши, ручные ID, категории, наценки и сравнение с прошлой выгрузкой не трогаются.</div>
                    </div>
                </div>
                <div class="settings-section">
                    <h3>7. Проверка ID</h3>
                    <div class="settings-grid">
                        <div class="settings-field"><label for="st-verify-threshold">Порог совпадения названия</label><input id="st-verify-threshold" type="number" min="0.1" max="0.99" step="0.01"></div>
                        <div class="settings-field"><label for="st-verify-api-no-name-status">Если API не вернул название</label><select id="st-verify-api-no-name-status"><option value="review">Проверить</option><option value="mismatch">Несовпадение</option></select></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-trust-manual"> Ручное подтверждение считать абсолютным OK</label></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-force-refresh"> При проверке ID всегда заново ходить в API</label></div>
                        <div class="settings-field wide"><label class="settings-checkbox"><input type="checkbox" id="st-verify-require-priority"> Совпадением считать только article/model причины</label></div>
                    </div>
                </div>
                <div class="settings-actions">
                    <button type="button" class="btn btn-outline" id="reset-settings-btn">Сбросить</button>
                    <button type="button" class="btn" id="save-settings-btn">Сохранить настройки</button>
                </div>
                <div class="settings-note" id="settings-save-note"></div>
            </div>
        </div>`;

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
        var apiSources = uploadAppSettings.api_sources || {};
        var uploadsCleanup = uploadAppSettings.uploads_cleanup || {};
        var iven = apiSources.iven || {};
        var tradex = apiSources.tradex || {};
        var ntech = apiSources.ntech || {};
        var noId = uploadAppSettings.no_id_search || {};
        var verifyId = uploadAppSettings.verify_id || {};
        document.getElementById('st-export-include-without-id').checked = !!exportCfg.include_without_id;
        document.getElementById('st-export-price-name').value = exportCfg.price_name || 'consolidated_price';
        document.getElementById('st-export-skip-duplicate-suppliers').value = Array.isArray(exportCfg.exclude_duplicate_id_suppliers) ? exportCfg.exclude_duplicate_id_suppliers.join('
') : '';
        document.getElementById('st-api-allow-direct').checked = !!cacheApi.allow_direct;
        document.getElementById('st-api-retry-attempts').value = cacheApi.retry_attempts || 3;
        document.getElementById('st-api-backoff-sec').value = cacheApi.backoff_sec || 0.6;
        document.getElementById('st-api-proxy-cooldown').value = cacheApi.proxy_cooldown_sec || 180;
        document.getElementById('st-api-max-workers').value = cacheApi.max_parallel_workers || 10;
        document.getElementById('st-supplier-rules').value = rulesToText(suppliers.filename_rules || []);
        document.getElementById('st-src-iven-enabled').checked = !!iven.enabled;
        document.getElementById('st-src-iven-supplier').value = iven.supplier || 'IVEN';
        document.getElementById('st-src-iven-url').value = iven.file_url || '';
        document.getElementById('st-src-iven-verify-ssl').checked = !!iven.verify_ssl;
        document.getElementById('st-src-tradex-enabled').checked = !!tradex.enabled;
        document.getElementById('st-src-tradex-supplier').value = tradex.supplier || 'Tradex';
        document.getElementById('st-src-tradex-url').value = tradex.file_url || '';
        document.getElementById('st-src-tradex-verify-ssl').checked = !!tradex.verify_ssl;
        document.getElementById('st-src-ntech-enabled').checked = !!ntech.enabled;
        document.getElementById('st-src-ntech-supplier').value = ntech.supplier || 'N-Tech';
        document.getElementById('st-src-ntech-auth-url').value = ntech.auth_url || '';
        document.getElementById('st-src-ntech-price-url').value = ntech.price_url || '';
        document.getElementById('st-src-ntech-username').value = ntech.username || '';
        document.getElementById('st-src-ntech-password').value = ntech.password || '';
        document.getElementById('st-src-ntech-verify-ssl').checked = !!ntech.verify_ssl;
        document.getElementById('st-cleanup-keep-sessions').value = uploadsCleanup.keep_last_sessions || 20;
        document.getElementById('st-cleanup-keep-days').value = uploadsCleanup.keep_days || 7;
        document.getElementById('st-cleanup-keep-api-hours').value = uploadsCleanup.keep_api_fetch_hours || 12;
        document.getElementById('st-noid-max-candidates').value = noId.max_candidates || 80;
        document.getElementById('st-noid-max-queries').value = noId.max_queries || 4;
        document.getElementById('st-noid-tgpc-test-limit').value = noId.tgpc_pc_test_limit || 100;
        document.getElementById('st-noid-prefer-paren-model').checked = !!noId.prefer_paren_model;
        document.getElementById('st-noid-prefer-article').checked = !!noId.prefer_article_tokens;
        document.getElementById('st-noid-include-brand').checked = !!noId.include_brand_token;
        document.getElementById('st-noid-require-category-hint').checked = !!noId.require_category_hint;
        document.getElementById('st-noid-category-rules').value = noId.category_rules_text || '';
        document.getElementById('st-verify-threshold').value = verifyId.match_threshold || 0.74;
        document.getElementById('st-verify-api-no-name-status').value = verifyId.api_no_name_status || 'review';
        document.getElementById('st-verify-trust-manual').checked = !!verifyId.trust_manual_confirmed;
        document.getElementById('st-verify-force-refresh').checked = !!verifyId.force_refresh_api;
        document.getElementById('st-verify-require-priority').checked = !!verifyId.require_article_or_model_priority;
    }

    function collectSettingsForm(){
        return {
            export: {
                include_without_id: document.getElementById('st-export-include-without-id').checked,
                price_name: document.getElementById('st-export-price-name').value,
                exclude_duplicate_id_suppliers: String(document.getElementById('st-export-skip-duplicate-suppliers').value || '').split(/
?
/).map(function(v){
                    return String(v || '').trim();
                }).filter(Boolean)
            },
            cache_api: {
                allow_direct: document.getElementById('st-api-allow-direct').checked,
                retry_attempts: document.getElementById('st-api-retry-attempts').value,
                backoff_sec: document.getElementById('st-api-backoff-sec').value,
                proxy_cooldown_sec: document.getElementById('st-api-proxy-cooldown').value,
                max_parallel_workers: document.getElementById('st-api-max-workers').value
            },
            suppliers: {
                filename_rules: textToRules(document.getElementById('st-supplier-rules').value)
            },
            api_sources: {
                iven: {
                    enabled: document.getElementById('st-src-iven-enabled').checked,
                    supplier: document.getElementById('st-src-iven-supplier').value,
                    file_url: document.getElementById('st-src-iven-url').value,
                    verify_ssl: document.getElementById('st-src-iven-verify-ssl').checked
                },
                tradex: {
                    enabled: document.getElementById('st-src-tradex-enabled').checked,
                    supplier: document.getElementById('st-src-tradex-supplier').value,
                    file_url: document.getElementById('st-src-tradex-url').value,
                    verify_ssl: document.getElementById('st-src-tradex-verify-ssl').checked
                },
                ntech: {
                    enabled: document.getElementById('st-src-ntech-enabled').checked,
                    supplier: document.getElementById('st-src-ntech-supplier').value,
                    auth_url: document.getElementById('st-src-ntech-auth-url').value,
                    price_url: document.getElementById('st-src-ntech-price-url').value,
                    username: document.getElementById('st-src-ntech-username').value,
                    password: document.getElementById('st-src-ntech-password').value,
                    verify_ssl: document.getElementById('st-src-ntech-verify-ssl').checked
                }
            },
            uploads_cleanup: {
                keep_last_sessions: document.getElementById('st-cleanup-keep-sessions').value,
                keep_days: document.getElementById('st-cleanup-keep-days').value,
                keep_api_fetch_hours: document.getElementById('st-cleanup-keep-api-hours').value
            },
            no_id_search: {
                max_candidates: document.getElementById('st-noid-max-candidates').value,
                max_queries: document.getElementById('st-noid-max-queries').value,
                tgpc_pc_test_limit: document.getElementById('st-noid-tgpc-test-limit').value,
                prefer_paren_model: document.getElementById('st-noid-prefer-paren-model').checked,
                prefer_article_tokens: document.getElementById('st-noid-prefer-article').checked,
                include_brand_token: document.getElementById('st-noid-include-brand').checked,
                require_category_hint: document.getElementById('st-noid-require-category-hint').checked,
                category_rules_text: document.getElementById('st-noid-category-rules').value
            },
            verify_id: {
                match_threshold: document.getElementById('st-verify-threshold').value,
                api_no_name_status: document.getElementById('st-verify-api-no-name-status').value,
                trust_manual_confirmed: document.getElementById('st-verify-trust-manual').checked,
                force_refresh_api: document.getElementById('st-verify-force-refresh').checked,
                require_article_or_model_priority: document.getElementById('st-verify-require-priority').checked
            }
        };
    }

    function loadAppSettingsToModal(){
        var note = document.getElementById('settings-save-note');
        if(note){ note.textContent = 'Загрузка настроек...'; }
        fetch('/api/app-settings').then(function(r){ return r.json(); }).then(function(d){
            if(!d || d.status !== 'ok'){ throw new Error('load_failed'); }
            applySettingsToForm(d.settings || {});
            if(note){ note.textContent = ''; }
            updateFileList();
            loadApiSourceStatuses();
        }).catch(function(){
            if(note){ note.textContent = 'Не удалось загрузить настройки.'; }
        });
    }

    function saveAppSettingsFromModal(){
        var note = document.getElementById('settings-save-note');
        if(note){ note.textContent = 'Сохраняю настройки...'; }
        fetch('/api/app-settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(collectSettingsForm())
        }).then(function(r){ return r.json(); }).then(function(d){
            if(!d || d.status !== 'ok'){ throw new Error('save_failed'); }
            applySettingsToForm(d.settings || {});
            updateFileList();
            if(note){ note.textContent = 'Настройки сохранены.'; }
        }).catch(function(){
            if(note){ note.textContent = 'Не удалось сохранить настройки.'; }
        });
    }

    var openBtn = document.getElementById('open-settings-btn');
    var closeBtn = document.getElementById('close-settings-btn');
    if(openBtn){
        openBtn.onclick = function(){
            settingsModal.classList.add('active');
            loadAppSettingsToModal();
        };
    }
    if(closeBtn){
        closeBtn.onclick = function(){
            settingsModal.classList.remove('active');
        };
    }
    var saveBtn = document.getElementById('save-settings-btn');
    if(saveBtn){ saveBtn.onclick = saveAppSettingsFromModal; }
    var resetBtn = document.getElementById('reset-settings-btn');
    if(resetBtn){ resetBtn.onclick = loadAppSettingsToModal; }
    settingsModal.onclick = function(e){
        if(e.target && e.target.id === 'settings-modal'){
            settingsModal.classList.remove('active');
        }
    };
    loadAppSettingsToModal();
})();

var apiSourcePollTimer = null;
var apiSourceAutoProcessMap = {};
var busyOverlay = document.getElementById('busy-overlay');
var busyTitleEl = document.getElementById('busy-title');
var busyTextEl = document.getElementById('busy-text');
var busyStageTimer = null;
var busyStageMessages = [];
var busyStageIndex = 0;

function showBusyOverlay(title, text){
    if(busyTitleEl){ busyTitleEl.textContent = title || 'Обрабатываем прайс'; }
    if(busyTextEl){ busyTextEl.textContent = text || 'Это может занять несколько секунд. Окно не зависло, просто идёт обработка.'; }
    if(busyOverlay){ busyOverlay.classList.add('active'); }
}

function updateBusyOverlay(title, text){
    if(busyTitleEl && title){ busyTitleEl.textContent = title; }
    if(busyTextEl && text){ busyTextEl.textContent = text; }
}

function startBusyStageRotation(title, messages, intervalMs){
    if(busyStageTimer){
        window.clearInterval(busyStageTimer);
        busyStageTimer = null;
    }
    busyStageMessages = Array.isArray(messages) ? messages.slice() : [];
    busyStageIndex = 0;
    showBusyOverlay(title, busyStageMessages[0] || 'Идёт обработка...');
    if(busyStageMessages.length <= 1){ return; }
    busyStageTimer = window.setInterval(function(){
        busyStageIndex = (busyStageIndex + 1) % busyStageMessages.length;
        updateBusyOverlay(title, busyStageMessages[busyStageIndex]);
    }, intervalMs || 1800);
}

function hideBusyOverlay(){
    if(busyStageTimer){
        window.clearInterval(busyStageTimer);
        busyStageTimer = null;
    }
    busyStageMessages = [];
    busyStageIndex = 0;
    if(busyOverlay){ busyOverlay.classList.remove('active'); }
}

function sourceBadgeClass(state){
    if(!state || !state.enabled || !state.configured){ return 'api-source-badge disabled'; }
    if(state.status === 'error'){ return 'api-source-badge error'; }
    if(state.ready){ return 'api-source-badge ready'; }
    return 'api-source-badge';
}

function sourceBadgeText(state){
    if(!state || !state.enabled){ return 'Выключен'; }
    if(!state.configured){ return 'Не настроен'; }
    if(state.status === 'error'){ return 'Ошибка'; }
    if(state.ready){ return 'Готов'; }
    if(state.running){ return 'Выгрузка'; }
    return 'Ожидает';
}

function formatApiSourceTime(ts){
    var num = Number(ts || 0);
    if(!num){ return ''; }
    var d = new Date(num * 1000);
    if(!isFinite(d.getTime())){ return ''; }
    var dd = String(d.getDate()).padStart(2, '0');
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var yyyy = d.getFullYear();
    var hh = String(d.getHours()).padStart(2, '0');
    var mi = String(d.getMinutes()).padStart(2, '0');
    return dd + '.' + mm + '.' + yyyy + ' ' + hh + ':' + mi;
}

function formatHistorySize(bytes){
    var num = Number(bytes || 0);
    if(!num){ return '—'; }
    if(num >= 1024 * 1024){ return (num / (1024 * 1024)).toFixed(2) + ' MB'; }
    if(num >= 1024){ return (num / 1024).toFixed(1) + ' KB'; }
    return num.toLocaleString() + ' B';
}

function escapeHtml(text){
    return String(text == null ? '' : text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderApiHistory(items){
    var box = document.getElementById('api-history-list');
    if(!box){ return; }
    var rows = Array.isArray(items) ? items : [];
    if(!rows.length){
        box.innerHTML = '<div class="api-history-empty">История пока пустая.</div>';
        return;
    }
    box.innerHTML = rows.map(function(item){
        var whenText = formatApiSourceTime(item.finished_at || item.started_at);
        var typeText = item.event_type === 'process' ? 'Обработка' : 'Выгрузка';
        var statusClass = item.status === 'error' ? 'error' : (item.status === 'ok' ? 'ok' : 'run');
        var statusText = item.status === 'error' ? 'Ошибка' : (item.status === 'ok' ? 'Успех' : 'В работе');
        var details = [];
        if(item.file_size){ details.push('Файл: ' + formatHistorySize(item.file_size)); }
        if(item.duration_sec){ details.push('Время: ' + Number(item.duration_sec).toLocaleString() + ' сек'); }
        if(item.items_count){ details.push('Товаров: ' + Number(item.items_count).toLocaleString()); }
        if(item.without_id_count || item.without_id_count === 0){ details.push('Без ID: ' + Number(item.without_id_count).toLocaleString()); }
        var metaText = details.length ? details.join(' • ') : '—';
        var message = item.message || '';
        return '' +
            '<div class="api-history-row">' +
                '<div class="api-history-col"><strong>' + escapeHtml(item.label || item.source_key || 'Источник') + '</strong><div>' + escapeHtml(item.supplier || '') + '</div></div>' +
                '<div class="api-history-col">' + escapeHtml(typeText) + '</div>' +
                '<div class="api-history-col"><span class="api-history-status ' + statusClass + '">' + escapeHtml(statusText) + '</span></div>' +
                '<div class="api-history-col">' + escapeHtml(message || metaText) + (message && metaText !== '—' ? ('<div class="api-history-note">' + escapeHtml(metaText) + '</div>') : '') + '</div>' +
                '<div class="api-history-col">' + escapeHtml(whenText || '—') + '</div>' +
                '<div class="api-history-col">' + escapeHtml(item.file_name || '—') + '</div>' +
            '</div>';
    }).join('');
}

function renderApiSources(items){
    var grid = document.getElementById('api-sources-grid');
    if(!grid){ return; }
    var list = Array.isArray(items) ? items : [];
    if(list.length === 0){
        grid.innerHTML = '<div class="settings-note">Пока нет настроенных API-источников.</div>';
        return;
    }
    grid.innerHTML = list.map(function(item){
        var progress = Math.max(0, Math.min(100, Number(item.progress || 0)));
        var disabledFetch = (!item.enabled || !item.configured || item.running) ? 'disabled' : '';
        var disabledFetchProcess = (!item.enabled || !item.configured || item.running) ? 'disabled' : '';
        var disabledProcess = (!item.ready) ? 'disabled' : '';
        var autoLabel = apiSourceAutoProcessMap[item.source_key] ? 'Жду 100%' : 'Выгрузить и обработать';
        var totalText = item.total_bytes ? (' / ' + item.total_bytes.toLocaleString()) : '';
        var message = item.message || (item.ready ? 'Прайс готов к обработке.' : 'Нажми "Выгрузить", чтобы получить прайс.');
        var readyAt = item.ready ? formatApiSourceTime(item.finished_at) : '';
        var timeText = readyAt ? ('Последняя выгрузка: ' + readyAt) : '';
        var processBtnHtml = item.ready
            ? ('<button type="button" class="btn api-source-process" data-source="' + item.source_key + '" ' + disabledProcess + '>Обработать</button>')
            : '';
        return '' +
            '<div class="api-source-item" data-source="' + item.source_key + '">' +
                '<div class="api-source-title">' +
                    '<div><strong>' + item.label + '</strong><div class="api-source-supplier">Поставщик: ' + item.supplier + '</div></div>' +
                    '<span class="' + sourceBadgeClass(item) + '">' + sourceBadgeText(item) + '</span>' +
                '</div>' +
                '<div class="api-source-progress"><span style="width:' + progress + '%"></span></div>' +
                '<div class="api-source-meta"><span>' + progress + '%</span><span>' + Number(item.downloaded || 0).toLocaleString() + totalText + '</span></div>' +
                '<div class="api-source-message">' + message + '</div>' +
                '<div class="api-source-time">' + timeText + '</div>' +
                '<div class="api-source-actions">' +
                    '<button type="button" class="btn btn-outline api-source-fetch" data-source="' + item.source_key + '" ' + disabledFetch + '>Выгрузить</button>' +
                    '<button type="button" class="btn btn-outline api-source-fetch-process" data-source="' + item.source_key + '" ' + disabledFetchProcess + '>' + autoLabel + '</button>' +
                    processBtnHtml +
                '</div>' +
            '</div>';
    }).join('');
}

function scheduleApiSourcePoll(){
    if(apiSourcePollTimer){ window.clearTimeout(apiSourcePollTimer); }
    apiSourcePollTimer = window.setTimeout(loadApiSourceStatuses, 1500);
}

function loadApiSourceStatuses(){
    fetch('/api/source-fetch-status').then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){ throw new Error('status_failed'); }
        var items = Array.isArray(d.items) ? d.items : [];
        renderApiHistory(Array.isArray(d.history) ? d.history : []);
        items.forEach(function(it){
            if(apiSourceAutoProcessMap[it.source_key]){
                if(it.ready){
                    delete apiSourceAutoProcessMap[it.source_key];
                    processApiSource(it.source_key);
                } else if(it.status === 'error'){
                    delete apiSourceAutoProcessMap[it.source_key];
                    hideBusyOverlay();
                }
            }
        });
        var activeSource = null;
        items.forEach(function(it){
            if(!activeSource && (it.running || apiSourceAutoProcessMap[it.source_key])){ activeSource = it; }
        });
        if(activeSource && busyOverlay && busyOverlay.classList.contains('active')){
            var title = apiSourceAutoProcessMap[activeSource.source_key] ? 'Выгружаем и обрабатываем прайс' : 'Выгружаем прайс';
            var message = activeSource.message || 'Ждём ответ поставщика...';
            if(activeSource.status === 'starting'){
                message = activeSource.message || 'Подготавливаем запрос к поставщику...';
            } else if(activeSource.status === 'downloading'){
                if(Number(activeSource.total_bytes || 0) > 0){
                    message = 'Скачиваем файл: ' + Number(activeSource.downloaded || 0).toLocaleString() + ' / ' + Number(activeSource.total_bytes || 0).toLocaleString();
                } else {
                    message = activeSource.message || 'Скачиваем файл поставщика...';
                }
            }
            updateBusyOverlay(title, message);
        } else if(!Object.keys(apiSourceAutoProcessMap).length && busyOverlay && busyOverlay.classList.contains('active') && !busyStageTimer) {
            hideBusyOverlay();
        }
        renderApiSources(items);
        if(items.some(function(it){ return !!it.running; }) || Object.keys(apiSourceAutoProcessMap).length){
            scheduleApiSourcePoll();
        }
    }).catch(function(){
        hideBusyOverlay();
        renderApiSources([]);
    });
}

function startApiSourceFetch(sourceKey){
    showBusyOverlay('Выгружаем прайс', 'Подготавливаем запрос к поставщику...');
    fetch('/api/source-fetch-start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: sourceKey})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok'){ throw new Error((d && d.message) || 'fetch_failed'); }
        loadApiSourceStatuses();
        scheduleApiSourcePoll();
    }).catch(function(){
        hideBusyOverlay();
        loadApiSourceStatuses();
    });
}

function startApiSourceFetchAndProcess(sourceKey){
    var card = document.querySelector('.api-source-item[data-source="' + sourceKey + '"]');
    var processBtn = card ? card.querySelector('.api-source-process') : null;
    if(processBtn && !processBtn.disabled){
        showBusyOverlay('Обрабатываем прайс', 'Файл уже выгружен. Сейчас запускаем обработку и откроем результат.');
        processApiSource(sourceKey);
        return;
    }
    apiSourceAutoProcessMap[sourceKey] = true;
    showBusyOverlay('Выгружаем и обрабатываем прайс', 'Сначала получим файл у поставщика, потом автоматически запустим обработку.');
    startApiSourceFetch(sourceKey);
    scheduleApiSourcePoll();
}

function processApiSource(sourceKey){
    startBusyStageRotation('Обрабатываем прайс', [
        'Загружаем файл во внутренний конвейер...',
        'Парсим Excel и определяем колонки...',
        'Сводим товары и применяем сохранённые правила...',
        'Подготавливаем результат к открытию...'
    ], 1700);
    fetch('/api/source-process', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: sourceKey})
    }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || d.status !== 'ok' || !d.redirect_url){ throw new Error((d && d.message) || 'process_failed'); }
        window.location.href = d.redirect_url;
    }).catch(function(err){
        hideBusyOverlay();
        alert((err && err.message) ? err.message : 'Не удалось обработать прайс');
    });
}

document.addEventListener('click', function(e){
    var fetchBtn = e.target && e.target.closest ? e.target.closest('.api-source-fetch') : null;
    if(fetchBtn){
        startApiSourceFetch(fetchBtn.dataset.source);
        return;
    }
    var processBtn = e.target && e.target.closest ? e.target.closest('.api-source-process') : null;
    if(processBtn){
        processApiSource(processBtn.dataset.source);
        return;
    }
    var fetchProcessBtn = e.target && e.target.closest ? e.target.closest('.api-source-fetch-process') : null;
    if(fetchProcessBtn){
        startApiSourceFetchAndProcess(fetchProcessBtn.dataset.source);
    }
});

function detectSupplier(fname) {
    var fl = fname.toLowerCase();
    var supplierRules = (((uploadAppSettings || {}).suppliers || {}).filename_rules || []);
    for (var r = 0; r < supplierRules.length; r++) {
        var rule = supplierRules[r] || {};
        var pattern = String(rule.pattern || '').toLowerCase().trim();
        var supplier = String(rule.supplier || '').trim();
        if (pattern && supplier && fl.indexOf(pattern) >= 0) return supplier;
    }
    if (fl.indexOf('tradex') >= 0) return 'Tradex';
    if (fl.indexOf('1030z') >= 0) return 'BN-1030Z';
    if (fl.indexOf('1030') >= 0) return 'BN-1030';
    if (fl.indexOf('1374') >= 0) return 'BN-1374';
    if (fl.indexOf('price_bn') >= 0) return 'TGPC';
    return '';
}

function updateFileList() {
    fileList.innerHTML = '';
    if (dt.files.length === 0) {
        dropZone.classList.remove('has-files');
        actionsArea.style.display = 'none';
        fileInput.value = '';
        return;
    }
    dropZone.classList.add('has-files');
    actionsArea.style.display = 'block';
    
    var fileNames = [];
    for (var i = 0; i < dt.files.length; i++) {
        var f = dt.files[i];
        var detected = detectSupplier(f.name);
        var div = document.createElement('div');
        div.className = 'file-item';
        div.innerHTML = '<span class="fname" data-fname="' + f.name + '">' + f.name + '</span>' +
            '<input type="text" class="supplier-input" data-fname="' + f.name + '" value="' + detected + '" placeholder="Имя поставщика">' +
            '<span class="remove" data-fname="'+f.name+'">&times;</span>';
        fileList.appendChild(div);
        fileNames.push(f.name);
    }
    
    document.querySelectorAll('.remove').forEach(function(el){
        el.addEventListener('click', function(e){
            e.stopPropagation();
            var fname = this.dataset.fname;
            var newDt = new DataTransfer();
            for(var j=0; j<dt.files.length; j++){
                if(dt.files[j].name !== fname) newDt.items.add(dt.files[j]);
            }
            dt = newDt;
            updateFileList();
        });
    });
}

fileInput.addEventListener('change', function(){
    for(var i=0; i<this.files.length; i++) dt.items.add(this.files[i]);
    updateFileList();
});

dropZone.addEventListener('click', function(){ fileInput.click(); });
dropZone.addEventListener('dragover', function(e){ e.preventDefault(); this.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', function(e){ this.classList.remove('drag-over'); });
dropZone.addEventListener('drop', function(e){
    e.preventDefault(); this.classList.remove('drag-over');
    for(var i=0; i<e.dataTransfer.files.length; i++) dt.items.add(e.dataTransfer.files[i]);
    updateFileList();
});

document.getElementById('upload-form').addEventListener('submit', function(e){
    var inputs = document.querySelectorAll('.supplier-input');
    for(var i=0; i<inputs.length; i++){
        var inp = inputs[i];
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'supplier_' + encodeURIComponent(inp.dataset.fname);
        hidden.value = inp.value;
        this.appendChild(hidden);
    }
    
    fileInput.files = dt.files;
    
    document.getElementById('submit-btn').disabled = true;
document.getElementById('spinner').classList.add('active');
    startBusyStageRotation('Обрабатываем прайсы', [
        'Загружаем файлы и проверяем структуру...',
        'Парсим Excel и определяем рабочие колонки...',
        'Сводим товары и подставляем найденные ID...',
        'Применяем категории и наценки...',
        'Подготавливаем результат к открытию...'
    ], 1800);
});
