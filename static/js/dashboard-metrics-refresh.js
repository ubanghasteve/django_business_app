/**
 * Non-invasive AJAX metrics refresh.
 * Uses fetch() to read-only summary endpoints; updates only textContent of existing elements.
 * Triggered: optional polling every 10s; can be called after successful form/delete by other code.
 * Does not modify existing JS or HTML structure.
 */
(function () {
  'use strict';

  var POLL_INTERVAL_MS = 10000;
  var BASE = '/dashboard/api/summaries/';
  var currencySymbol = '';

  function getCurrencySymbol() {
    if (currencySymbol) return currencySymbol;
    var meta = document.querySelector('meta[name="currency-symbol"]');
    currencySymbol = (meta && meta.getAttribute('content')) || '₦';
    return currencySymbol;
  }

  function formatCurrency(num) {
    var n = Number(num);
    if (isNaN(n)) n = 0;
    return getCurrencySymbol() + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setText(el, text) {
    if (el && el.textContent !== undefined) el.textContent = text;
  }

  function applyCoreMetrics(data) {
    var core = data && data.core;
    if (!core || typeof core !== 'object') return;
    document.querySelectorAll('[data-realtime-key]').forEach(function (el) {
      var key = el.getAttribute('data-realtime-key');
      var format = el.getAttribute('data-realtime-format') || '';
      var val;
      if (key === 'core.total_invoices') val = core.total_invoices;
      else if (key === 'core.monthly_revenue') val = core.monthly_revenue;
      else if (key === 'core.total_clients') val = core.total_clients;
      else if (key === 'core.outstanding_invoices') val = core.outstanding_invoices;
      else return;
      if (val === undefined || val === null) return;
      var text = format === 'currency' ? formatCurrency(val) : String(val);
      setText(el, text);
    });
  }

  function applyInvoiceMetrics(data) {
    if (!data || typeof data !== 'object') return;
    var els = document.querySelectorAll('[data-realtime-key]');
    els.forEach(function (el) {
      var key = el.getAttribute('data-realtime-key');
      var format = el.getAttribute('data-realtime-format') || '';
      var val;
      if (key === 'invoice.total_count') val = data.total_count;
      else if (key === 'invoice.total_amount') val = data.total_amount;
      else if (key === 'invoice.paid_amount') val = data.paid_amount;
      else if (key === 'invoice.revenue_generated') val = data.revenue_generated;
      else if (key === 'invoice.outstanding') val = data.outstanding;
      else if (key === 'invoice.refund_due') val = data.refund_due;
      else if (key === 'invoice.revenue_today') val = data.revenue_today;
      else if (key === 'invoice.revenue_week') val = data.revenue_week;
      else if (key === 'invoice.revenue_month') val = data.revenue_month;
      else if (key === 'invoice.revenue_quarter') val = data.revenue_quarter;
      else if (key === 'invoice.revenue_year') val = data.revenue_year;
      else return;
      if (val === undefined || val === null) return;
      var text = format === 'currency' ? formatCurrency(val) : String(val);
      setText(el, text);
      var card = el.closest('.card[data-full-value]');
      if (card && format === 'currency') card.setAttribute('data-full-value', text);
    });
  }

  function detectPage() {
    var path = window.location.pathname || '';
    // Main dashboard: do not refresh metrics via API — server-rendered values are authoritative (avoids zeros overwrite).
    if (path.indexOf('/dashboard') !== -1 && path.replace(/\/$/, '').endsWith('dashboard')) return null;
    if (path.indexOf('/invoices') !== -1 && path.indexOf('/template') === -1) return 'invoices';
    if (path.indexOf('/receipts') !== -1) return 'receipts';
    if (path.indexOf('/quotations') !== -1) return 'quotations';
    if (path.indexOf('/waybills') !== -1) return 'waybills';
    if (path.indexOf('/job-orders') !== -1) return 'job_orders';
    return null;
  }

  function summaryPathForPage(page) {
    if (page === 'dashboard') return 'dashboard/';
    if (page === 'job_orders') return 'job-orders/';
    return page + '/';
  }

  function fetchAndApply(page) {
    var url = BASE + summaryPathForPage(page);
    fetch(url, {
      method: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      credentials: 'same-origin'
    }).then(function (res) {
      if (!res.ok) {
        console.warn('[Dashboard metrics] Summary request failed: ' + res.status + ' ' + res.statusText + ' for ' + url);
        return null;
      }
      return res.json();
    }).then(function (data) {
      if (!data || typeof data !== 'object') return;
      if (data.error) {
        console.warn('[Dashboard metrics] Invalid response (error):', data.error);
        return;
      }
      // Only apply dashboard metrics when we have core data (avoid overwriting with zeros from failed/empty context)
      if (page === 'dashboard') {
        if (data.core && typeof data.core === 'object') applyCoreMetrics(data);
      } else if (page === 'invoices') applyInvoiceMetrics(data);
    }).catch(function (err) {
      console.warn('[Dashboard metrics] Summary fetch failed, keeping server-rendered values:', err && err.message);
    });
  }

  function runRefresh() {
    var page = detectPage();
    if (page) fetchAndApply(page);
  }

  function startPolling() {
    // Defer first refresh so initial page request (and its DB writes) can finish first (avoids SQLite "database is locked")
    setTimeout(function () {
      runRefresh();
      setInterval(runRefresh, POLL_INTERVAL_MS);
    }, 2000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      startPolling();
    });
  } else {
    startPolling();
  }

  window.refreshDashboardMetrics = runRefresh;
})();
