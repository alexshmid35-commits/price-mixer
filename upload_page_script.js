
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
                    <h3>4. Подбор Без OnlinerID</h3>
                    <div class="settings-grid">
                        <div class="settings-field"><label for="st-noid-max-candidates">Кандидатов показывать</label><input id="st-noid-max-candidates" type="number" min="10" max="150"></div>
                        <div class="settings-field"><label for="st-noid-max-queries">Запросов на поиск</label><input id="st-noid-max-queries" type="number" min="1" max="8"></div>
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
                    <h3>5. Проверка ID</h3>
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
        document.getElementById('st-noid-max-queries').value = noId.max_queries || 4;
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
                price_name: document.getElementById('st-export-price-name').value
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
            no_id_search: {
                max_candidates: document.getElementById('st-noid-max-candidates').value,
                max_queries: document.getElementById('st-noid-max-queries').value,
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
});
