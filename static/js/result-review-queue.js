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
    var lowerText = text.toLowerCase();
    for(var i = 0; i < patterns.length; i++){
        var raw = String(patterns[i] || '');
        if(!raw){ continue; }
        var idx = lowerText.indexOf(raw.toLowerCase());
        if(idx >= 0){
            var before = escapeHtml(text.slice(0, idx));
            var hit = escapeHtml(text.slice(idx, idx + raw.length));
            var after = escapeHtml(text.slice(idx + raw.length));
            return before + '<span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 4px;font-weight:700;">' + hit + '</span>' + after;
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
        /(?:^|[^a-z0-9])(i[3579]-\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(pentium\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(celeron\s+[a-z]?\d{4,5})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(athlon\s+\d{4,5}[a-z]{0,2})(?=$|[^a-z0-9])/i,
        /(?:^|[^a-z0-9])(xeon\s+[ew]?-?\d{1,2}-?\d{4,5}\s*v?\d?)(?=$|[^a-z0-9])/i
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

function parseBoardBrandModel(candidateName){
    var text = String(candidateName || '');
    var low = text.toLowerCase();
    var brand = '';
    if(/(?:^|[^a-z0-9])asrock(?=$|[^a-z0-9])/i.test(low)){ brand = 'ASROCK'; }
    else if(/(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])/i.test(low)){ brand = 'GIGABYTE'; }
    else if(/(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])/i.test(low)){ brand = 'ASUS'; }
    else if(/(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])/i.test(low)){ brand = 'MSI'; }
    else if(/(?:^|[^a-z0-9])biostar(?=$|[^a-z0-9])/i.test(low)){ brand = 'BIOSTAR'; }
    else if(/(?:^|[^a-z0-9])colorful(?=$|[^a-z0-9])/i.test(low)){ brand = 'COLORFUL'; }
    else if(/(?:^|[^a-z0-9])maxsun(?=$|[^a-z0-9])/i.test(low)){ brand = 'MAXSUN'; }
    var model = '';
    if(brand){
        model = text.replace(/^\s*MB\s+/i, '');
        model = model.replace(new RegExp('^\s*' + brand + '\s+', 'i'), '');
        model = model.split(/(?:\s+Soc[-\s]|\s+Socket[-\s])/i)[0] || model;
        model = model.replace(/\([^)]+\)\s*$/,'').trim();
    }
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    return { brand: brand, model: model.toUpperCase(), compactModel: compactModel };
}

function parseMonitorBrandModel(candidateName){
    var text = String(candidateName || '').replace(/″/g, '"');
    var low = text.toLowerCase();
    var brand = '';
    if(/(?:^|[^a-z0-9])elsa(?=$|[^a-z0-9])/i.test(low)){ brand = 'ELSA'; }
    else if(/(?:^|[^a-z0-9])lg(?=$|[^a-z0-9])/i.test(low)){ brand = 'LG'; }
    else if(/(?:^|[^a-z0-9])xiaomi(?=$|[^a-z0-9])/i.test(low)){ brand = 'XIAOMI'; }
    else if(/(?:^|[^a-z0-9])asrock(?=$|[^a-z0-9])/i.test(low)){ brand = 'ASROCK'; }
    else if(/(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])/i.test(low)){ brand = 'GIGABYTE'; }
    else if(/(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])/i.test(low)){ brand = 'MSI'; }
    else if(/(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])/i.test(low)){ brand = 'ASUS'; }
    var sizeMatch = text.match(/^\s*(\d{2}(?:\.\d)?)\s*"/i);
    var size = sizeMatch && sizeMatch[1] ? sizeMatch[1] : '';
    var model = text;
    if(size){
        model = model.replace(/^\s*\d{2}(?:\.\d)?\s*"\s*/i, '');
    }
    if(brand){
        model = model.replace(new RegExp('^\s*' + brand + '\s+', 'i'), '');
    }
    model = model.split(/\s*\(/, 1)[0] || model;
    model = model.trim();
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    return { brand: brand, model: model.toUpperCase(), compactModel: compactModel, size: size };
}

function parseGpuBrandModel(candidateName){
    var text = String(candidateName || '');
    var low = text.toLowerCase();
    var vendor = '';
    if(/(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])/i.test(low)){ vendor = 'GIGABYTE'; }
    else if(/(?:^|[^a-z0-9])sapphire(?=$|[^a-z0-9])/i.test(low)){ vendor = 'SAPPHIRE'; }
    else if(/(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])/i.test(low)){ vendor = 'ASUS'; }
    else if(/(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])/i.test(low)){ vendor = 'MSI'; }
    else if(/(?:^|[^a-z0-9])palit(?=$|[^a-z0-9])/i.test(low)){ vendor = 'PALIT'; }
    else if(/(?:^|[^a-z0-9])gainward(?=$|[^a-z0-9])/i.test(low)){ vendor = 'GAINWARD'; }
    else if(/(?:^|[^a-z0-9])zotac(?=$|[^a-z0-9])/i.test(low)){ vendor = 'ZOTAC'; }
    else if(/(?:^|[^a-z0-9])inno3d(?=$|[^a-z0-9])/i.test(low)){ vendor = 'INNO3D'; }
    else if(/(?:^|[^a-z0-9])ocpc(?=$|[^a-z0-9])/i.test(low)){ vendor = 'OCPC'; }
    var gpuBrand = /geforce|rtx|gtx/i.test(low) ? 'NVIDIA' : ((/radeon|(?:^|[^a-z0-9])rx\s*\d{3,4}/i.test(low)) ? 'AMD' : '');
    var model = '';
    var patterns = [
        /((?:rtx|gtx)\s*\d{4}\s*ti?)/i,
        /((?:rx)\s*\d{3,4}\s*xt?)/i,
        /((?:rx)\s*\d{3,4})/i
    ];
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            model = String(m[1]).toUpperCase().replace(/\s+/g, ' ').trim();
            break;
        }
    }
    var compactModel = model.toLowerCase().replace(/[^a-z0-9]+/g, '');
    var sku = '';
    var skuMatch = text.match(/\(([A-Za-z0-9+\- ]{6,40})\)/);
    if(skuMatch && skuMatch[1]){
        sku = String(skuMatch[1]).toLowerCase().replace(/[^a-z0-9]+/g, '');
    }
    return { vendor: vendor, gpuBrand: gpuBrand, model: model, compactModel: compactModel, sku: sku };
}

function parseRamBrandModel(candidateName){
    var text = String(candidateName || '');
    var low = text.toLowerCase();
    var brand = '';
    if(/(?:^|[^a-z0-9])kingston(?=$|[^a-z0-9])/i.test(low)){ brand = 'KINGSTON'; }
    else if(/(?:^|[^a-z0-9])g\.?skill(?=$|[^a-z0-9])/i.test(low)){ brand = 'GSKILL'; }
    else if(/(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])/i.test(low)){ brand = 'NETAC'; }
    else if(/(?:^|[^a-z0-9])team(?=$|[^a-z0-9])/i.test(low)){ brand = 'TEAM'; }
    else if(/(?:^|[^a-z0-9])a-?data|(?:^|[^a-z0-9])adata|(?:^|[^a-z0-9])xpg(?=$|[^a-z0-9])/i.test(low)){ brand = 'ADATA'; }
    else if(/(?:^|[^a-z0-9])patriot(?=$|[^a-z0-9])/i.test(low)){ brand = 'PATRIOT'; }
    else if(/(?:^|[^a-z0-9])corsair(?=$|[^a-z0-9])/i.test(low)){ brand = 'CORSAIR'; }
    var sku = '';
    var skuMatch = text.match(/\(([A-Za-z0-9+\-\/ ]{6,80})\)/);
    if(skuMatch && skuMatch[1]){
        sku = String(skuMatch[1]).toLowerCase().replace(/[^a-z0-9]+/g, '');
    }
    return { brand: brand, sku: sku };
}

function queueCandidateTone(item, candidate){
    var expectedHddCode = String((item && item.hdd_code) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    var candHddCode = String((candidate && candidate.code) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(expectedHddCode && candHddCode && expectedHddCode === candHddCode){
        return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точный HDD' };
    }
    var expectedCoolerCode = String((item && item.cooler_code) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    var candCoolerCode = String((candidate && candidate.code) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(expectedCoolerCode && candCoolerCode && expectedCoolerCode === candCoolerCode){
        return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точное охлаждение' };
    }
    var expectedPrinterArt = String((item && item.printer_article) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    var candPrinterCode = String((candidate && candidate.code) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    if(expectedPrinterArt && candPrinterCode && expectedPrinterArt === candPrinterCode){
        return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точный принтер / МФУ' };
    }
    var expectedRamBrand = String((item && item.ram_brand) || '').trim().toUpperCase();
    var expectedRamSku = String((item && item.ram_sku) || '').trim().toUpperCase();
    if(expectedRamBrand || expectedRamSku){
        var parsedRam = parseRamBrandModel(String((candidate && candidate.name) || ''));
        var sameRamBrand = !!expectedRamBrand && parsedRam.brand === expectedRamBrand;
        var sameRamSku = !!expectedRamSku && parsedRam.sku === expectedRamSku.toLowerCase().replace(/[^a-z0-9]+/g, '');
        if(sameRamBrand && sameRamSku){
            return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точная RAM SKU' };
        }
        if(sameRamBrand){
            return { bg: '#fef3c7', color: '#92400e', border: '#fcd34d', label: 'бренд ок' };
        }
        return { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5', label: 'проверить' };
    }
    var expectedGpuVendor = String((item && item.gpu_vendor) || '').trim().toUpperCase();
    var expectedGpuModel = String((item && item.gpu_model) || '').trim().toUpperCase();
    if(expectedGpuVendor || expectedGpuModel){
        var parsedGpu = parseGpuBrandModel(String((candidate && candidate.name) || ''));
        var sameGpuVendor = !!expectedGpuVendor && parsedGpu.vendor === expectedGpuVendor;
        var sameGpuModel = !!expectedGpuModel && !!parsedGpu.compactModel && parsedGpu.compactModel === expectedGpuModel.toLowerCase().replace(/[^a-z0-9]+/g, '');
        var expectedGpuSku = String((item && item.gpu_sku) || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
        var sameGpuSku = !!expectedGpuSku && parsedGpu.sku === expectedGpuSku;
        if(sameGpuVendor && sameGpuModel && sameGpuSku){
            return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точная GPU SKU' };
        }
        if(sameGpuVendor && sameGpuModel){
            return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точная GPU' };
        }
        if(sameGpuModel){
            return { bg: '#fef3c7', color: '#92400e', border: '#fcd34d', label: 'модель ок' };
        }
        return { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5', label: 'проверить' };
    }
    var expectedMonitorBrand = String((item && item.monitor_brand) || '').trim().toUpperCase();
    var expectedMonitorModel = String((item && item.monitor_model) || '').trim().toUpperCase();
    if(expectedMonitorBrand || expectedMonitorModel){
        var parsedMon = parseMonitorBrandModel(String((candidate && candidate.name) || ''));
        var sameMonitorBrand = !!expectedMonitorBrand && parsedMon.brand === expectedMonitorBrand;
        var sameMonitorModel = !!expectedMonitorModel && !!parsedMon.compactModel && parsedMon.compactModel === expectedMonitorModel.toLowerCase().replace(/[^a-z0-9]+/g, '');
        if(sameMonitorBrand && sameMonitorModel){
            return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точный монитор' };
        }
        if(sameMonitorModel){
            return { bg: '#fef3c7', color: '#92400e', border: '#fcd34d', label: 'модель ок' };
        }
        return { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5', label: 'проверить' };
    }
    var expectedBoardBrand = String((item && item.board_brand) || '').trim().toUpperCase();
    var expectedBoardModel = String((item && item.board_model) || '').trim().toUpperCase();
    if(expectedBoardBrand || expectedBoardModel){
        var parsedBoard = parseBoardBrandModel(String((candidate && candidate.name) || ''));
        var sameBoardBrand = !!expectedBoardBrand && parsedBoard.brand === expectedBoardBrand;
        var sameBoardModel = !!expectedBoardModel && !!parsedBoard.compactModel && parsedBoard.compactModel === expectedBoardModel.toLowerCase().replace(/[^a-z0-9]+/g, '');
        if(sameBoardBrand && sameBoardModel){
            return { bg: '#dcfce7', color: '#166534', border: '#86efac', label: 'точная плата' };
        }
        if(sameBoardModel){
            return { bg: '#fef3c7', color: '#92400e', border: '#fcd34d', label: 'модель ок' };
        }
        return { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5', label: 'проверить' };
    }
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
    var tone = queueCandidateTone(item, candidate);
    if(tone.label === 'точное CPU' || tone.label === 'точная плата' || tone.label === 'точный монитор' || tone.label === 'точная GPU SKU' || tone.label === 'точная GPU' || tone.label === 'точная RAM SKU' || tone.label === 'точный HDD' || tone.label === 'точное охлаждение' || tone.label === 'точный принтер / МФУ'){ return 0; }
    if(tone.label === 'модель ок' || tone.label === 'бренд ок'){ return 1; }
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
            var cpuBrand  = escapeHtml(String((item.cpu_brand || item.board_brand || item.monitor_brand || item.gpu_vendor || item.ram_brand || item.ssd_brand || item.psu_brand || item.case_brand || item.hdd_brand || item.cooler_brand || item.printer_brand || item.laptop_brand)||'').trim());
            var cpuModel  = escapeHtml(String((item.cpu_model || item.board_model || item.monitor_model || item.gpu_model || item.gpu_sku || item.ram_sku || item.ssd_model || item.ssd_code || item.psu_model || item.psu_code || item.case_model || item.case_code || item.hdd_code || item.hdd_capacity || item.cooler_code || item.cooler_tdp || item.printer_model || item.printer_article || item.laptop_model)||'').trim());
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
                    var gpuHighlight = String((item.gpu_sku || item.gpu_model || item.ram_sku || item.laptop_model) || '');
                    var cName  = highlightCpuModelMatch(String(c.name||''), String((item.cpu_model || item.board_model || item.monitor_model || gpuHighlight)||''));
                    var cSc    = c.score !== undefined ? Math.round(Number(c.score)*100) : 0;
                    var scCol  = cSc >= 90 ? '#15803d' : cSc >= 70 ? '#b45309' : '#dc2626';
                    var cUrl   = escapeHtml(String(c.url||''));
                    var tone   = queueCandidateTone(item, c);
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
                if(item) _doReviewPick(item.name_key||'', '', '', '', item.name||'', item.supplier||'');
                var wrap = skipBtn.closest('[data-rqi]');
                if(wrap){ wrap.style.opacity='0.4'; wrap.style.pointerEvents='none'; }
            } else if(pickBtn){
                var idx = Number(pickBtn.getAttribute('data-rqi-pick'));
                var ci  = Number(pickBtn.getAttribute('data-rqi-ci'));
                var item = _reviewQueueData[idx];
                if(item){
                    var cand = (item.candidates||[])[ci] || {};
                    _doReviewPick(item.name_key||'', cand.id||'', cand.name||'', cand.url||'', item.name||'', item.supplier||'');
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

function _doReviewPick(nameKey, oid, candName, url, itemName, supplier){
    fetch('/api/review-queue-pick', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name_key: nameKey, onliner_id: oid, url: url, name: itemName||'', supplier: supplier||''})
    }).then(function(r){
        return r.json().then(function(d){
            if(!r.ok || !d || d.status === 'error'){
                throw new Error((d && d.message) || 'Не удалось сохранить выбор.');
            }
            return d;
        });
    }).then(function(d){
        var badge = document.getElementById('review-queue-count-badge');
        var remaining = Number((d&&d.remaining)||0);
        if(badge){ badge.textContent = remaining; if(!remaining) badge.style.display='none'; }
        if(oid && tblMain && typeof tblMain.ajax !== 'undefined'){
            tblMain.ajax.reload(null, false);
        }
        var list = document.getElementById('review-queue-list');
        if(list){
            var done = list.querySelectorAll('[data-rqi]');
            var allFaded = true;
            done.forEach(function(el){ if(el.style.opacity !== '0.4') allFaded = false; });
            if(allFaded) list.innerHTML = '<div class="markup-note" style="color:#6b7280;">Очередь пуста.</div>';
        }
    }).catch(function(err){
        var note = document.getElementById('review-queue-note');
        if(note){
            note.textContent = String((err && err.message) || err || 'Не удалось сохранить выбор.');
            note.style.color = '#dc2626';
        } else {
            alert(String((err && err.message) || err || 'Не удалось сохранить выбор.'));
        }
        if(typeof window.loadReviewQueue === 'function'){
            window.loadReviewQueue();
        }
    });
}

window.pickReviewCandidate = _doReviewPick;
