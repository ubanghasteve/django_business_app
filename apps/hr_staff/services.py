# -*- coding: utf-8 -*-
"""
HR employee account services: create portal user, reset password, get/create Employee role.

Security:
- HR cannot assign permissions outside HR scope (enforced by permission_boundaries in role form).
- HR cannot edit Account or CompanyProfile; cannot delete User directly.
- Employee role has full_company_visibility=False so employees see only their own data via querysets.
"""
import secrets
import string
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.core.models import Account
from apps.accounts.models import AccountGroup
from apps.accounts.services import (
    create_account_group,
    assign_user_to_account_group,
    set_user_account_role,
)

from .models import Employee

User = get_user_model()

# Role name for employees with portal access. full_company_visibility=False.
EMPLOYEE_ROLE_NAME = 'Employee'

# Permissions for Employee role: view own HR dashboard (portal), view/edit own profile, view/create own leave. No HR-only perms.
EMPLOYEE_ROLE_PERMISSION_CODENAMES = [
    'hr_staff.view_own_hr_dashboard',  # so employee can open HR & Staff and see their dashboard (My Profile, My Leave)
    'hr_staff.view_department',   # e.g. show department name on profile
    'hr_staff.view_employee',
    'hr_staff.change_employee',
    'hr_staff.view_leaverequest',
    'hr_staff.add_leaverequest',
    'core.view_companyprofile',
]


def get_or_create_employee_role(account: Account) -> AccountGroup:
    """
    Get or create the "Employee" role for an account.
    full_company_visibility=False so visibility is enforced by queryset (self-only).
    Ensures view_own_hr_dashboard is on the role so employees can access the portal.
    """
    ag = AccountGroup.objects.filter(
        account=account,
        role_name=EMPLOYEE_ROLE_NAME,
    ).select_related('group').first()
    if ag:
        # Ensure Employee role has view_own_hr_dashboard (for existing roles created before we added it)
        from apps.accounts.services import update_account_group_permissions
        existing = set(ag.group.permissions.values_list('content_type__app_label', 'codename'))
        if ('hr_staff', 'view_own_hr_dashboard') not in existing:
            current = [f"{p.content_type.app_label}.{p.codename}" for p in ag.group.permissions.all()]
            merged = set(current) | set(EMPLOYEE_ROLE_PERMISSION_CODENAMES)
            update_account_group_permissions(ag, list(merged))
        return ag
    return create_account_group(
        account=account,
        role_name=EMPLOYEE_ROLE_NAME,
        permission_codenames=EMPLOYEE_ROLE_PERMISSION_CODENAMES,
    )


def _generate_temporary_password(length=12):
    """Generate a secure temporary password (letters + digits)."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@transaction.atomic
def create_employee_portal_user(
    employee: Employee,
    temporary_password: str | None = None,
) -> tuple[User, str]:
    """
    Create a Django User for the employee and link it.

    - User email from employee.email (must be unique and not empty).
    - User account = employee.account.
    - Assigns Employee role (full_company_visibility=False).
    - Sets employee.linked_user, employee.is_portal_user = True.
    - Returns (user, password). If temporary_password is None, generates one; caller must show/send it once (HR never sees it again).

    Raises ValueError if employee already has linked_user or email is missing/duplicate.
    """
    if employee.linked_user_id:
        raise ValueError('Employee already has portal access.')
    email = (employee.email or '').strip()
    if not email:
        raise ValueError('Employee must have an email to create portal access.')
    if User.objects.filter(email__iexact=email).exists():
        raise ValueError('A user with this email already exists.')
    account = employee.account
    if not account:
        raise ValueError('Employee must belong to an account.')
    password = temporary_password or _generate_temporary_password()
    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=employee.first_name or '',
        last_name=employee.last_name or '',
        account=account,
        is_staff=False,
        is_active=True,
    )
    user.force_password_change = True  # Force change on first login; never reveal temp password again.
    user.save(update_fields=['force_password_change'])
    employee_role = get_or_create_employee_role(account)
    set_user_account_role(user, employee_role)
    employee.linked_user = user
    employee.is_portal_user = True
    employee.portal_created_by_hr = True  # HR created this account; HR may reset password
    employee.save(update_fields=['linked_user', 'is_portal_user', 'portal_created_by_hr'])
    return user, password


def reset_employee_password(employee: Employee, new_password: str | None = None) -> str:
    """
    Reset the linked User's password. If new_password is None, generates a temporary one.
    Returns the new password (caller shows/sends once; HR never sees it after).

    Raises ValueError if employee has no linked_user.
    """
    if not employee.linked_user_id:
        raise ValueError('Employee does not have portal access.')
    user = employee.linked_user
    password = new_password or _generate_temporary_password()
    user.set_password(password)
    user.save(update_fields=['password'])
    return password


def set_employee_account_active(employee: Employee, active: bool) -> None:
    """Enable or disable the linked User's login (is_active). No-op if no linked_user."""
    if not employee.linked_user_id:
        return
    User.objects.filter(pk=employee.linked_user_id).update(is_active=active)


# ----- Email Notifications -----

def send_hr_email(to_email: str, subject: str, message: str, from_email: str = None, html_message: str = None) -> bool:
    """
    Send an email for HR notifications.
    Returns True if email was sent successfully, False otherwise.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.core.mail.message import EmailMessage
    
    if not to_email:
        return False
    
    sender = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    
    try:
        if html_message:
            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email=sender,
                to=[to_email],
            )
            email.content_subtype = 'html'
            email.send(fail_silently=False)
        else:
            send_mail(
                subject=subject,
                message=message,
                from_email=sender,
                recipient_list=[to_email],
                fail_silently=False,
            )
        return True
    except Exception:
        return False


def notify_leave_status(leave_request, status: str, base_url: str = None) -> bool:
    """
    Send email notification to employee when their leave request is approved or rejected.
    Returns True if email was sent, False otherwise.
    """
    employee = leave_request.employee
    if not employee or not employee.email:
        return False
    
    employee_name = employee.full_name
    leave_type = leave_request.get_leave_type_display() if leave_request.leave_type else 'Leave'
    start_date = leave_request.start_date.strftime('%B %d, %Y') if leave_request.start_date else ''
    end_date = leave_request.end_date.strftime('%B %d, %Y') if leave_request.end_date else ''
    days_requested = leave_request.total_days or 0
    
    status_display = 'Approved' if status == 'approved' else 'Rejected'
    status_color = '28a745' if status == 'approved' else 'dc3545'
    
    subject = f'Leave Request {status_display} - {leave_type}'
    
    leave_url = f'{base_url}/hr-staff/leave/{leave_request.pk}/' if base_url else ''
    
    html_message = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #{status_color};">Leave Request {status_display}</h2>
        <p>Dear {employee_name},</p>
        <p>Your leave request has been <strong>{status_display.lower()}</strong>.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Leave Type</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{leave_type}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Start Date</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{start_date}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>End Date</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{end_date}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Days Requested</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{days_requested}</td>
            </tr>
        </table>
        {"<p>You can view the details of your leave request by logging into the HR portal.</p>" if leave_url else ""}
        <p style="color: #666; font-size: 12px; margin-top: 30px;">
            This is an automated notification from the HR Portal. Please do not reply to this email.
        </p>
    </div>
    """
    
    message = f"""Dear {employee_name},

Your leave request has been {status_display.lower()}.

Leave Type: {leave_type}
Start Date: {start_date}
End Date: {end_date}
Days Requested: {days_requested}

You can view the details of your leave request by logging into the HR portal.

This is an automated notification from the HR Portal. Please do not reply to this email.
"""
    
    return send_hr_email(employee.email, subject, message, html_message=html_message)


def notify_training_enrollment(enrollment, base_url: str = None) -> bool:
    """
    Send email notification to employee when they are enrolled in a training course.
    Returns True if email was sent, False otherwise.
    """
    employee = enrollment.employee
    if not employee or not employee.email:
        return False
    
    course = enrollment.course
    if not course:
        return False
    
    employee_name = employee.full_name
    course_title = course.title
    course_category = course.category or 'General'
    duration = course.duration_hours or 0
    
    enrollment_date = enrollment.enrolled_date.strftime('%B %d, %Y') if enrollment.enrolled_date else ''
    
    subject = f'Training Enrollment - {course_title}'
    
    course_url = f'{base_url}/hr-staff/training/{course.pk}/' if base_url else ''
    
    html_message = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1976d2;">New Training Enrollment</h2>
        <p>Dear {employee_name},</p>
        <p>You have been enrolled in a new training course.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Course Title</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{course_title}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Category</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{course_category}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Duration</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{duration} hours</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Enrolled Date</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{enrollment_date}</td>
            </tr>
        </table>
        {"<p>You can view the course details by logging into the HR portal.</p>" if course_url else ""}
        <p style="color: #666; font-size: 12px; margin-top: 30px;">
            This is an automated notification from the HR Portal. Please do not reply to this email.
        </p>
    </div>
    """
    
    message = f"""Dear {employee_name},

You have been enrolled in a new training course.

Course Title: {course_title}
Category: {course_category}
Duration: {duration} hours
Enrolled Date: {enrollment_date}

You can view the course details by logging into the HR Portal.

This is an automated notification from the HR Portal. Please do not reply to this email.
"""
    
    return send_hr_email(employee.email, subject, message, html_message=html_message)


def notify_performance_review(review, base_url: str = None) -> bool:
    """
    Send email notification to employee when a performance review is created or completed.
    Returns True if email was sent, False otherwise.
    """
    employee = review.employee
    if not employee or not employee.email:
        return False
    
    employee_name = employee.full_name
    review_period = review.review_period or 'Current Period'
    status = review.get_status_display() if review.status else 'Pending'
    
    subject = f'Performance Review - {review_period}'
    
    review_url = f'{base_url}/hr-staff/performance/{review.pk}/' if base_url else ''
    
    html_message = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1976d2;">Performance Review</h2>
        <p>Dear {employee_name},</p>
        <p>You have a new performance review.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Review Period</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{review_period}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Status</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{status}</td>
            </tr>
        </table>
        {"<p>You can view the review details by logging into the HR portal.</p>" if review_url else ""}
        <p style="color: #666; font-size: 12px; margin-top: 30px;">
            This is an automated notification from the HR Portal. Please do not reply to this email.
        </p>
    </div>
    """
    
    message = f"""Dear {employee_name},

You have a new performance review.

Review Period: {review_period}
Status: {status}

You can view the review details by logging into the HR Portal.

This is an automated notification from the HR Portal. Please do not reply to this email.
"""
    
    return send_hr_email(employee.email, subject, message, html_message=html_message)
