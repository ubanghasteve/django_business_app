(function() {
  var lastPunchTime = null;
  var audioBuffer = null;
  var audioContext = null;
  var SOUND_ENABLED_KEY = 'notification_sound_enabled';

  function isSoundEnabled() {
    try {
      return localStorage.getItem(SOUND_ENABLED_KEY) === 'true';
    } catch (e) {
      return false;
    }
  }

  function initAudioContext() {
    try {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioContext.state === 'suspended') {
        audioContext.resume();
      }
      return audioContext;
    } catch (e) {
      return null;
    }
  }

  function playNotificationSound() {
    if (!isSoundEnabled()) return;
    
    try {
      var ctx = initAudioContext();
      if (!ctx) return;

      if (audioBuffer) {
        playFromBuffer();
        return;
      }

      var request = new XMLHttpRequest();
      request.open('GET', '/static/sounds/notification.mp3', true);
      request.responseType = 'arraybuffer';
      request.onload = function() {
        if (request.status === 200) {
          ctx.decodeAudioData(request.response, function(buffer) {
            audioBuffer = buffer;
            playFromBuffer();
          }, function() {});
        }
      };
      request.send();
    } catch (e) {}
  }

  function playFromBuffer() {
    if (!audioBuffer || !audioContext) return;
    try {
      var source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      source.start(0);
    } catch (e) {}
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value != null && value !== undefined ? value : '';
  }

  function updateDashboard(data) {
    if (!data) return;
    setText('card-total-employees', data.total_employees);
    setText('card-present-today', data.present_today);
    setText('card-absent-today', data.absent_today);
    setText('card-late-arrivals', data.late_arrivals);
    setText('card-online-devices', data.online_devices);
    setText('card-offline-devices', data.offline_devices);

    var tbody = document.getElementById('live-attendance-body');
    if (!tbody) return;
    if (!data.recent_logs || !data.recent_logs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No recent logs.</td></tr>';
      return;
    }

    // Check for new attendance and play sound
    var latestPunch = data.recent_logs[0];
    if (latestPunch && latestPunch.punch_time && latestPunch.punch_time !== lastPunchTime) {
      if (lastPunchTime !== null) {
        playNotificationSound();
      }
      lastPunchTime = latestPunch.punch_time;
    }

    var rows = data.recent_logs.map(function(row) {
      var photoHtml = row.employee_photo
        ? '<img src="' + row.employee_photo + '" class="rounded-circle" width="32" height="32" alt="">'
        : '<div class="rounded-circle bg-secondary d-inline-flex align-items-center justify-content-center text-white" style="width:32px;height:32px;font-size:0.75rem;">' +
          (row.employee_name ? row.employee_name.charAt(0) : '?') +
          '</div>';
      
      var punchBadge = '';
      var punchType = (row.punch_type || '').toLowerCase();
      if (punchType === 'check in' || punchType === 'clock in') {
        punchBadge = '<span class="badge bg-success ms-1">IN</span>';
      } else if (punchType === 'check out' || punchType === 'clock out') {
        punchBadge = '<span class="badge bg-warning text-dark ms-1">OUT</span>';
      }
      
      return (
        '<tr>' +
          '<td>' + row.employee_name + '</td>' +
          '<td>' + photoHtml + '</td>' +
          '<td>' + row.punch_time + '</td>' +
          '<td>' + row.punch_type + punchBadge + '</td>' +
          '<td>' + (row.device_name || '—') + '</td>' +
        '</tr>'
      );
    });
    tbody.innerHTML = rows.join('');
  }

  function updateDevices(devices) {
    var loading = document.getElementById('devices-loading');
    var list = document.getElementById('devices-list');
    var countEl = document.getElementById('device-count');
    if (!loading || !list) return;
    
    if (countEl) countEl.textContent = devices ? devices.length : 0;
    
    if (!devices || !devices.length) {
      loading.textContent = 'No devices registered yet. Add a device to start tracking attendance.';
      loading.classList.remove('d-none');
      list.classList.add('d-none');
      return;
    }
    loading.classList.add('d-none');
    list.classList.remove('d-none');
    list.innerHTML = devices.map(function(d) {
      var badge = d.status === 'online' ? 'bg-success' : (d.status === 'offline' ? 'bg-danger' : 'bg-secondary');
      var statusText = d.status ? d.status.charAt(0).toUpperCase() + d.status.slice(1) : '—';
      var ipText = d.ip_address ? d.ip_address + ':' + (d.port || 4370) : 'Push only';
      return '<li class="list-group-item d-flex justify-content-between align-items-center">' +
        '<div><strong>' + (d.device_name || '—') + '</strong><br><small class="text-muted">' + ipText + '</small></div>' +
        '<span class="badge ' + badge + '">' + statusText + '</span></li>';
    }).join('');
    
    // Update device stats
    updateDeviceStats(devices);
  }

  function updateDeviceStats(devices) {
    var tbody = document.getElementById('device-stats-body');
    if (!tbody || !devices || !devices.length) {
      if (tbody) tbody.innerHTML = '<tr><td colspan="2" class="text-muted text-center py-2">No devices</td></tr>';
      return;
    }
    
    // For now, show device list - in real implementation, would fetch per-device stats
    tbody.innerHTML = devices.map(function(d) {
      var badge = d.status === 'online' ? 'bg-success' : (d.status === 'offline' ? 'bg-danger' : 'bg-secondary');
      return '<tr>' +
        '<td><span class="badge ' + badge + ' me-1">' + (d.status || '?') + '</span> ' + (d.device_name || '—') + '</td>' +
        '<td><small class="text-muted">' + (d.ip_address || 'Push only') + '</small></td>' +
        '</tr>';
    }).join('');
  }

  function poll() {
    fetch('/api/attendance/realtime', {
      method: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      cache: 'no-store'
    })
      .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
      .then(updateDashboard)
      .catch(function() {});
  }

  function loadDevices() {
    fetch('/api/attendance/device-status', {
      method: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      cache: 'no-store'
    })
      .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
      .then(updateDevices)
      .catch(function() {
        var loading = document.getElementById('devices-loading');
        if (loading) { loading.textContent = 'No devices registered yet.'; }
      });
  }

  function init() {
    poll();
    loadDevices();
    setInterval(poll, 2000);
    setInterval(loadDevices, 5000); // Refresh devices less frequently
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

