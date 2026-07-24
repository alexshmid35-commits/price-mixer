(function(window, document) {
    'use strict';

    if (typeof window.showBusyOverlay !== 'function') {
        window.showBusyOverlay = function(){};
    }
    if (typeof window.updateBusyOverlay !== 'function') {
        window.updateBusyOverlay = function(){};
    }
    if (typeof window.hideBusyOverlay !== 'function') {
        window.hideBusyOverlay = function(){};
    }

    window.CATEGORY_PRIORITY_JS = [
        'Процессор',
        'Кулер',
        'Охлаждение',
        'Материнская плата',
        'Оперативная память',
        'SSD',
        'Жесткий диск',
        'Видеокарта',
        'Блок питания',
        'Корпус',
        'Монитор',
        'Кронштейны'
    ];

    window.onResultPageReady = function(fn) {
        if (window.jQuery && typeof window.jQuery === 'function') {
            window.jQuery(fn);
            return;
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    };
})(window, document);
