"""
Custom error views for the project (e.g. 403 with role-based messaging).
"""
from django.http import HttpResponseForbidden
from django.template import loader
from django.views.decorators.csrf import requires_csrf_token
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

from apps.accounts.models import SubUser


def _is_company_team_member(request):
    """
    True if the current user is a company team member (SubUser), not the account owner.
    Uses session first (set at team member login), then DB fallback.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return False
    # 1. Session: login view sets sub_user_id only when a team member logs in
    session = getattr(request, "session", None)
    if session:
        sub_user_id = session.get("sub_user_id")
        if sub_user_id:
            try:
                sub_user_id_int = int(sub_user_id)
                if SubUser.objects.filter(pk=sub_user_id_int, linked_user=request.user).exists():
                    return True
            except (ValueError, TypeError):
                pass
        # If session has sub_user_id but DB check failed (e.g. stale session), still treat as team member
        if sub_user_id:
            return True
    # 2. Fallback: user is the linked_user of a SubUser
    return SubUser.objects.filter(linked_user=request.user).exists()


@requires_csrf_token
def permission_denied(request, exception, template_name="403.html"):
    """
    Permission denied (403) handler with role-based message.
    - Company owner: contact the developer for full access.
    - Company team member: contact the company admin to give them full access.
    """
    try:
        template = loader.get_template(template_name)
    except Exception:
        return HttpResponseForbidden("403 Forbidden")

    is_company_team_member = _is_company_team_member(request)
    context = {
        "exception": str(exception),
        "is_company_team_member": is_company_team_member,
        "is_record_unauthorized": False,
    }
    return HttpResponseForbidden(template.render(context, request))


def render_record_unauthorized(request, template_name="403.html"):
    """
    Return 403 response using the same unauthorized page as permission_denied,
    with message for "record not visible or does not exist". Used when
    get_object_or_404(visibility_queryset, ...) would 404 so we show a
    friendly page instead of a raw 404, without leaking whether the record exists.
    """
    try:
        template = loader.get_template(template_name)
    except Exception:
        return HttpResponseForbidden("403 Forbidden")
    context = {
        "exception": "",
        "is_company_team_member": _is_company_team_member(request),
        "is_record_unauthorized": True,
    }
    return HttpResponseForbidden(template.render(context, request))


def get_object_or_unauthorized(request, queryset, *filter_args, **filter_kwargs):
    """
    Fetch a single object from a visibility-scoped queryset (e.g. for_user_queryset).
    Returns (obj, None) if found; (None, HttpResponse 403) if not in queryset.
    Use for detail/edit/delete/PDF/export so isolation-based "not found" shows
    the existing unauthorized page instead of a raw 404, without leaking existence.

    Usage:
        obj, response = get_object_or_unauthorized(request, qs, pk=pk)
        if response:
            return response
        # use obj
    """
    try:
        return (queryset.get(*filter_args, **filter_kwargs), None)
    except (ObjectDoesNotExist, MultipleObjectsReturned, ValueError):
        return (None, render_record_unauthorized(request))
