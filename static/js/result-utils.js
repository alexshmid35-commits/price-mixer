function escapeHtml(text){
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function syncDuplicateIdCheckCardCollapsed(){
    var body = document.getElementById('duplicate-id-check-card-body');
    var btn = document.getElementById('toggle-duplicate-id-check-card-btn');
    if(!body || !btn){ return; }
    body.style.display = duplicateIdCardCollapsed ? 'none' : 'block';
    btn.textContent = duplicateIdCardCollapsed ? 'Показать' : 'Скрыть';
}

function toggleDuplicateIdCheckCard(forceCollapsed){
    if(typeof forceCollapsed === 'boolean'){
        duplicateIdCardCollapsed = forceCollapsed;
    } else {
        duplicateIdCardCollapsed = !duplicateIdCardCollapsed;
    }
    syncDuplicateIdCheckCardCollapsed();
}
