function initSnapshotFilterUI(){
    function syncSnapshotDetailUI(){
        var wrap = document.getElementById('snapshot-lists');
        if(!wrap){ return; }
        var mode = String(snapshotDetailMode || '').trim();
        wrap.classList.toggle('active', !!mode);
        wrap.querySelectorAll('.snapshot-list').forEach(function(card){
            var kind = String(card.getAttribute('data-kind') || '').trim();
            card.classList.toggle('active', !!mode && kind === mode);
        });
        document.querySelectorAll('.snapshot-mini[data-kind]').forEach(function(card){
            var kind = String(card.getAttribute('data-kind') || '').trim();
            card.classList.toggle('active', !!mode && kind === mode);
        });
    }
    function toggleSnapshotDetail(mode){
        var next = String(mode || '').trim();
        snapshotDetailMode = (snapshotDetailMode === next) ? '' : next;
        syncSnapshotDetailUI();
    }
    function setSnapshotFilter(mode){
        var filters = (window.snapshotDiffData && window.snapshotDiffData.filters) ? window.snapshotDiffData.filters : {};
        snapshotFilterMode = mode || '';
        if(mode === 'new'){
            snapshotFilterNames = Array.isArray(filters.new_names) ? filters.new_names.slice() : [];
        } else if(mode === 'new_without_id'){
            snapshotFilterNames = Array.isArray(filters.new_without_id_names) ? filters.new_without_id_names.slice() : [];
        } else {
            snapshotFilterNames = [];
        }
        showOnlySnapshotRows = !!snapshotFilterNames.length;
        redrawMainTable();
    }
    var btnNew = document.getElementById('show-new-items-btn');
    if(btnNew){
        btnNew.addEventListener('click', function(){ setSnapshotFilter('new'); });
    }
    var btnNewNoId = document.getElementById('show-new-noid-items-btn');
    if(btnNewNoId){
        btnNewNoId.addEventListener('click', function(){ setSnapshotFilter('new_without_id'); });
    }
    var btnClear = document.getElementById('clear-snapshot-filter-btn');
    if(btnClear){
        btnClear.addEventListener('click', function(){ setSnapshotFilter(''); });
    }
    document.querySelectorAll('.snapshot-mini[data-kind]').forEach(function(card){
        card.addEventListener('click', function(){
            toggleSnapshotDetail(card.getAttribute('data-kind'));
        });
    });
    syncSnapshotDetailUI();
}
