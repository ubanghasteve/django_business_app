(function (global) {
  'use strict';

  /**
   * UnifiedSyncEngine
   * Thin wrapper around OfflineSync that:
   * - Schedules periodic syncs (push + pull) for all models
   * - Processes all pending queues (requests, notifications, messages, email, SMS)
   * - Updates a global online/offline banner
   *
   * It does NOT replace OfflineSync; it composes it for backwards compatibility.
   */

  function UnifiedSyncEngine(offlineSync) {
    this.offlineSync = offlineSync || global.OfflineSync || null;
    this.intervalMs = 60000; // 60 seconds
    this._init();
  }

  UnifiedSyncEngine.prototype._init = function () {
    var self = this;
    if (!this.offlineSync || typeof window === 'undefined' || typeof document === 'undefined') {
      return;
    }

    function trigger() {
      self.runFullSyncCycle();
    }

    // Online/offline listeners
    window.addEventListener('online', function () {
      self.updateConnectionBanner();
      trigger();
    });
    window.addEventListener('offline', function () {
      self.updateConnectionBanner();
    });

    // Visibility change: when tab becomes visible, try a sync
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && navigator.onLine) {
        trigger();
      }
    });

    // Initial sync after load/idle so it does not compete with first paint
    function scheduleInitial() {
      self.updateConnectionBanner();
      var run = function () { trigger(); };
      if (typeof window.requestIdleCallback !== 'undefined') {
        window.requestIdleCallback(run, { timeout: 4000 });
      } else {
        setTimeout(run, 4000);
      }
    }

    if (document.readyState === 'complete') {
      scheduleInitial();
    } else {
      window.addEventListener('load', function () {
        scheduleInitial();
      });
    }

    // Background sync every 60s when tab is visible
    setInterval(function () {
      if (document.visibilityState === 'visible' && navigator.onLine) {
        trigger();
      }
    }, this.intervalMs);
  };

  UnifiedSyncEngine.prototype._isListPage = function () {
    if (typeof location === 'undefined') return false;
    var path = location.pathname || '';
    var re = /^\/(expense|invoices|clients|requisitions|receipts|waybills|quotations|job-orders|inventory|accounting|hr-staff)(\/)?(\?.*)?$/;
    var reWithSlash = /^\/(expense|invoices|clients|requisitions|receipts|waybills|quotations|job-orders|inventory|accounting|hr-staff)\/$/;
    return re.test(path) || reWithSlash.test(path);
  };

  UnifiedSyncEngine.prototype.updateConnectionBanner = function () {
    if (typeof document === 'undefined') return;
    var banner = document.getElementById('connection-status-banner');
    var icon = document.getElementById('connection-status-icon');
    if (!banner && !icon) return;

    var textEl = document.getElementById('connection-status-text');
    var dotEl = document.getElementById('connection-status-dot');

    var online = (typeof navigator !== 'undefined') ? navigator.onLine : true;
    if (online) {
      if (banner) {
        banner.className = 'alert alert-success d-flex align-items-center justify-content-between py-2 px-3 mb-3';
        banner.style.display = 'none'; // Hide banner when online (icon is enough)
      }
      if (textEl) {
        textEl.textContent = 'Online – Changes sync automatically.';
      }
      if (dotEl) {
        dotEl.style.backgroundColor = '#28a745';
      }
      if (icon) {
        icon.style.backgroundColor = '#28a745';
        icon.setAttribute('title', 'Online – Changes sync automatically.');
      }
    } else {
      if (banner) {
        banner.className = 'alert alert-danger d-flex align-items-center justify-content-between py-2 px-3 mb-3';
        banner.style.display = 'flex'; // Show banner when offline
      }
      if (textEl) {
        textEl.textContent = 'Offline – Changes will sync automatically when you reconnect.';
      }
      if (dotEl) {
        dotEl.style.backgroundColor = '#dc3545';
      }
      if (icon) {
        icon.style.backgroundColor = '#dc3545';
        icon.setAttribute('title', 'Offline – Changes will sync automatically when you reconnect.');
      }
    }
  };

  UnifiedSyncEngine.prototype._showSyncNotification = function (count) {
    // Check if notification already shown recently (within last 30 seconds)
    var now = Date.now();
    if (this._lastNotificationTime && (now - this._lastNotificationTime) < 30000) {
      return; // Skip - already notified recently
    }
    this._lastNotificationTime = now;
    
    // Create a subtle toast notification
    var existing = document.getElementById('sync-complete-toast');
    if (existing) existing.remove();
    
    var toast = document.createElement('div');
    toast.id = 'sync-complete-toast';
    toast.className = 'alert alert-success position-fixed';
    toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 250px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);';
    toast.innerHTML = '<strong><i class="fas fa-sync-alt me-2"></i>Sync Complete</strong><br><small>' + count + ' record(s) synced successfully.</small>';
    document.body.appendChild(toast);
    
    // Auto-remove after 4 seconds
    setTimeout(function() {
      if (toast.parentNode) toast.remove();
    }, 4000);
  };

  /**
   * Run full sync cycle:
   * 1. syncAllModels (push unsynced, then pull changes)
   * 2. processAllPendingQueues (messages, email, SMS, notifications, generic requests)
   * 3. Reload list pages when records were synced so UI reflects server state
   */
  UnifiedSyncEngine.prototype.runFullSyncCycle = function () {
    var self = this;
    if (!this.offlineSync) {
      return Promise.resolve({ online: false, hadUnsynced: 0 });
    }
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      this.updateConnectionBanner();
      return Promise.resolve({ online: false, hadUnsynced: 0 });
    }

    var hadUnsynced = 0;

    function onDone(result) {
      if (result && typeof result.hadUnsynced === 'number') {
        hadUnsynced = result.hadUnsynced;
      }
    }

    var syncFunc = this.offlineSync.syncAllModels || function () {
      return Promise.resolve({ hadUnsynced: 0 });
    };

    return syncFunc({ onDone: onDone }).then(function (res) {
      if (res && typeof res.hadUnsynced === 'number') {
        hadUnsynced = res.hadUnsynced;
      }
      if (self.offlineSync.processAllPendingQueues) {
        return self.offlineSync.processAllPendingQueues().then(function () {
          return hadUnsynced;
        });
      }
      return hadUnsynced;
    }).then(function (finalUnsynced) {
      self.updateConnectionBanner();
      // Instead of reloading, dispatch an event that pages can listen to
      if (finalUnsynced > 0) {
        try {
          // Dispatch custom event for pages to handle UI update
          var syncEvent = new CustomEvent('offlineDataSynced', { 
            detail: { 
              hadUnsynced: finalUnsynced,
              timestamp: Date.now()
            },
            bubbles: true 
          });
          document.dispatchEvent(syncEvent);
          
          // Also dispatch on window for broader compatibility
          if (typeof window !== 'undefined') {
            window.dispatchEvent(syncEvent);
          }
          
          // Show a subtle notification without page reload
          self._showSyncNotification(finalUnsynced);
        } catch (e) {
          console.warn('[UnifiedSyncEngine] Event dispatch failed:', e);
        }
      }
      return { online: true, hadUnsynced: finalUnsynced };
    }).catch(function (err) {
      self.updateConnectionBanner();
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[UnifiedSyncEngine] sync error:', err);
      }
      return Promise.reject(err);
    });
  };

  UnifiedSyncEngine.prototype.syncAllModels = function () {
    if (!this.offlineSync || !this.offlineSync.syncAllModels) {
      return Promise.resolve({ hadUnsynced: 0 });
    }
    return this.offlineSync.syncAllModels({});
  };

  UnifiedSyncEngine.prototype.processPendingRequests = function () {
    if (!this.offlineSync || !this.offlineSync.processPendingRequests) {
      return Promise.resolve();
    }
    return this.offlineSync.processPendingRequests();
  };

  UnifiedSyncEngine.prototype.processNotifications = function () {
    if (!this.offlineSync || !this.offlineSync.processPendingNotifications) {
      return Promise.resolve();
    }
    return this.offlineSync.processPendingNotifications();
  };

  UnifiedSyncEngine.prototype.processEmails = function () {
    if (!this.offlineSync || !this.offlineSync.queuePendingEmail) {
      return Promise.resolve();
    }
    // Emails are processed as part of processAllPendingQueues; keep this as a thin wrapper.
    if (this.offlineSync.processAllPendingQueues) {
      return this.offlineSync.processAllPendingQueues();
    }
    return Promise.resolve();
  };

  UnifiedSyncEngine.prototype.processSms = function () {
    if (!this.offlineSync || !this.offlineSync.queuePendingSms) {
      return Promise.resolve();
    }
    // SMS are processed as part of processAllPendingQueues; keep this as a thin wrapper.
    if (this.offlineSync.processAllPendingQueues) {
      return this.offlineSync.processAllPendingQueues();
    }
    return Promise.resolve();
  };

  // Expose globally
  global.UnifiedSyncEngine = UnifiedSyncEngine;

  // Create a default instance when OfflineSync is present (most pages)
  if (!global.unifiedSyncEngine && global.OfflineSync) {
    try {
      global.unifiedSyncEngine = new UnifiedSyncEngine(global.OfflineSync);
    } catch (e) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[UnifiedSyncEngine] init failed:', e);
      }
    }
  }

})(typeof window !== 'undefined' ? window : this);

