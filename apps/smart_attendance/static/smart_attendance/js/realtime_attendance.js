/**
 * Realtime attendance – polls /api/attendance/realtime/ every 3 seconds.
 * Updates table dynamically without refreshing page.
 */
(function() {
  var POLL_INTERVAL_MS = 3000;

  function updateDashboard(data) {
    var setText = function(id, value) {
      var el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    if (data.total_employees !== undefined) setText('card-total-employees', data.total_employees);
    if (data.present_today !== undefined) setText('card-present-today', data.present_today);
    if (data.absent_today !== undefined) setText('card-absent-today', data.absent_today);
    if (data.late_arrivals !== undefined) setText('card-late-arrivals', data.late_arrivals);
    if (data.online_devices !== undefined) setText('card-online-devices', data.online_devices);
    if (data.offline_devices !== undefined) setText('card-offline-devices', data.offline_devices);

    var tbody = document.getElementById('live-attendance-body');
    if (!tbody) return;
    if (!data.recent_logs || !data.recent_logs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No recent logs.</td></tr>';
      return;
    }
    var rows = data.recent_logs.map(function(row) {
      var photoHtml = row.employee_photo
        ? '<img src="' + row.employee_photo + '" class="rounded-circle" width="32" height="32" alt="">'
        : '<div class="rounded-circle bg-secondary d-inline-flex align-items-center justify-content-center text-white" style="width:32px;height:32px;font-size:0.75rem;">' +
          (row.employee_name ? row.employee_name.charAt(0) : '?') + '</div>';
      return '<tr><td>' + row.employee_name + '</td><td>' + photoHtml + '</td><td>' +
        row.punch_time + '</td><td>' + row.punch_type + '</td><td>' + row.device_name + '</td></tr>';
    });
    tbody.innerHTML = rows.join('');
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      poll();
      setInterval(poll, POLL_INTERVAL_MS);
    });
  } else {
    poll();
    setInterval(poll, POLL_INTERVAL_MS);
  }
})();
