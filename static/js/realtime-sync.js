/**
 * Phase 4–5 — Real-time template updates (non-destructive).
 * Subscribes to WebSocket; updates ONLY elements with data-realtime-key.
 * Phase 7: No hard dependency — if WebSocket fails, app continues; manual refresh works.
 */
(function () {
  'use strict';

  function getValue(obj, path) {
    var parts = path.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length && cur != null; i++) {
      cur = cur[parts[i]];
    }
    return cur;
  }

  function formatValue(value, format, currencySymbol) {
    if (value === undefined || value === null) value = 0;
    if (format === 'currency' && typeof value === 'number') {
      var sym = currencySymbol || (document.querySelector('meta[name="currency-symbol"]') || {}).content || '₦';
      return sym + Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    if (typeof value === 'number' && (value % 1 !== 0)) {
      return Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return String(value);
  }

  function applyMetrics(metrics) {
    if (!metrics || typeof metrics !== 'object') return;
    var currencySymbol = (document.querySelector('meta[name="currency-symbol"]') || {}).content || '₦';
    var updated = 0;
    document.querySelectorAll('[data-realtime-key]').forEach(function (el) {
      var key = el.getAttribute('data-realtime-key');
      var format = el.getAttribute('data-realtime-format') || '';
      var value = getValue(metrics, key);
      if (value === undefined) return;
      var text = formatValue(value, format, currencySymbol);
      if (el.getAttribute('data-realtime-target') === 'inner') {
        el.innerHTML = text;
      } else {
        el.textContent = text;
      }
      updated++;
    });
  }

  function connect() {
    var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var host = window.location.host;
    var url = protocol + '//' + host + '/ws/realtime/';
    var ws = null;
    var reconnectTimeout = null;
    var reconnectDelay = 3000;

    function tryReconnect() {
      reconnectTimeout = setTimeout(function () {
        if (!ws || ws.readyState === WebSocket.CLOSED) connect();
      }, reconnectDelay);
    }

    try {
      ws = new WebSocket(url);
    } catch (e) {
      return;
    }

    ws.onopen = function () {
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }
    };

    ws.onmessage = function (event) {
      try {
        var data = JSON.parse(event.data);
        if (data.type === 'metrics' && data.metrics) {
          var m = data.metrics;
          applyMetrics(m);
        }
      } catch (err) {
        // ignore parse errors
      }
    };

    ws.onerror = function () {
      // no-op; onclose will run
    };

    ws.onclose = function () {
      tryReconnect();
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (window.__REALTIME_ENABLED) connect();
    });
  } else {
    if (window.__REALTIME_ENABLED) connect();
  }
})();
