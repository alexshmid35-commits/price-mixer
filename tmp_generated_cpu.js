function processorModelQuery(name){
    var text = String(name || '');
    if(!text){ return ''; }
    var patterns = [
        /(i[3579]-\d{4,5}[a-z]{0,2})/i,
        /(ryzen\s*[3579]\s*\d{4,5}[a-z]{0,2})/i,
        /(pentium\s+[a-z]?\d{4,5})/i,
        /(celeron\s+[a-z]?\d{4,5})/i,
        /(athlon\s+\d{4,5}[a-z]{0,2})/i
    ];
    for(var i = 0; i < patterns.length; i++){
        var m = text.match(patterns[i]);
        if(m && m[1]){
            return String(m[1]).replace(/\s+/g, ' ').trim();
        }
    }
    return '';
}

