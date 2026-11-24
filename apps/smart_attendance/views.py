from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from apps.core.ownership import get_account_for_user
from apps.core.permissions import company_admin_or_permission_required

from .analytics_engine import update_analytics_for_employee
from .device_authentication import authenticate_device, DeviceAuthenticationError
from .device_manager import (
    list_devices_for_user,
    recover_offline_device,
    trigger_device_discovery_for_user,
)
from .device_push_gateway import handle_biometric_push
from .forms import BiometricDeviceForm, EmployeeForm
from .models import (
    AttendanceAnalytics,
    AttendanceLog,
    BiometricDevice,
    DailyAttendance,
    Employee,
)
from .permissions import IsCompanyAdminOrModelPermission
from .serializers import (
    AttendanceLogSerializer,
    BiometricBatchPushSerializer,
    BiometricDeviceSerializer,
    BiometricPushSerializer,
    DailyAttendanceSerializer,
)


# ---------------------------------------------------------------------------
# Web dashboard and management views
# ---------------------------------------------------------------------------


def _get_tenant_for_request(request):
    return get_account_for_user(request.user)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_attendance_dashboard", raise_exception=True)
def dashboard(request):
    """
    Attendance dashboard: shell-only for instant load.
    No DB queries here - all data loads via AJAX from /api/attendance/realtime and /api/attendance/device-status.
    """
    context = {
        "total_employees": 0,
        "devices": [],
    }
    return render(request, "smart_attendance/dashboard.html", context)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_biometricdevice", raise_exception=True)
def devices(request):
    tenant = _get_tenant_for_request(request)
    qs = BiometricDevice.objects.filter(tenant=tenant).order_by("device_name")
    context = {"devices": qs}
    return render(request, "smart_attendance/devices.html", context)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_biometricdevice", raise_exception=True)
def device_detail(request, pk):
    tenant = _get_tenant_for_request(request)
    device = get_object_or_404(BiometricDevice, pk=pk, tenant=tenant)
    recent_logs = AttendanceLog.objects.filter(device=device).select_related("employee").order_by("-punch_time")[:50]
    context = {
        "device": device,
        "recent_logs": recent_logs,
    }
    return render(request, "smart_attendance/device_detail.html", context)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.add_biometricdevice", raise_exception=True)
def register_device(request):
    tenant = _get_tenant_for_request(request)
    if request.method == "POST":
        form = BiometricDeviceForm(request.POST)
        if form.is_valid():
            device = form.save(commit=False)
            device.tenant = tenant
            device.save()
            messages.success(request, "Biometric device registered successfully.")
            return redirect("smart_attendance:device_setup_complete", pk=device.pk)
    else:
        form = BiometricDeviceForm()
    return render(request, "smart_attendance/device_form.html", {"form": form})


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_biometricdevice", raise_exception=True)
def device_setup_complete(request, pk):
    """
    Post-registration setup page – shows exact push URL and config for real-time sync.
    """
    tenant = _get_tenant_for_request(request)
    device = get_object_or_404(BiometricDevice, pk=pk, tenant=tenant)
    host = request.get_host()
    is_localhost = host.startswith("127.0.0.1") or host.startswith("localhost") or host == "localhost"
    push_base = getattr(settings, "BIOMETRIC_PUSH_BASE_URL", None)
    if push_base:
        push_url = f"{push_base.rstrip('/')}/api/biometric/push"
    else:
        push_url = f"{request.scheme}://{host}/api/biometric/push"
    context = {
        "device": device,
        "push_url": push_url,
        "is_localhost": is_localhost,
    }
    return render(request, "smart_attendance/device_setup_complete.html", context)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_employee", raise_exception=True)
def employees(request):
    tenant = _get_tenant_for_request(request)
    qs = Employee.objects.filter(tenant=tenant).order_by("last_name", "first_name")
    return render(request, "smart_attendance/employees.html", {"employees": qs})


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.add_employee", raise_exception=True)
def create_employee(request):
    tenant = _get_tenant_for_request(request)
    if request.method == "POST":
        form = EmployeeForm(request.POST, request.FILES)
        if form.is_valid():
            employee = form.save(commit=False)
            employee.tenant = tenant
            employee.save()
            messages.success(request, "Employee created successfully.")
            return redirect("smart_attendance:employees")
    else:
        form = EmployeeForm()
    return render(request, "smart_attendance/employee_form.html", {"form": form, "action": "Create"})


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.change_employee", raise_exception=True)
def edit_employee(request, pk):
    tenant = _get_tenant_for_request(request)
    employee = get_object_or_404(Employee, pk=pk, tenant=tenant)
    if request.method == "POST":
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Employee updated successfully.")
            return redirect("smart_attendance:employee_profile", pk=employee.pk)
    else:
        form = EmployeeForm(instance=employee)
    return render(request, "smart_attendance/employee_form.html", {"form": form, "employee": employee, "action": "Edit"})


@login_required
@never_cache
def employee_profile(request, pk):
    """
    Employee profile page.
    - HR/Admin: needs smart_attendance.view_employee
    - Normal employee: can view own attendance via view_own_attendance
    """
    tenant = _get_tenant_for_request(request)
    employee = get_object_or_404(Employee, pk=pk, tenant=tenant)

    is_self = getattr(employee.hr_employee, "linked_user_id", None) == request.user.id if getattr(employee, "hr_employee", None) else False
    if not request.user.has_perm("smart_attendance.view_employee"):
        if not (is_self and request.user.has_perm("smart_attendance.view_own_attendance")):
            return HttpResponse(status=403)

    today = timezone.localdate()
    daily = DailyAttendance.objects.filter(employee=employee, date=today).first()
    recent_logs = AttendanceLog.objects.filter(employee=employee).select_related("device").order_by("-punch_time")[:100]
    context = {
        "employee": employee,
        "today": daily,
        "recent_logs": recent_logs,
    }
    return render(request, "smart_attendance/employee_profile.html", context)


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_attendancelog", raise_exception=True)
def attendance_logs(request):
    tenant = _get_tenant_for_request(request)
    logs = (
        AttendanceLog.objects.select_related("employee", "device")
        .filter(employee__tenant=tenant)
        .order_by("-punch_time")[:500]
    )
    return render(request, "smart_attendance/attendance_logs.html", {"logs": logs})


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_dailyattendance", raise_exception=True)
def daily_attendance_view(request):
    tenant = _get_tenant_for_request(request)
    target_date_str = request.GET.get("date")
    if target_date_str:
        target_date = date.fromisoformat(target_date_str)
    else:
        target_date = timezone.localdate()
    records = (
        DailyAttendance.objects.select_related("employee")
        .filter(employee__tenant=tenant, date=target_date)
        .order_by("employee__last_name", "employee__first_name")
    )
    return render(
        request,
        "smart_attendance/daily_attendance.html",
        {"records": records, "target_date": target_date},
    )


@login_required
@never_cache
@company_admin_or_permission_required("smart_attendance.view_attendanceanalytics", raise_exception=True)
def analytics_view(request):
    tenant = _get_tenant_for_request(request)
    period = request.GET.get("period") or AttendanceAnalytics.PERIOD_DAILY
    today = timezone.localdate()
    analytics = (
        AttendanceAnalytics.objects.select_related("employee")
        .filter(employee__tenant=tenant, period=period, date__lte=today)
        .order_by("-date")[:500]
    )
    return render(
        request,
        "smart_attendance/analytics.html",
        {"analytics": analytics, "period": period},
    )


# ---------------------------------------------------------------------------
# Export views
# ---------------------------------------------------------------------------


@login_required
@company_admin_or_permission_required("smart_attendance.export_attendance", raise_exception=True)
def export_daily_attendance_csv(request):
    import csv

    tenant = _get_tenant_for_request(request)
    target_date_str = request.GET.get("date")
    if target_date_str:
        target_date = date.fromisoformat(target_date_str)
    else:
        target_date = timezone.localdate()
    records = (
        DailyAttendance.objects.select_related("employee")
        .filter(employee__tenant=tenant, date=target_date)
        .order_by("employee__last_name", "employee__first_name")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="daily_attendance_{target_date}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Employee ID",
            "Name",
            "Date",
            "First Check-in",
            "Last Check-out",
            "Total Hours",
            "Punch Count",
            "Status",
        ]
    )
    for r in records:
        writer.writerow(
            [
                r.employee.employee_id,
                f"{r.employee.first_name} {r.employee.last_name}",
                r.date.isoformat(),
                r.first_check_in.isoformat() if r.first_check_in else "",
                r.last_check_out.isoformat() if r.last_check_out else "",
                r.total_hours.total_seconds() / 3600 if r.total_hours else "",
                r.punch_count,
                r.get_status_display(),
            ]
        )
    return response


@login_required
@company_admin_or_permission_required("smart_attendance.export_attendance", raise_exception=True)
def export_attendance_analytics_excel(request):
    import openpyxl

    tenant = _get_tenant_for_request(request)
    period = request.GET.get("period") or AttendanceAnalytics.PERIOD_MONTHLY
    analytics = (
        AttendanceAnalytics.objects.select_related("employee")
        .filter(employee__tenant=tenant, period=period)
        .order_by("-date")[:2000]
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance Analytics"
    ws.append(
        [
            "Employee ID",
            "Name",
            "Period Start",
            "Period",
            "Times Entered",
            "Times Exited",
            "Work Hours",
            "Late Minutes",
            "Overtime Minutes",
        ]
    )
    for a in analytics:
        ws.append(
            [
                a.employee.employee_id,
                f"{a.employee.first_name} {a.employee.last_name}",
                a.date.isoformat(),
                a.get_period_display(),
                a.times_entered,
                a.times_exited,
                a.work_hours.total_seconds() / 3600 if a.work_hours else "",
                a.late_minutes,
                a.overtime_minutes,
            ]
        )
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response[
        "Content-Disposition"
    ] = f'attachment; filename="attendance_analytics_{period}.xlsx"'
    wb.save(response)
    return response


# ---------------------------------------------------------------------------
# REST APIs
# ---------------------------------------------------------------------------


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def biometric_push_api(request):
    """
    Biometric push API gateway – flexible, accepts all device formats.

    Supports: JSON, form data, query params. device_serial from body/header/SN.
    device_secret from body/X-Device-Secret. uid from uid/biometric_uid/user_id/PIN.
    Preserves ALL extra fields. Falls back to strict serializer if flexible parse fails.
    """
    from .payload_parser import parse_push_payload

    payload, device_serial, device_secret, err = parse_push_payload(request)
    if payload is not None:
        try:
            handle_biometric_push(payload, device_secret or "")
            return Response({"status": "ok"}, status=200)
        except DeviceAuthenticationError as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

    # Parsing failed – return parser error so device/app get a clear reason
    if err:
        return Response({"detail": err}, status=400)

    # Fallback: strict serializer for standard JSON
    serializer = BiometricPushSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            serializer.errors if not err else {"detail": err, "errors": serializer.errors},
            status=400,
        )

    device_secret = (
        request.headers.get("X-Device-Secret")
        or request.data.get("device_secret")
        or ""
    )
    payload = dict(serializer.validated_data)
    payload["device_serial"] = serializer.validated_data["device_serial"]
    raw = dict(request.data) if hasattr(request, "data") and request.data else {}
    for k, v in raw.items():
        if k not in payload:
            payload[k] = v

    try:
        handle_biometric_push(payload, device_secret)
    except DeviceAuthenticationError as exc:
        return Response({"detail": str(exc)}, status=403)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)

    return Response({"status": "ok"}, status=200)


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def biometric_push_batch_api(request):
    """
    Batch biometric push API – flexible, accepts logs in any format.

    Supports: logs, log, data, records, attendance, etc. Preserves all extra fields.
    Falls back to strict serializer if flexible parse fails.
    Handles offline device recovery - when device reconnects, it sends historical logs.
    """
    from .batch_payload_parser import parse_batch_push_payload

    device_serial, device_secret, logs, err = parse_batch_push_payload(request)
    if device_serial is not None and logs is not None:
        if not logs:
            return Response({"status": "ok", "message": "No valid logs to process"}, status=200)
        try:
            device = authenticate_device(device_serial, device_secret or "")
            # Update device status to online when receiving batch push
            device.status = BiometricDevice.STATUS_ONLINE
            device.last_seen = timezone.now()
            device.save(update_fields=["status", "last_seen"])
            recover_offline_device(device, logs)
            return Response(
                {"status": "ok", "message": "Batch processed", "count": len(logs)},
                status=200,
            )
        except DeviceAuthenticationError as exc:
            return Response({"detail": str(exc)}, status=403)

    # Fallback: strict serializer
    serializer = BiometricBatchPushSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            serializer.errors if not err else {"detail": err, "errors": serializer.errors},
            status=400,
        )

    device_secret = (
        request.headers.get("X-Device-Secret")
        or request.data.get("device_secret")
        or ""
    )
    device_serial = serializer.validated_data["device_serial"]
    raw_logs = serializer.validated_data["logs"]

    try:
        device = authenticate_device(device_serial, device_secret)
    except DeviceAuthenticationError as exc:
        return Response({"detail": str(exc)}, status=403)

    # Update device status to online when receiving batch push
    device.status = BiometricDevice.STATUS_ONLINE
    device.last_seen = timezone.now()
    device.save(update_fields=["status", "last_seen"])

    logs = []
    raw_list = []
    if hasattr(request, "data") and request.data and isinstance(request.data.get("logs"), list):
        raw_list = request.data["logs"]
    for i, log in enumerate(raw_logs):
        payload = dict(log)
        payload["device_serial"] = device_serial
        if i < len(raw_list) and isinstance(raw_list[i], dict):
            for k, v in raw_list[i].items():
                if k not in payload:
                    payload[k] = v
        logs.append(payload)

    recover_offline_device(device, logs)

    return Response(
        {"status": "ok", "message": "Batch processed", "count": len(logs)},
        status=200,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCompanyAdminOrModelPermission])
def devices_api(request):
    tenant = _get_tenant_for_request(request)
    qs = BiometricDevice.objects.filter(tenant=tenant).order_by("device_name")
    data = BiometricDeviceSerializer(qs, many=True).data
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsCompanyAdminOrModelPermission])
def devices_discover_api(request):
    """
    Trigger device auto-discovery for current tenant.
    """
    discovered = trigger_device_discovery_for_user(request.user, request)
    return Response({"discovered": discovered})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_live_api(request):
    """
    Lightweight live stats for AJAX polling (every 5s).
    """
    tenant = _get_tenant_for_request(request)
    today = timezone.localdate()

    employees_qs = Employee.objects.filter(tenant=tenant, is_active=True)
    total_employees = employees_qs.count()

    daily_qs = DailyAttendance.objects.filter(employee__tenant=tenant, date=today)
    present_count = daily_qs.exclude(status=DailyAttendance.STATUS_ABSENT).count()
    late_count = daily_qs.filter(status=DailyAttendance.STATUS_LATE).count()
    absent_count = max(total_employees - present_count, 0)

    devices_qs = BiometricDevice.objects.filter(tenant=tenant)
    online_devices = devices_qs.filter(status=BiometricDevice.STATUS_ONLINE).count()
    offline_devices = devices_qs.filter(status=BiometricDevice.STATUS_OFFLINE).count()

    # Last 20 logs for ticker
    recent_logs = (
        AttendanceLog.objects.select_related("employee", "device")
        .filter(employee__tenant=tenant)
        .order_by("-punch_time")[:20]
    )
    def _photo_url(emp):
        if not emp or not emp.profile_photo:
            return None
        try:
            return request.build_absolute_uri(emp.profile_photo.url)
        except Exception:
            return None

    recent_data = [
        {
            "employee_name": f"{log.employee.first_name} {log.employee.last_name}",
            "employee_photo": _photo_url(log.employee),
            "device_name": log.device.device_name if log.device else "",
            "punch_time": timezone.localtime(log.punch_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "punch_type": log.punch_type,
        }
        for log in recent_logs
    ]

    return Response(
        {
            "total_employees": total_employees,
            "present_today": present_count,
            "absent_today": absent_count,
            "late_arrivals": late_count,
            "online_devices": online_devices,
            "offline_devices": offline_devices,
            "recent_logs": recent_data,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_today_api(request):
    """
    Detailed per-employee view of today's attendance (used by dashboard modals).
    """
    tenant = _get_tenant_for_request(request)
    today = timezone.localdate()
    daily_qs = (
        DailyAttendance.objects.select_related("employee")
        .filter(employee__tenant=tenant, date=today)
        .order_by("employee__last_name", "employee__first_name")
    )
    data = DailyAttendanceSerializer(daily_qs, many=True).data
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_logs_api(request):
    """
    GET /api/attendance/logs/ – paginated attendance logs (tenant-scoped).
    """
    tenant = _get_tenant_for_request(request)
    limit = min(int(request.GET.get("limit", 100)), 500)
    logs = (
        AttendanceLog.objects.select_related("employee", "device")
        .filter(employee__tenant=tenant)
        .order_by("-punch_time")[:limit]
    )
    data = AttendanceLogSerializer(logs, many=True).data
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCompanyAdminOrModelPermission])
def attendance_employee_api(request, pk):
    """
    GET /api/attendance/employee/<id>/ – employee attendance profile.
    """
    tenant = _get_tenant_for_request(request)
    employee = get_object_or_404(Employee, pk=pk, tenant=tenant)
    today = timezone.localdate()
    daily = DailyAttendance.objects.filter(employee=employee, date=today).first()
    recent_logs = (
        AttendanceLog.objects.filter(employee=employee)
        .select_related("device")
        .order_by("-punch_time")[:50]
    )
    return Response(
        {
            "employee": {
                "id": employee.id,
                "employee_id": employee.employee_id,
                "full_name": f"{employee.first_name} {employee.last_name}",
                "department": employee.department,
                "position": employee.position,
            },
            "today": DailyAttendanceSerializer(daily).data if daily else None,
            "recent_logs": AttendanceLogSerializer(recent_logs, many=True).data,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_device_status_api(request):
    """
    GET /api/attendance/device-status/ – live device status for all tenant devices.
    """
    tenant = _get_tenant_for_request(request)
    devices = BiometricDevice.objects.filter(tenant=tenant).order_by("device_name")
    data = [
        {
            "id": d.id,
            "device_name": d.device_name,
            "ip_address": str(d.device_ip) if d.device_ip else "",
            "port": d.device_port,
            "status": d.status,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        }
        for d in devices
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_device_last_punch_api(request, device_id):
    """
    GET /api/attendance/device/<id>/last-punch/ – latest attendance log for a device (for setup/verify page).
    """
    tenant = _get_tenant_for_request(request)
    device = get_object_or_404(BiometricDevice, pk=device_id, tenant=tenant)
    log = (
        AttendanceLog.objects.filter(device=device)
        .select_related("employee")
        .order_by("-punch_time")
        .first()
    )
    if not log:
        return Response({"last_punch": None})
    return Response(
        {
            "last_punch": {
                "employee_name": f"{log.employee.first_name} {log.employee.last_name}".strip(),
                "punch_time": timezone.localtime(log.punch_time).strftime("%Y-%m-%d %H:%M:%S"),
                "punch_type": log.punch_type or "—",
            }
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_realtime_api(request):
    """
    GET /api/attendance/realtime/ – realtime dashboard data (poll every 3s).
    Same payload as /api/attendance/live/.
    """
    # Pass Django HttpRequest so attendance_live_api's @api_view doesn't double-wrap a DRF Request
    django_request = getattr(request, '_request', request)
    return attendance_live_api(django_request)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_report_api(request):
    """
    Report API for date range analytics.
    """
    tenant = _get_tenant_for_request(request)
    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    if not start_str or not end_str:
        return Response({"detail": "start and end are required"}, status=400)
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)

    records = (
        DailyAttendance.objects.select_related("employee")
        .filter(employee__tenant=tenant, date__gte=start, date__lte=end)
        .order_by("date", "employee__last_name", "employee__first_name")
    )
    data = DailyAttendanceSerializer(records, many=True).data
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_device_stats_api(request):
    """
    GET /api/attendance/device-stats/ – attendance counts by device for today.
    Shows how many punches each device has recorded today.
    """
    tenant = _get_tenant_for_request(request)
    today = timezone.localdate()
    
    devices = BiometricDevice.objects.filter(tenant=tenant).order_by("device_name")
    
    data = []
    for device in devices:
        punch_count = AttendanceLog.objects.filter(
            device=device,
            punch_time__date=today
        ).count()
        
        unique_employees = AttendanceLog.objects.filter(
            device=device,
            punch_time__date=today
        ).values('employee_id').distinct().count()
        
        data.append({
            "id": device.id,
            "device_name": device.device_name,
            "ip_address": str(device.device_ip) if device.device_ip else "",
            "port": device.device_port,
            "status": device.status,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "punch_count_today": punch_count,
            "unique_employees_today": unique_employees,
        })
    
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_offline_push_api(request):
    """
    API endpoint for offline attendance logs pushed from the web client.
    Accepts a list of attendance log entries to be saved when back online.
    """
    from .models import AttendanceLog, Employee, BiometricDevice
    
    data = request.data
    if not isinstance(data, dict):
        return Response({'error': 'Expected JSON object with logs array'}, status=400)
    
    logs = data.get('logs', [])
    if not logs:
        return Response({'error': 'No logs provided'}, status=400)
    
    account = get_account_for_user(request.user)
    if not account:
        return Response({'error': 'No account found'}, status=403)
    
    created_logs = []
    errors = []
    
    for log_entry in logs:
        try:
            employee_id = log_entry.get('employee_id')
            punch_time = log_entry.get('punch_time')
            punch_type = log_entry.get('punch_type', 'check-in')
            verify_mode = log_entry.get('verify_mode', 'offline')
            
            if not employee_id or not punch_time:
                errors.append({'error': 'Missing employee_id or punch_time', 'entry': log_entry})
                continue
            
            employee = Employee.objects.filter(
                tenant=account,
                employee_id=employee_id
            ).first()
            
            if not employee:
                errors.append({'error': f'Employee not found: {employee_id}', 'entry': log_entry})
                continue
            
            from django.utils.dateparse import parse_datetime
            if isinstance(punch_time, str):
                punch_time = parse_datetime(punch_time)
            
            if not punch_time:
                from datetime import datetime
                punch_time = datetime.now()
            
            attendance_log = AttendanceLog.objects.create(
                employee=employee,
                device=None,
                punch_time=punch_time,
                punch_type=punch_type,
                verify_mode=verify_mode,
                is_duplicate=False
            )
            created_logs.append(attendance_log.id)
            
        except Exception as e:
            errors.append({'error': str(e), 'entry': log_entry})
    
    return Response({
        'success': True,
        'created_count': len(created_logs),
        'created_ids': created_logs,
        'errors': errors
    })

