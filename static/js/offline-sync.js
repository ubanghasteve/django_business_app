/**
 * Offline-first sync layer: IndexedDB + wrap AJAX + auto sync when online.
 * - IndexedDB: app_offline_db with one store per model (clients, invoices, requisitions, expense).
 * - Each record: uuid, payload, synced (boolean), updated_at (ISO string), tenant_id.
 * - When offline: store in IndexedDB with synced=false; when online: POST to /api/v1/{model}/bulk-create-update/.
 * - After successful push: GET /api/v1/{model}/changes/?since=last_sync_time and update local cache; store last_sync_time in localStorage.
 */
(function (global) {
  'use strict';

  const DB_NAME = 'app_offline_db';
  const DB_VERSION = 6;
  // IndexedDB store names (local cache). Keep broad so existing offline drafts still open.
  const STORES = [
    // Core Business Apps
    'clients', 'invoices', 'requisitions', 'expense', 'receipts', 'waybills', 'quotations',
    // Inventory & Jobs
    'inventory', 'job_orders',
    // HR & Staff
    'hr_staff', 'hr_departments', 'hr_leaves', 'hr_leave_policies', 'hr_performance_reviews',
    'hr_goals', 'hr_training_courses', 'hr_training_enrollments', 'hr_job_seekers', 'hr_documents',
    // Payroll
    'payroll', 'payroll_items', 'payslips', 'salary_advances', 'loans', 'bonuses',
    // Smart Attendance
    'smart_attendance', 'attendance_logs', 'attendance_devices', 'attendance_employees',
    // Documents & Messaging
    'documents', 'messaging', 'notifications',
    // Core/Account
    'core_company', 'core_bank_accounts',
    // Accounting
    'accounting',
    // Expense Additional
    'expense_categories', 'expense_custom_fields', 'expense_custom_forms'
  ];
  // Only models that have working /api/v1/{model}/changes/ backends.
  // Polling unsupported names caused terminal 404 spam and did not affect feature UIs.
  const API_SYNC_MODELS = [
    'clients', 'invoices', 'requisitions', 'expense', 'receipts', 'waybills', 'quotations',
    'inventory', 'job_orders',
    'hr_staff', 'hr_departments', 'hr_leaves',
    'accounting', 'documents',
    'messaging', 'notifications',
    'core_company', 'core_bank_accounts'
  ];
  const API_BASE = '/api/v1';
  const LAST_SYNC_PREFIX = 'offline_sync_last_';
  const QUEUES_DB_NAME = 'app_offline_queues';
  const QUEUES_DB_VERSION = 5;
  const QUEUE_STORES = [
    'pending_messages', 'pending_emails', 'pending_sms', 
    'pending_requests', 'pending_notifications', 
    'pending_attendance', 'pending_payroll',
    'pending_hr_actions', 'pending_expense_actions'
  ];

  let db = null;
  let queuesDb = null;

  function openDB() {
    if (db) return Promise.resolve(db);
    return new Promise(function (resolve, reject) {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onerror = function () { reject(req.error); };
      req.onsuccess = function () { db = req.result; resolve(db); };
      req.onupgradeneeded = function (event) {
        const database = event.target.result;
        STORES.forEach(function (storeName) {
          if (!database.objectStoreNames.contains(storeName)) {
            const store = database.createObjectStore(storeName, { keyPath: 'uuid' });
            store.createIndex('synced', 'synced', { unique: false });
            store.createIndex('tenant_id', 'tenant_id', { unique: false });
          }
        });
        if (!database.objectStoreNames.contains('metadata')) {
          database.createObjectStore('metadata', { keyPath: 'key' });
        }
      };
    });
  }

  function openQueuesDB() {
    if (queuesDb) return Promise.resolve(queuesDb);
    return new Promise(function (resolve, reject) {
      const req = indexedDB.open(QUEUES_DB_NAME, QUEUES_DB_VERSION);
      req.onerror = function () { reject(req.error); };
      req.onsuccess = function () { queuesDb = req.result; resolve(queuesDb); };
      req.onupgradeneeded = function (event) {
        const database = event.target.result;
        QUEUE_STORES.forEach(function (storeName) {
          if (!database.objectStoreNames.contains(storeName)) {
            database.createObjectStore(storeName, { keyPath: 'id', autoIncrement: true });
          }
        });
      };
    });
  }

  /**
   * Store a record for offline sync. Sets synced=false, updated_at=now, tenant_id.
   * payload must include or get a uuid (generated if missing).
   */
  function storeInIndexedDB(model, payload, tenantId) {
    var uuid = payload.uuid || generateUUID();
    if (!payload.uuid) payload.uuid = uuid;
    var record = {
      uuid: uuid,
      payload: payload,
      synced: false,
      updated_at: new Date().toISOString(),
      tenant_id: String(tenantId || '')
    };
    return openDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx = database.transaction(model, 'readwrite');
        const store = tx.objectStore(model);
        const req = store.put(record);
        req.onsuccess = function () { resolve(uuid); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0;
      var v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  /**
   * Get all unsynced records for a model (synced === false).
   * Uses getAll() + filter because IDBKeyRange.only() does not accept boolean in all browsers.
   */
  function getUnsynced(model) {
    return openDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx = database.transaction(model, 'readonly');
        const store = tx.objectStore(model);
        const req = store.getAll();
        req.onsuccess = function () {
          const rows = req.result || [];
          resolve(rows.filter(function (r) { return r.synced === false; }));
        };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /**
   * Mark records as synced (by uuid list) for a model.
   */
  function markSynced(model, uuids) {
    if (!uuids || uuids.length === 0) return Promise.resolve();
    return openDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx = database.transaction(model, 'readwrite');
        const store = tx.objectStore(model);
        uuids.forEach(function (uuid) {
          const getReq = store.get(uuid);
          getReq.onsuccess = function () {
            var r = getReq.result;
            if (r) {
              r.synced = true;
              r.updated_at = new Date().toISOString();
              store.put(r);
            }
          };
        });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function getLastSyncTime(model) {
    try {
      var s = localStorage.getItem(LAST_SYNC_PREFIX + model);
      return s || null;
    } catch (e) {
      return null;
    }
  }

  function setLastSyncTime(model, isoString) {
    try {
      localStorage.setItem(LAST_SYNC_PREFIX + model, isoString);
    } catch (e) {}
    // Best-effort: also persist last_sync in IndexedDB metadata for diagnostics and cross-tab visibility
    openDB().then(function (database) {
      try {
        if (!database.objectStoreNames.contains('metadata')) return;
        var tx = database.transaction('metadata', 'readwrite');
        var store = tx.objectStore('metadata');
        store.put({ key: LAST_SYNC_PREFIX + model, value: isoString });
      } catch (e) {
      }
    }).catch(function () {});
  }

  /**
   * Get CSRF token from meta or cookie for fetch.
   */
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
    var name = 'csrftoken';
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var parts = cookies[i].trim().split('=');
      if (parts[0] === name) return decodeURIComponent(parts[1] || '');
    }
    return '';
  }

  function fetchOpts(method, body) {
    var opts = {
      method: method || 'GET',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      }
    };
    opts.headers['X-CSRFToken'] = getCsrfToken();
    if (body) {
      opts.body = typeof body === 'string' ? body : JSON.stringify(body);
      opts.headers['Content-Type'] = 'application/json';
    }
    return opts;
  }

  /**
   * Push unsynced items for one model to the server (POST bulk-create-update).
   * Retries once on network failure so no records are left behind.
   * Returns { success: true, syncedUuids: [...], syncedCount: N } or { success: false, error: ... }.
   */
  function pushModel(model, retryCount) {
    retryCount = retryCount || 0;
    return getUnsynced(model).then(function (rows) {
      if (rows.length === 0) return { success: true, syncedUuids: [], syncedCount: 0 };
      var items = rows.map(function (r) { return r.payload; });
      var url = API_BASE + '/' + model + '/bulk-create-update/';
      return fetch(url, fetchOpts('POST', { items: items }))
        .then(function (res) {
          if (!res.ok) return res.text().then(function (t) { throw new Error(t || res.status); });
          return res.json();
        })
        .then(function (data) {
          var successCount = (data.success || []).length;
          var syncedUuids = rows.slice(0, successCount).map(function (r) { return r.uuid; });
          return markSynced(model, syncedUuids).then(function () {
            return { success: true, syncedUuids: syncedUuids, syncedCount: syncedUuids.length, response: data };
          });
        })
        .catch(function (err) {
          if (retryCount < 1) {
            return new Promise(function (resolve) { setTimeout(resolve, 1000); }).then(function () {
              return pushModel(model, retryCount + 1);
            });
          }
          throw err;
        });
    });
  }

  /**
   * Pull server changes for one model (GET changes/?since=...) and merge into IndexedDB (upsert by uuid).
   */
  function pullModel(model) {
    var since = getLastSyncTime(model);
    if (!since) since = '1970-01-01T00:00:00Z';
    var url = API_BASE + '/' + model + '/changes/?since=' + encodeURIComponent(since);
    return fetch(url, fetchOpts('GET'))
      .then(function (res) {
        if (!res.ok) return [];
        return res.json();
      })
      .then(function (items) {
        if (!items || items.length === 0) return;
        var now = new Date().toISOString();
        setLastSyncTime(model, now);
        return openDB().then(function (database) {
          return new Promise(function (resolve, reject) {
            const tx = database.transaction(model, 'readwrite');
            const store = tx.objectStore(model);
            items.forEach(function (item) {
              if (!item) return;
              var key = item.uuid || (item.id != null ? String(item.id) : null);
              if (!key) return;
              var r = {
                uuid: key,
                payload: item,
                synced: true,
                updated_at: item.updated_at || item.created_at || now,
                tenant_id: ''
              };
              store.put(r);
            });
            tx.oncomplete = resolve;
            tx.onerror = function () { reject(tx.error); };
          });
        });
      })
      .catch(function () {
        // Never break the sync loop for one model
        return null;
      });
  }

  /**
   * Sync all models: push unsynced, then pull changes for each. Runs silently in background.
   * Resolves with { hadUnsynced: number } (total records that were synced). Dispatches offlineSyncComplete when done.
   */
  function syncAllModels(options) {
    options = options || {};
    var onDone = options.onDone || function () {};
    if (!navigator.onLine) {
      onDone({ online: false, hadUnsynced: 0 });
      return Promise.resolve({ hadUnsynced: 0 });
    }
    var totalSynced = 0;
    var sequence = Promise.resolve();
    API_SYNC_MODELS.forEach(function (model) {
      sequence = sequence
        .then(function () { return pushModel(model); })
        .then(function (result) {
          if (result && result.syncedCount) totalSynced += result.syncedCount;
          return pullModel(model);
        })
        .catch(function () { return null; });
    });
    return sequence.then(function () {
      onDone({ online: true, hadUnsynced: totalSynced });
      try {
        if (typeof window !== 'undefined' && window.dispatchEvent) {
          window.dispatchEvent(new CustomEvent('offlineSyncComplete', { detail: { hadUnsynced: totalSynced } }));
        }
      } catch (e) {}
      return { hadUnsynced: totalSynced };
    }).catch(function (err) {
      if (typeof console !== 'undefined' && console.warn) console.warn('[OfflineSync] sync error:', err);
      onDone({ online: true, error: err, hadUnsynced: totalSynced });
      try {
        if (typeof window !== 'undefined' && window.dispatchEvent) {
          window.dispatchEvent(new CustomEvent('offlineSyncComplete', { detail: { error: err, hadUnsynced: totalSynced } }));
        }
      } catch (e) {}
      return Promise.reject(err);
    });
  }

  /**
   * Wrap a create/update AJAX call: if online, run attemptAjaxSubmit(); else store in IndexedDB and resolve with { savedOffline: true }.
   * Does NOT remove existing AJAX logic — call this instead of calling the AJAX directly when you want offline support.
   * @param {string} model - One of: clients, invoices, requisitions, expense
   * @param {object} payload - Record payload (must be JSON-serializable; uuid optional)
   * @param {string} tenantId - Current tenant/account id (e.g. from meta or window.__TENANT_ID)
   * @param {function} attemptAjaxSubmit - Function that returns a Promise (e.g. () => fetch(...).then(...))
   * @returns {Promise} Resolves with AJAX result or { savedOffline: true, uuid } when stored offline.
   */
  function wrapSubmit(model, payload, tenantId, attemptAjaxSubmit) {
    if (navigator.onLine) {
      return Promise.resolve(attemptAjaxSubmit());
    }
    return storeInIndexedDB(model, payload, tenantId).then(function (uuid) {
      return { savedOffline: true, uuid: uuid };
    });
  }

  /**
   * Wrap a delete (soft-delete) AJAX call: if online, run attemptAjax(); else store { uuid, is_deleted: true } in IndexedDB.
   * Sync API will apply soft-delete when pushed. Use for invoices, requisitions, expense, clients.
   * @param {string} model - One of: clients, invoices, requisitions, expense
   * @param {string} uuid - Record uuid to delete
   * @param {string} tenantId - Current tenant id
   * @param {function} attemptAjax - Function that returns a Promise (e.g. () => fetch(...).then(...))
   * @returns {Promise} Resolves with AJAX result or { savedOffline: true } when stored offline.
   */
  function wrapDelete(model, uuid, tenantId, attemptAjax) {
    if (!uuid) {
      return Promise.resolve(attemptAjax());
    }
    if (navigator.onLine) {
      return Promise.resolve(attemptAjax());
    }
    var payload = { uuid: uuid, is_deleted: true, updated_at: new Date().toISOString() };
    return storeInIndexedDB(model, payload, tenantId).then(function () {
      return { savedOffline: true };
    });
  }

  /**
   * Expose for pages: get current tenant id from meta or window.
   */
  function getTenantId() {
    if (typeof window !== 'undefined' && window.__TENANT_ID) return window.__TENANT_ID;
    var meta = document.querySelector('meta[name="tenant-id"]');
    return meta ? meta.getAttribute('content') || '' : '';
  }

  /** Queue a message for sending when online. url = full POST URL, payload = { content, reply_to }. */
  function queuePendingMessage(url, payload, optimisticId) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_messages', 'readwrite');
        var store = tx.objectStore('pending_messages');
        var record = { url: url, payload: payload || {}, optimisticId: optimisticId || '', created_at: new Date().toISOString() };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /** Queue email for sending when online. payload = { recipients, subject, message, additional_emails }. */
  function queuePendingEmail(payload) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_emails', 'readwrite');
        var store = tx.objectStore('pending_emails');
        var record = { payload: payload || {}, created_at: new Date().toISOString() };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /** Queue SMS for sending when online. payload = { recipients, message, additional_phones }. */
  function queuePendingSms(payload) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_sms', 'readwrite');
        var store = tx.objectStore('pending_sms');
        var record = { payload: payload || {}, created_at: new Date().toISOString() };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /**
   * Queue a form or arbitrary request to replay when online (profile edit, team member, company profile, etc.).
   * record = { url, method, body (string), contentType, created_at }.
   */
  function queuePendingRequest(url, method, body, contentType) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_requests', 'readwrite');
        var store = tx.objectStore('pending_requests');
        var record = {
          url: url,
          method: method || 'POST',
          body: body || '',
          contentType: contentType || 'application/x-www-form-urlencoded',
          created_at: new Date().toISOString()
        };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /**
   * Queue a notifications API action (mark-read, mark-all-read, clear-all, delete).
   * Stored separately so it can be processed with proper ordering.
   * record = { url, method, body, created_at }.
   */
  function queuePendingNotification(url, method, body) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_notifications', 'readwrite');
        var store = tx.objectStore('pending_notifications');
        var record = {
          url: url,
          method: method || 'POST',
          body: body || null,
          created_at: new Date().toISOString()
        };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  /**
   * Build a JSON payload from form inputs for sync API. Skips file inputs and csrf.
   * Use for forms with data-sync-model when offline.
   */
  function buildFormPayload(form, options) {
    options = options || {};
    var payload = { updated_at: new Date().toISOString(), is_deleted: false };
    var elements = form.elements || [];
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      if (!el.name || el.disabled) continue;
      if (el.type === 'file') continue;
      if (el.name === 'csrfmiddlewaretoken') continue;
      if (el.type === 'checkbox') {
        payload[el.name] = el.checked;
        continue;
      }
      if (el.type === 'radio' && !el.checked) continue;
      if (el.type === 'radio') {
        payload[el.name] = el.value;
        continue;
      }
      var v = el.value;
      if (v === '' || (typeof v === 'string' && v.trim() === '')) continue;
      if (el.type === 'number' || el.type === 'range') {
        var n = parseFloat(v);
        payload[el.name] = isNaN(n) ? v : n;
      } else {
        payload[el.name] = v;
      }
    }
    return payload;
  }

  /**
   * Serialize form to application/x-www-form-urlencoded, skipping file inputs (so it can be replayed when online).
   * For multipart forms, only non-file fields are queued; user can re-upload files when online.
   */
  function serializeFormForOffline(form) {
    var fd = new FormData(form);
    var params = new URLSearchParams();
    fd.forEach(function (value, key) {
      if (value instanceof File) {
        if (value.size > 0) return; /* skip file content when queueing */
      }
      params.append(key, value);
    });
    return params.toString();
  }

  /**
   * Queue form submit for when online. Returns a promise that resolves when queued.
   * Use when offline; form will be replayed as POST with same action and body (non-file fields only).
   */
  function queueFormSubmit(form) {
    var url = (form.getAttribute('action') || window.location.href).trim();
    if (url.indexOf('/') === 0) url = window.location.origin + url;
    var method = (form.getAttribute('method') || 'GET').toUpperCase();
    var body = serializeFormForOffline(form);
    return queuePendingRequest(url, method, body, 'application/x-www-form-urlencoded');
  }

  function processPendingRequests() {
    return getAllFromQueue('pending_requests').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var item = items[0];
      var opts = {
        method: item.method || 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': item.contentType || 'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'text/html, application/json'
        }
      };
      opts.headers['X-CSRFToken'] = getCsrfToken();
      opts.body = item.body || '';
      return fetch(item.url, opts).then(function (r) {
        if (r.ok || r.status === 302 || r.status === 301) return deleteFromQueue('pending_requests', item.id);
        return Promise.resolve();
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingRequests() : Promise.resolve();
      });
    });
  }

  function getAllFromQueue(storeName) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction(storeName, 'readonly');
        var store = tx.objectStore(storeName);
        var req = store.getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function deleteFromQueue(storeName, id) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction(storeName, 'readwrite');
        var store = tx.objectStore(storeName);
        var req = store.delete(id);
        req.onsuccess = function () { resolve(); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function processPendingNotifications() {
    return getAllFromQueue('pending_notifications').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var item = items[0];
      var opts = fetchOpts(item.method || 'POST', item.body || null);
      return fetch(item.url, opts).then(function (r) {
        if (r.ok || r.status === 204 || r.status === 200) {
          return deleteFromQueue('pending_notifications', item.id);
        }
        return Promise.resolve();
      }).catch(function () {
        return Promise.resolve();
      }).then(function () {
        return items.length > 1 ? processPendingNotifications() : Promise.resolve();
      });
    });
  }

  function processPendingMessages() {
    return getAllFromQueue('pending_messages').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var opts = fetchOpts('POST', items[0].payload);
      opts.headers['Content-Type'] = 'application/json';
      return fetch(items[0].url, opts).then(function (r) {
        return r.json().then(function (data) {
          if (r.ok && !data.error) return deleteFromQueue('pending_messages', items[0].id);
          return Promise.resolve();
        }).catch(function () { return Promise.resolve(); });
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingMessages() : Promise.resolve();
      });
    });
  }

  function processPendingEmails() {
    return getAllFromQueue('pending_emails').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var opts = fetchOpts('POST', items[0].payload);
      opts.headers['Content-Type'] = 'application/json';
      return fetch('/api/mailing/send-email/', opts).then(function (r) {
        return r.json().then(function (data) {
          if (r.ok && data && data.success) return deleteFromQueue('pending_emails', items[0].id);
          return Promise.resolve();
        }).catch(function () { return Promise.resolve(); });
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingEmails() : Promise.resolve();
      });
    });
  }

  function processPendingSms() {
    return getAllFromQueue('pending_sms').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var opts = fetchOpts('POST', items[0].payload);
      opts.headers['Content-Type'] = 'application/json';
      return fetch('/api/mailing/send-sms/', opts).then(function (r) {
        return r.json().then(function (data) {
          if (r.ok && data && data.success) return deleteFromQueue('pending_sms', items[0].id);
          return Promise.resolve();
        }).catch(function () { return Promise.resolve(); });
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingSms() : Promise.resolve();
      });
    });
  }

  function queuePendingAttendance(payload) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_attendance', 'readwrite');
        var store = tx.objectStore('pending_attendance');
        var record = { payload: payload || {}, created_at: new Date().toISOString() };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function processPendingAttendance() {
    return getAllFromQueue('pending_attendance').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var opts = fetchOpts('POST', items[0].payload);
      opts.headers['Content-Type'] = 'application/json';
      return fetch('/api/attendance/push-offline/', opts).then(function (r) {
        if (r.ok || r.status === 200) {
          return deleteFromQueue('pending_attendance', items[0].id);
        }
        return Promise.resolve();
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingAttendance() : Promise.resolve();
      });
    });
  }

  function queuePendingPayroll(payload) {
    return openQueuesDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        var tx = database.transaction('pending_payroll', 'readwrite');
        var store = tx.objectStore('pending_payroll');
        var record = { payload: payload || {}, created_at: new Date().toISOString() };
        var req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function processPendingPayroll() {
    return getAllFromQueue('pending_payroll').then(function (items) {
      if (items.length === 0) return Promise.resolve();
      var opts = fetchOpts('POST', items[0].payload);
      opts.headers['Content-Type'] = 'application/json';
      return fetch('/api/payroll/offline-sync/', opts).then(function (r) {
        if (r.ok || r.status === 200) {
          return deleteFromQueue('pending_payroll', items[0].id);
        }
        return Promise.resolve();
      }).catch(function () { return Promise.resolve(); }).then(function () {
        return items.length > 1 ? processPendingPayroll() : Promise.resolve();
      });
    });
  }

  function processAllPendingQueues() {
    return processPendingMessages()
      .then(processPendingEmails)
      .then(processPendingSms)
      .then(processPendingNotifications)
      .then(processPendingAttendance)
      .then(processPendingPayroll)
      .then(processPendingRequests);
  }

  var OfflineSync = {
    openDB: openDB,
    storeInIndexedDB: storeInIndexedDB,
    getUnsynced: getUnsynced,
    markSynced: markSynced,
    getLastSyncTime: getLastSyncTime,
    setLastSyncTime: setLastSyncTime,
    pushModel: pushModel,
    pullModel: pullModel,
    syncAllModels: syncAllModels,
    wrapSubmit: wrapSubmit,
    wrapDelete: wrapDelete,
    getTenantId: getTenantId,
    buildFormPayload: buildFormPayload,
    queuePendingMessage: queuePendingMessage,
    queuePendingEmail: queuePendingEmail,
    queuePendingSms: queuePendingSms,
    queuePendingRequest: queuePendingRequest,
    queueFormSubmit: queueFormSubmit,
    queuePendingNotification: queuePendingNotification,
    queuePendingAttendance: queuePendingAttendance,
    queuePendingPayroll: queuePendingPayroll,
    processPendingRequests: processPendingRequests,
    processPendingNotifications: processPendingNotifications,
    processPendingAttendance: processPendingAttendance,
    processPendingPayroll: processPendingPayroll,
    processAllPendingQueues: processAllPendingQueues,
    getAllFromQueue: getAllFromQueue,
    STORES: STORES,
    API_BASE: API_BASE
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = OfflineSync;
  } else {
    global.OfflineSync = OfflineSync;
  }
})(typeof window !== 'undefined' ? window : this);
