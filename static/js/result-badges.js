function initNtechChecksBadges(){
    updateNtechCheckCategoryBadges(mainTableRows || []);
}

var NTECH_CHECK_KEYS = [
    'cpu', 'board', 'monitor', 'gpu', 'ram', 'ssd', 'psu', 'case', 'hdd', 'cooler', 'printer',
    'peripheral', 'usb', 'network', 'ups', 'keyboard', 'mouse', 'headphones',
    'audio', 'misc'
];

function isNtechSupplierName(value){
    var supplier = String(value || '').trim().toLowerCase();
    return supplier === 'n-tech' || supplier === 'ntech' || supplier === 'n tech';
}

function isIvenSupplierName(value){
    var supplier = String(value || '').trim().toLowerCase();
    return supplier === 'iven' || supplier === 'ивен';
}

function isIvenZakazSupplierName(value){
    var supplier = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return supplier === 'iven_zakaz' || supplier === 'ivenzakaz' || supplier === 'ивен_заказ';
}

function isTradexSupplierName(value){
    var supplier = String(value || '').trim().toLowerCase();
    return supplier === 'tradex' || supplier === 'традекс';
}

function isIvenPcName(value){
    var name = String(value || '').trim().toLowerCase();
    if(!name){ return false; }
    if((name.indexOf('iven') < 0 && name.indexOf('ивен') < 0)){ return false; }
    if(/^(компьютер|системный блок|пэвм)\s+/.test(name)){ return true; }
    return /\b(gaming|office|home|pro|ultra|superpower)\b/.test(name);
}

function isNtechPcName(value, category){
    var name = String(value || '').trim().toLowerCase();
    var cat = String(category || '').trim().toLowerCase();
    if(!name){ return false; }
    if(name.indexOf('только в составе пэвм') >= 0){ return false; }
    if(name.indexOf('пэвм') >= 0 && name.indexOf('tgpc') >= 0){ return true; }
    if((cat.indexOf('системный блок') >= 0 || cat.indexOf('компьютер') >= 0) && name.indexOf('tgpc') >= 0){ return true; }
    return false;
}

function isIvenLaptopName(value, category){
    var name = String(value || '').trim().toLowerCase();
    var cat = String(category || '').trim().toLowerCase();
    if(!name){ return false; }
    if(/\b(сумк\w*|чехл\w*|рюкзак\w*|подставк\w*|столик\w*|кулер\w*|охлаждающ\w*|заряд\w*|зарядн\w*|адаптер\w*|блок\s+питания|аккумулятор\w*|кабел\w*|матриц\w*|клавиатур\w*|петл\w*|рамк\w*|шлейф\w*|док[-\s]?станц\w*|докинг\w*|мыш\w*)\b/.test(name)){
        return false;
    }
    return /\b(ноутбук|laptop|notebook|ultrabook)\b/.test(name)
        || cat.indexOf('ноутбук') >= 0
        || cat.indexOf('laptop') >= 0
        || cat.indexOf('notebook') >= 0;
}

function isTradexLaptopName(value, category){
    return isIvenLaptopName(value, category);
}

function ntechCheckKeyForCategory(rawCategory, rawName){
    var c = String(rawCategory || '').trim().toLowerCase();
    var name = String(rawName || '').trim().toLowerCase();
    if(!c && !name){ return 'misc'; }
    if(c.indexOf('процессор') >= 0) return 'cpu';
    if(c.indexOf('материн') >= 0) return 'board';
    if(c.indexOf('монитор') >= 0) return 'monitor';
    if(c.indexOf('видеокарт') >= 0) return 'gpu';
    if(c.indexOf('оператив') >= 0 || c === 'ram') return 'ram';
    if(c === 'ssd') return 'ssd';
    if(c.indexOf('блок питания') >= 0 || c === 'бп' || c === 'psu') return 'psu';
    if(c.indexOf('корпус') >= 0) return 'case';
    if(c.indexOf('жестк') >= 0 || c === 'hdd') return 'hdd';
    if(c.indexOf('кулер') >= 0 || c.indexOf('охлажден') >= 0 || c.indexOf('охлаждение') >= 0) return 'cooler';
    if(c.indexOf('принтер') >= 0 || c.indexOf('мфу') >= 0 || c.indexOf('картридж') >= 0) return 'printer';
    if(c.indexOf('системный блок') >= 0 || c.indexOf('компьютер') >= 0 || name.indexOf('пэвм') >= 0 || name.indexOf('компьютер') >= 0) return '';
    if(c.indexOf('накопители usb') >= 0 || c === 'sdhc' || c === 'sdxc' || c.indexOf('картридер') >= 0) return 'usb';
    if(c.indexOf('кабел') >= 0 || c.indexOf('переход') >= 0 || c.indexOf('райзер') >= 0 || c.indexOf('коннектор') >= 0 || c.indexOf('заглуш') >= 0 || c.indexOf('рамка') >= 0) return 'misc';
    if(c === 'сеть' || c.indexOf('сетев') >= 0 || c === 'web') return 'network';
    if(c.indexOf('ибп') >= 0 || c.indexOf('аккумулятор') >= 0) return 'ups';
    if(c.indexOf('клавиат') >= 0) return 'keyboard';
    if(c.indexOf('мыш') >= 0 || c.indexOf('коврик') >= 0) return 'mouse';
    if(c.indexOf('науш') >= 0 || c.indexOf('гарнит') >= 0 || c.indexOf('микрофон') >= 0) return 'headphones';
    if(c.indexOf('акуст') >= 0 || c.indexOf('колон') >= 0) return 'audio';
    if(c.indexOf('перифер') >= 0) return 'peripheral';
    return 'misc';
}

function setNtechCheckBadge(key, count){
    var badge = document.getElementById(key + '-review-badge');
    if(!badge){ return; }
    var cnt = Number(count || 0);
    if(cnt > 0){
        badge.textContent = formatBadgeCount(cnt);
        badge.classList.add('active');
        var titlePrefix = 'Товаров N-Tech без ID: ';
        if(key === 'ntech-pc'){
            titlePrefix = 'N-Tech ПЭВМ без ID: ';
        } else if(key === 'iven-pc'){
            titlePrefix = 'IVEN ПЭВМ без ID: ';
        } else if(key === 'iven-laptop'){
            titlePrefix = 'Ноутбуки IVEN без ID: ';
        } else if(key === 'iven-zakaz-laptop'){
            titlePrefix = 'Ноутбуки IVEN_zakaz без ID: ';
        } else if(key === 'tradex-laptop'){
            titlePrefix = 'Ноутбуки Tradex без ID: ';
        }
        badge.title = titlePrefix + String(Math.round(cnt));
    } else {
        badge.textContent = '';
        badge.classList.remove('active');
        badge.removeAttribute('title');
    }
}

function updateNtechCheckCategoryBadges(rows){
    if(typeof mainTableServerSide !== 'undefined' && mainTableServerSide && mainTableBadgeCounts){
        applyNtechCheckBadgeCounts(mainTableBadgeCounts);
        return;
    }
    var counts = {};
    NTECH_CHECK_KEYS.forEach(function(key){ counts[key] = 0; });
    var total = 0;
    var ntechPcTotal = 0;
    var ivenPcTotal = 0;
    var ivenLaptopTotal = 0;
    var ivenZakazLaptopTotal = 0;
    var tradexLaptopTotal = 0;
    (Array.isArray(rows) ? rows : []).forEach(function(row){
        if(!Array.isArray(row)){ return; }
        if(String((row && row[0]) || '').trim()){ return; }
        if(isIvenSupplierName(row[3]) && isIvenPcName(row[1])){
            ivenPcTotal += 1;
            return;
        }
        if(isIvenSupplierName(row[3]) && isIvenLaptopName(row[1], row[9])){
            ivenLaptopTotal += 1;
            return;
        }
        if(isIvenZakazSupplierName(row[3]) && isIvenLaptopName(row[1], row[9])){
            ivenZakazLaptopTotal += 1;
            return;
        }
        if(isTradexSupplierName(row[3]) && isTradexLaptopName(row[1], row[9])){
            tradexLaptopTotal += 1;
            return;
        }
        if(!isNtechSupplierName(row[3])){ return; }
        if(isNtechPcName(row[1], row[9])){
            ntechPcTotal += 1;
            return;
        }
        var key = ntechCheckKeyForCategory(row[9], row[1]);
        if(!key){ return; }
        if(!counts.hasOwnProperty(key)){ key = 'misc'; }
        counts[key] += 1;
        total += 1;
    });
    NTECH_CHECK_KEYS.forEach(function(key){ setNtechCheckBadge(key, counts[key] || 0); });
    setNtechCheckBadge('ntech-pc', ntechPcTotal);
    setNtechCheckBadge('iven-pc', ivenPcTotal);
    setNtechCheckBadge('iven-laptop', ivenLaptopTotal);
    setNtechCheckBadge('iven-zakaz-laptop', ivenZakazLaptopTotal);
    setNtechCheckBadge('tradex-laptop', tradexLaptopTotal);
    var blockTotal = total + ntechPcTotal + ivenPcTotal + ivenLaptopTotal + ivenZakazLaptopTotal + tradexLaptopTotal;
    if(blockTotal > 0){
        setActionBadge('checks-block-badge', blockTotal, {
            title: 'Товары без ID для подбора в блоке проверок: {count}'
        });
    } else {
        setActionBadge('checks-block-badge', 0);
    }
}

function applyNtechCheckBadgeCounts(rawCounts){
    var counts = (rawCounts && typeof rawCounts === 'object') ? rawCounts : {};
    var total = 0;
    NTECH_CHECK_KEYS.forEach(function(key){
        var count = Number(counts[key] || 0);
        setNtechCheckBadge(key, count);
        total += count;
    });
    ['ntech-pc', 'iven-pc', 'iven-laptop', 'iven-zakaz-laptop', 'tradex-laptop'].forEach(function(key){
        var count = Number(counts[key] || 0);
        setNtechCheckBadge(key, count);
        total += count;
    });
    if(total > 0){
        setActionBadge('checks-block-badge', total, {
            title: 'Товары без ID для подбора в блоке проверок: {count}'
        });
    } else {
        setActionBadge('checks-block-badge', 0);
    }
}

function formatBadgeCount(value){
    var n = Number(value || 0);
    if(!isFinite(n) || n <= 0){ return ''; }
    if(n > 999){ return '999+'; }
    return String(Math.round(n));
}

function setActionBadge(badgeId, count, options){
    var badge = document.getElementById(badgeId);
    if(!badge){ return; }
    var n = Number(count || 0);
    if(!isFinite(n) || n <= 0){
        badge.textContent = '';
        badge.classList.remove('active');
        return;
    }
    var prefix = options && options.prefix ? String(options.prefix) : '';
    badge.textContent = prefix + formatBadgeCount(n);
    badge.classList.add('active');
    if(options && options.title){
        badge.title = String(options.title).replace('{count}', String(Math.round(n)));
    }
}

function initActionBadges(){
    refreshActionBadges();
}

function refreshActionBadges(){
    fetch('/api/stats?_ts=' + Date.now(), {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(s){
        if(!s){
            setActionBadge('quality-check-badge', 0);
            setActionBadge('checks-block-badge', 0);
            return;
        }
        updateStatsCounters(s);
        setActionBadge('quality-check-badge', s.quality_suspicious_price_count || 0, {
            title: 'Цены, где надо проверить или доприменить наценки: {count}'
        });
        var newNoIdCount = Number(s.new_without_id_count || 0);
        var idPickCount = Number(s.id_pick_badge_count || 0);
        setActionBadge('checks-block-badge', idPickCount, {
            prefix: newNoIdCount > 0 ? '+' : '',
            title: newNoIdCount > 0 ? 'Новые товары без ID для подбора: {count}' : 'Товары без ID для подбора: {count}'
        });
        if(Array.isArray(mainTableRows) && mainTableRows.length){
            updateNtechCheckCategoryBadges(mainTableRows);
        }
    }).catch(function(){
        setActionBadge('quality-check-badge', 0);
        setActionBadge('checks-block-badge', 0);
    });
}

function refreshQualityCheckBadge(){
    refreshActionBadges();
}
