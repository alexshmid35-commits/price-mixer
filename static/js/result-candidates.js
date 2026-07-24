function normalizeCompactMatch(text){
    return String(text || '').toLowerCase().replace(/[^a-zа-я0-9]+/g, '');
}

function normalizeTextForAiMatch(s){
    return String(s || '')
        .toLowerCase()
        .replace(/[^a-zа-я0-9\s\-\/]/gi, ' ')
            .replace(/\s+/g, ' ')
        .trim();
}

function tokenListForAiMatch(s){
    var stop = {
        'система':1,'охлаждения':1,'водяного':1,'для':1,'и':1,'the':1,'with':1,
        'black':1,'white':1,'черный':1,'чёрный':1,'белый':1,'argb':1,'rgb':1
    };
    return normalizeTextForAiMatch(s).split(' ').filter(function(t){
        return t && t.length >= 3 && !stop[t];
    });
}

function isAiTextMatch(localName, apiName){
    var lNorm = normalizeTextForAiMatch(localName);
    var aNorm = normalizeTextForAiMatch(apiName);
    if(!lNorm || !aNorm){ return false; }
    if(aNorm.length >= 12 && lNorm.indexOf(aNorm) >= 0){ return true; }
    var lTokens = tokenListForAiMatch(localName);
    var aTokens = tokenListForAiMatch(apiName);
    if(!lTokens.length || !aTokens.length){ return false; }
    var lSet = {};
    lTokens.forEach(function(t){ lSet[t] = 1; });
    var common = 0;
    aTokens.forEach(function(t){ if(lSet[t]){ common += 1; } });
    var overlap = common / Math.max(1, aTokens.length);
    return overlap >= 0.60 && common >= 2;
}

function extractInlineHighlightTokens(localName){
    var raw = String(localName || '');
    var lower = raw.toLowerCase();
    var tokens = {};
    var colorWords = ['black','white','blue','red','green','grey','gray','silver','gold','pink','purple','orange','черный','чёрный','белый','синий','голубой','красный','зеленый','зелёный','серый','серебристый','золотой','желтый','жёлтый','розовый'];
    colorWords.forEach(function(word){
        if(lower.indexOf(word) >= 0){
            tokens[normalizeCompactMatch(word)] = true;
        }
    });
    var capacities = String(raw).match(/\b\d+(?:[.,]\d+)?\s*(?:tb|gb)\b/gi) || [];
    capacities.forEach(function(token){
        tokens[normalizeCompactMatch(token)] = true;
    });
    var latinModelTokens = String(raw).match(/\b[A-Za-z][A-Za-z0-9-]{2,}\b/g) || [];
    latinModelTokens.forEach(function(token){
        if(/\d/.test(token) || token.length >= 5){
            tokens[normalizeCompactMatch(token)] = true;
        }
    });
    return tokens;
}

function highlightCandidateName(localName, candidateName){
    var text = String(candidateName || '');
    var needles = extractInlineHighlightTokens(localName);
    if(!text || !Object.keys(needles).length){
        return escapeHtml(text);
    }
    var parts = [];
    var lastIdx = 0;
    var re = /[A-Za-zА-Яа-яЁё0-9.,-]+/g;
    var match;
    while((match = re.exec(text)) !== null){
        var token = match[0];
        var normalized = normalizeCompactMatch(token);
        parts.push(escapeHtml(text.slice(lastIdx, match.index)));
        if(normalized && needles[normalized]){
            parts.push('<span class="noid-inline-hit">' + escapeHtml(token) + '</span>');
        } else {
            parts.push(escapeHtml(token));
        }
        lastIdx = match.index + token.length;
    }
    parts.push(escapeHtml(text.slice(lastIdx)));
    return parts.join('');
}

function renderCandidateBadges(item){
    var badges = [];
    var reason = String((item && item.reason) || '').trim();
    var scoreNum = Number((item && item.score) || 0);
    var score = isNaN(scoreNum) ? 0 : scoreNum;
    var name = String((item && item.name) || '');
    if(score >= 0.97){
        badges.push('точное');
    } else if(reason === 'model_token' || reason === 'paren_model' || score >= 0.84){
        badges.push('модель');
    } else if(reason === 'article_like' || reason === 'article'){
        badges.push('артикул');
    }
    if(/\((черный|чёрный|белый|зеленый|зелёный|розовый|синий|красный)\)/i.test(name)){
        badges.push('цвет');
    }
    if(/(?:^|[^a-z0-9])(?:xbox|playstation|usb)(?=$|[^a-z0-9])/i.test(name)){
        badges.push('версия');
    }
    if(!badges.length){ return ''; }
    return '<div class="noid-inline-badges">' + badges.map(function(b){
        return '<span class="noid-inline-badge">' + escapeHtml(b) + '</span>';
    }).join('') + '</div>';
}

function compactBrandModelQuery(name){
    var text = String(name || '').replace(/\([^)]*\)/g, ' ');
    text = text.replace(/[,"']/g, ' ');
    text = text.replace(/\s+/g, ' ').trim();
    if(!text){ return ''; }
    var generic = {
        'гарнитура':1,'наушники':1,'наушникисмикрофоном':1,'с':1,'микрофоном':1,'мониторные':1,
        'охватывающие':1,'геймерские':1,'кабель':1,'черный':1,'чёрный':1,'белый':1,'зеленый':1,
        'зелёный':1,'розовый':1,'накладные':1,'usb':1
    };
    var parts = text.split(/\s+/);
    var picked = [];
    for(var i = 0; i < parts.length; i++){
        var token = parts[i];
        var norm = normalizeCompactMatch(token);
        if(!norm || generic[norm]){ continue; }
        if(picked.length < 2){
            picked.push(token);
            continue;
        }
        if(/[A-Za-z]/.test(token) && /\d/.test(token)){
            picked.push(token);
            continue;
        }
        if(/^v\d+$/i.test(token) || /^[xvspro]+$/i.test(token) || /^h\d{3,4}$/i.test(token)){
            picked.push(token);
            continue;
        }
        if(picked.length >= 4){ break; }
    }
    return picked.slice(0, 5).join(' ').trim();
}

function bracketModelQuery(name){
    var text = String(name || '');
    if(!text){ return ''; }
    var generic = {
        'hdd':1,'ssd':1,'sata':1,'sataiii':1,'sataii':1,'nvme':1,'m2':1,'usb':1,'typec':1,
        'tb':1,'gb':1,'mb':1,'rpm':1
    };
    var brand = '';
    var words = text.replace(/[,"']/g, ' ').split(/\s+/);
    for(var i = 0; i < words.length; i++){
        var token = String(words[i] || '').trim();
        var norm = normalizeCompactMatch(token);
        if(!norm || generic[norm] || /\d/.test(token)){ continue; }
        if(/[A-Za-zА-Яа-я]/.test(token)){
            brand = token;
            break;
        }
    }
    var parts = text.match(/\(([^)]+)\)/g) || [];
    for(var j = 0; j < parts.length; j++){
        var inside = String(parts[j] || '').replace(/[()]/g, '').trim();
        var normInside = normalizeCompactMatch(inside);
        if(normInside.length < 5){ continue; }
        if(/[A-Za-z]/.test(inside) && /\d/.test(inside)){
            return brand ? (brand + ' ' + inside) : inside;
        }
    }
    return '';
}

function processorModelQuery(name){
    var text = String(name || '');
    if(!text){ return ''; }
    var patterns = [
        /(?:^|[^a-z0-9])(i[3579]-\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(pentium\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(celeron\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(athlon\s+\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i
    ];
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            return String(m[1]).replace(/\s+/g, ' ').trim();
        }
    }
    return '';
}

function fetchNoIdCandidates(payload){
    return fetch('/api/id-replace-candidates', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || {})
    }).then(function(r){ return r.json(); }).then(function(d){
        return Array.isArray(d && d.items) ? d.items : [];
    });
}
