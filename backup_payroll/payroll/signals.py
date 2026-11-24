from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from apps.accounts.models import UserActivity
from apps.core.ownership import get_account_for_user
from apps.notifications.services import create_notification, get_company_admin_and_visibility_recipients

from .models import PayrollRun, Payslip


User = get_user_model()


def _log_activity(user, account, activity_type, description, app_name, model_name, obj):
    UserActivity.log_activity(
        user=user,
        account=account,
        activity_type=activity_type,
        description=description,
        app_name=app_name,
        model_name=model_name,
        object_id=str(getattr(obj, "pk", "")),
        object_repr=str(obj),
        url_path="",
        http_method="",
        ip_address=None,
        extra_data={},
    )


@receiver(post_save, sender=PayrollRun)
def payroll_run_activity_notifications(sender, instance: PayrollRun, created, **kwargs):
    """
    Activity + notifications for payroll lifecycle events.
    """
    actor = instance.created_by
    account = instance.account or (get_account_for_user(actor) if actor else None)
    if not account:
        return

    if created:
        desc = f"Payroll run created for period {instance.period}."
        _log_activity(
            actor,
            account,
            "CREATE",
            desc,
            "payroll",
            "PayrollRun",
            instance,
        )
        recipients = get_company_admin_and_visibility_recipients(account)
        for user in recipients:
            create_notification(
                user=user,
                account=account,
                source_app="payroll",
                title="Payroll Generated",
                message=desc,
                actor=actor,
                action_url="",
                target_type="payroll_run",
                target_id=instance.id,
            )
    else:
        # Status-based notifications
        if instance.status == "approved":
            title = "Payroll Approved"
            msg = f"Payroll run for period {instance.period} has been approved."
        elif instance.status == "paid":
            title = "Payroll Paid"
            msg = f"Payroll run for period {instance.period} has been marked as paid."
        else:
            return
        _log_activity(
            actor,
            account,
            "UPDATE",
            msg,
            "payroll",
            "PayrollRun",
            instance,
        )
        recipients = get_company_admin_and_visibility_recipients(account)
        for user in recipients:
            create_notification(
                user=user,
                account=account,
                source_app="payroll",
                title=title,
                message=msg,
                actor=actor,
                action_url="",
                target_type="payroll_run",
                target_id=instance.id,
            )


@receiver(post_save, sender=Payslip)
def payslip_activity_notifications(sender, instance: Payslip, created, **kwargs):
    """
    Activity + notification when a payslip is generated.
    """
    actor = instance.created_by
    account = instance.account or (get_account_for_user(actor) if actor else None)
    if not account:
        return
    employee = instance.employee
    desc = f"Payslip generated for {employee.full_name} – period {instance.period}."
    _log_activity(
        actor,
        account,
        "CREATE",
        desc,
        "payroll",
        "Payslip",
        instance,
    )
    # Notify employee if they have a linked portal user
    linked_user = getattr(employee, "linked_user", None)
    if linked_user and isinstance(linked_user, User):
        create_notification(
            user=linked_user,
            account=account,
            source_app="payroll",
            title="Payslip Ready",
            message="Your payslip is now available.",
            actor=actor,
            action_url="",
            target_type="payslip",
            target_id=instance.id,
        )

