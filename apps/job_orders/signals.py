from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from apps.core.models import CompanyProfile, Account
from apps.accounts.models import User
from .models import Product, Order


def _product_account(product):
    """Resolve account for a Product (job order) for activity logging.
    Uses ID lookups only so it is safe during cascade deletes (e.g. when
    Account or User was already deleted and .account would raise DoesNotExist).
    """
    account_id = None
    created_by_id = getattr(product, 'created_by_id', None)
    if created_by_id:
        account_id = User.objects.filter(pk=created_by_id).values_list('account_id', flat=True).first()
    if not account_id and getattr(product, 'updated_by_id', None):
        account_id = User.objects.filter(pk=product.updated_by_id).values_list('account_id', flat=True).first()
    if account_id:
        return Account.objects.filter(pk=account_id).first()
    return None


@receiver(post_save, sender=Product)
def log_product_activity(sender, instance, created, **kwargs):
    """Log job order (Product) create/update to security activity log."""
    account = _product_account(instance)
    if not account:
        return
    from apps.accounts.models import UserActivity
    from apps.accounts.activity_tracking import get_current_request
    request = get_current_request()
    user = getattr(request, 'user', None) if request else None
    if not user or not user.is_authenticated:
        user = getattr(instance, 'created_by', None) or getattr(instance, 'updated_by', None)
    activity_type = 'CREATE' if created else 'UPDATE'
    desc = f"Job order {instance.job_order} created" if created else f"Job order {instance.job_order} updated"
    UserActivity.log_activity(
        user=user or instance.created_by,
        account=account,
        activity_type=activity_type,
        description=desc,
        app_name='job_orders',
        model_name='Product',
        object_id=str(instance.pk),
        object_repr=instance.job_order or str(instance),
    )


@receiver(post_delete, sender=Product)
def log_product_deleted(sender, instance, **kwargs):
    """Log job order (Product) deletion to security activity log."""
    account = _product_account(instance)
    if not account:
        return
    from apps.accounts.models import UserActivity
    user = getattr(instance, 'created_by', None) or getattr(instance, 'updated_by', None)
    UserActivity.log_activity(
        user=user,
        account=account,
        activity_type='DELETE',
        description=f"Job order {instance.job_order} deleted",
        app_name='job_orders',
        model_name='Product',
        object_id=str(instance.pk),
        object_repr=instance.job_order or str(instance),
    )


@receiver(post_save, sender=CompanyProfile)
def update_job_order_currency_on_company_change(sender, instance, **kwargs):
    """Update job order currency when company profile currency changes"""
    try:
        # Update all products created by users of this company
        products = Product.objects.filter(created_by__company_profile=instance)
        for product in products:
            # Trigger save to update currency displays
            product.save()
        
        # Update all orders for users of this company
        orders = Order.objects.filter(customer__company_profile=instance)
        for order in orders:
            # Trigger save to update currency displays
            order.save()
            
    except Exception as e:
        # Log error but don't fail the company profile save
        print(f"Warning: Failed to update job order currency on company change: {e}")
        pass


# REMOVED: add_user_to_basic_group signal.
# It auto-granted every new user a global "Basic Users" group (job order permissions),
# violating: (1) no permissions beyond onboarding defaults, (2) no global group shared
# across accounts. Access is controlled only via Django Admin and account-scoped roles.
