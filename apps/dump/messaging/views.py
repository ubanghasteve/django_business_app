"""
Messaging views. All AJAX endpoints return JSON.
Every view verifies: user authenticated, user belongs to company, conversation access (member or admin).
"""
import json
import threading
from datetime import timedelta
from django.db.models import Count, Q, Exists, OuterRef
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from asgiref.sync import async_to_sync

from apps.core.ownership import get_account_for_user
from apps.core.utils import get_company_profile_for_user

from .models import Conversation, ConversationMember, Message, MessageHiddenForUser, CallSession, TypingIndicator
from .services import (
    conversations_for_user,
    user_can_access_conversation,
    user_is_group_admin,
    messages_for_user,
    update_presence,
    set_presence_offline,
    is_user_online,
)


def _require_auth_company(request):
    """Return (user, account, company_profile) or (None, None, None). 403 if not allowed."""
    if not request.user.is_authenticated:
        return None, None, None
    account = get_account_for_user(request.user)
    if not account:
        return request.user, None, None
    company = get_company_profile_for_user(request.user, request)
    return request.user, account, company


def _json_403(msg='Forbidden'):
    return JsonResponse({'error': msg}, status=403)


def _json_400(msg='Bad request'):
    return JsonResponse({'error': msg}, status=400)


def _json_404(msg='Not found'):
    return JsonResponse({'error': msg}, status=404)


def _get_conversation_or_404(conversation_id):
    """Return (conv, None) or (None, JsonResponse) so API views never raise Http404 (HTML)."""
    conv = Conversation.objects.filter(pk=conversation_id).first()
    if conv is None:
        return None, _json_404('Conversation not found')
    return conv, None


def _message_payload_for_ws(msg, request):
    """Build the same payload shape as fetch_messages for WebSocket push."""
    file_url = None
    if msg.file or getattr(msg, 'is_image', False):
        try:
            file_url = request.build_absolute_uri(reverse('messaging:api_serve_message_file', args=[msg.id]))
        except Exception:
            file_url = msg.file.url if getattr(msg, 'file', None) else None
    return {
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_name': msg.sender.get_full_name() or msg.sender.email,
        'content': msg.content,
        'reply_to_id': msg.reply_to_id,
        'reply_preview': (msg.reply_to.content or '(file)')[:80] if msg.reply_to else None,
        'file': file_url,
        'is_image': msg.is_image,
        'created_at': msg.created_at.isoformat(),
        'is_deleted': getattr(msg, 'is_deleted', False),
    }


def _push_message_to_websocket(conv_id, payload):
    """Send new message to all WebSocket clients in this conversation (real-time delivery).
    Runs in a daemon thread so the HTTP response returns immediately and delivery is not delayed."""
    def _do_send():
        try:
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'conv_{conv_id}',
                    {'type': 'message_created', 'message': payload},
                )
        except Exception:
            pass  # Don't fail REST request if WebSocket push fails

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()


# ---------- Page views (HTML) ----------

@require_GET
@ensure_csrf_cookie
def inbox_page(request):
    """Inbox page: conversation list + chat pane (split layout)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    return render(request, 'messaging/inbox.html', {
        'conversations': [],  # Loaded via AJAX
        'conversation': None,  # So template {% if conversation %} is safe
    })


@require_GET
@ensure_csrf_cookie
def chat_page(request, conversation_id):
    """Chat page for a specific conversation (or 404 if no access)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    conv = get_object_or_404(Conversation, pk=conversation_id)
    if not user_can_access_conversation(conv, user, request):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    return render(request, 'messaging/inbox.html', {
        'conversation': conv,
    })


# ---------- AJAX API (JSON) ----------

@never_cache
@ensure_csrf_cookie
@require_GET
def csrf_token_view(request):
    """Return current CSRF token; ensures cookie is set. Used when token may be stale (multi-tab, long session)."""
    from django.middleware.csrf import get_token
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    token = get_token(request)
    return JsonResponse({'csrfToken': token})


@never_cache
@require_GET
def account_users(request):
    """GET: list users in same account (for New chat)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    from apps.core.utils import get_account_users_for_filter
    users_qs = get_account_users_for_filter(user)
    users = [
        {'id': u.id, 'name': u.get_full_name() or u.email, 'email': u.email}
        for u in users_qs.exclude(id=user.id)[:50]
    ]
    return JsonResponse({'users': users})


@require_POST
def create_conversation(request):
    """POST: create private (other_user_id) or group (name, member_ids)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = request.POST.dict()
    other_user_id = body.get('other_user_id')
    name = (body.get('name') or '').strip()
    member_ids = body.get('member_ids') or []
    if other_user_id:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            other = User.objects.get(pk=int(other_user_id), account=account)
        except (ValueError, User.DoesNotExist):
            return _json_400('Invalid user')
        # Use deterministic ordering so both users get the SAME conversation for the pair
        # (avoids sender and recipient being in different threads so messages are visible to both)
        existing = Conversation.objects.filter(
            account=account, is_group=False
        ).filter(
            members__user_id=user.id
        ).filter(
            members__user_id=other.id
        ).annotate(
            mc=Count('members')
        ).filter(mc=2).order_by('id').first()
        if existing:
            # If current user had left this conversation, rejoin so they can send messages
            my_membership = ConversationMember.objects.filter(
                conversation=existing, user=user
            ).first()
            if my_membership and my_membership.left_at:
                my_membership.left_at = None
                my_membership.save(update_fields=['left_at'])
            return JsonResponse({'conversation_id': existing.id, 'created': False})
        conv = Conversation.objects.create(account=account, is_group=False, created_by=user)
        ConversationMember.objects.create(conversation=conv, user=user)
        ConversationMember.objects.create(conversation=conv, user=other)
        return JsonResponse({'conversation_id': conv.id, 'created': True})
    if name and member_ids:
        conv = Conversation.objects.create(
            account=account, is_group=True, name=name, created_by=user
        )
        ConversationMember.objects.create(conversation=conv, user=user, is_admin=True)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        for uid in member_ids[:20]:
            try:
                u = User.objects.get(pk=int(uid), account=account)
                ConversationMember.objects.get_or_create(conversation=conv, user=u)
            except (ValueError, User.DoesNotExist):
                pass
        return JsonResponse({'conversation_id': conv.id, 'created': True})
    return _json_400('Provide other_user_id for private or name and member_ids for group')


@never_cache
@require_GET
def conversation_list(request):
    """GET: list conversations for current user (member or admin sees company list). Optional q= search."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    qs = conversations_for_user(user, request)
    search_q = (request.GET.get('q') or '').strip()
    if search_q:
        # Match conversations by name, member names/email, OR any visible message content (text, numbers, symbols)
        matching_message = Message.objects.filter(
            conversation_id=OuterRef('pk'),
            is_deleted=False,
        ).exclude(
            hidden_for_users__user=user
        ).filter(
            content__icontains=search_q
        )
        qs = qs.filter(
            Q(name__icontains=search_q) |
            Q(members__user__email__icontains=search_q) |
            Q(members__user__first_name__icontains=search_q) |
            Q(members__user__last_name__icontains=search_q) |
            Exists(matching_message)
        ).distinct()
    conversations = []
    seen_ids = set()
    # For private chats, we may have multiple Conversation rows for the same pair (legacy duplicates).
    # Use the SAME canonical conversation (smallest id) that create_conversation returns, so sender
    # and recipient always see the same thread and messages are visible to both.
    private_by_other = {}  # other_user_id -> {conversation dict}
    for c in qs.select_related('created_by').prefetch_related('members__user')[:100]:
        if c.id in seen_ids:
            continue
        seen_ids.add(c.id)
        members = list(c.members.select_related('user').all())
        active_members = [m for m in members if m.left_at is None]
        # For 1:1 display name use all members (including left) so we show the other person's name
        # even when they have left; otherwise the other party would see "Conversation".
        other_users_for_name = [m.user for m in members if m.user_id != user.id]
        other_users = [m.user for m in active_members if m.user_id != user.id]
        display_name = c.name if c.is_group and c.name else (
            (other_users_for_name[0].get_full_name() or other_users_for_name[0].email) if other_users_for_name else 'Conversation'
        )
        visible_msgs = c.messages.filter(is_deleted=False).exclude(
            hidden_for_users__user=user
        )
        last_msg = visible_msgs.order_by('-created_at').first()
        membership = next((m for m in members if m.user_id == user.id), None)
        last_read = membership.last_read_at if membership and membership.last_read_at else None
        unread_count = 0
        if last_read and last_msg and last_msg.created_at > last_read:
            unread_count = visible_msgs.filter(created_at__gt=last_read).count()
        elif not last_read and last_msg:
            unread_count = visible_msgs.count()
        left = bool(membership and membership.left_at)
        last_message_at = last_msg.created_at.isoformat() if last_msg else c.created_at.isoformat()
        item = {
            'id': c.id,
            'is_group': c.is_group,
            'name': c.name or display_name,
            'created_at': c.created_at.isoformat(),
            'last_message_at': last_message_at,
            'member_ids': [m.user_id for m in active_members],
            'unread_count': unread_count,
            'left': left,
            'can_rejoin': left,
        }
        # For all private (1:1) chats, dedupe by other user so we show one entry per partner
        # (whether they or the current user have left/rejoined). Prefer canonical conversation (smallest id).
        if not c.is_group and other_users_for_name:
            other_id = other_users_for_name[0].id
            existing_item = private_by_other.get(other_id)
            if existing_item is None or c.id < existing_item['id']:
                private_by_other[other_id] = item
            continue
        conversations.append(item)
    # Append one private chat per other user (canonical conversation so both see same thread)
    for other_id, item in private_by_other.items():
        conversations.append(item)
    # Sort by last_message_at descending so most recent is first
    conversations.sort(key=lambda x: x['last_message_at'], reverse=True)
    return JsonResponse({'conversations': conversations})


@never_cache
@require_GET
def conversation_detail(request, conversation_id):
    """GET: single conversation details (if user has access)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    members = list(conv.members.select_related('user').filter(left_at__isnull=True))
    is_group_admin = user_is_group_admin(conv, user, request)
    return JsonResponse({
        'id': conv.id,
        'is_group': conv.is_group,
        'name': conv.name,
        'created_at': conv.created_at.isoformat(),
        'is_group_admin': is_group_admin,
        'members': [
            {
                'user_id': m.user_id,
                'name': m.user.get_full_name() or m.user.email,
                'is_admin': m.is_admin,
                'online': is_user_online(m.user_id, conv.account_id),
            }
            for m in members
        ],
    })


@require_POST
def send_message(request, conversation_id):
    """POST: send a text message (content in JSON or form)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    content = None
    if request.content_type and 'application/json' in request.content_type:
        try:
            body = json.loads(request.body)
            content = (body.get('content') or '').strip()
        except Exception:
            pass
    if content is None:
        content = (request.POST.get('content') or '').strip()
    reply_to_id = request.POST.get('reply_to') or (None)
    if request.content_type and 'application/json' in request.content_type:
        try:
            body = json.loads(request.body)
            reply_to_id = body.get('reply_to')
        except Exception:
            pass
    reply_to = None
    if reply_to_id:
        try:
            reply_to = Message.objects.get(pk=int(reply_to_id), conversation=conv, is_deleted=False)
        except (ValueError, Message.DoesNotExist):
            pass
    if not content:
        return _json_400('Message content is required')
    msg = Message.objects.create(
        conversation=conv,
        sender=user,
        content=content or None,
        reply_to=reply_to,
        is_deleted=False,
    )
    file_url = None
    if msg.file:
        try:
            file_url = request.build_absolute_uri(reverse('messaging:api_serve_message_file', args=[msg.id]))
        except Exception:
            file_url = msg.file.url if msg.file else None
    response_payload = {
        'id': msg.id,
        'conversation_id': conv.id,
        'sender_id': user.id,
        'content': msg.content,
        'reply_to_id': msg.reply_to_id,
        'file': file_url,
        'is_image': msg.is_image,
        'created_at': msg.created_at.isoformat(),
    }
    # Real-time: push to all WebSocket clients in this conversation
    _push_message_to_websocket(conv.id, _message_payload_for_ws(msg, request))
    return JsonResponse(response_payload)


@never_cache
@require_GET
def fetch_messages(request, conversation_id):
    """GET: messages after optional timestamp (after=ISO), before= or before_id= for older, q= for search."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    qs = messages_for_user(conv, user, request)
    after = request.GET.get('after')
    before = request.GET.get('before')
    before_id = request.GET.get('before_id')
    search_q = (request.GET.get('q') or '').strip()
    if after:
        try:
            from django.utils.dateparse import parse_datetime
            dt = parse_datetime(after)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            if dt:
                qs = qs.filter(created_at__gt=dt)
        except Exception:
            pass
    # "Load older": use before_id (message id) for stable pagination, else before (ISO timestamp)
    if before_id:
        try:
            cursor_msg = qs.filter(pk=int(before_id)).first()
            if cursor_msg:
                qs = qs.filter(created_at__lt=cursor_msg.created_at)
        except (ValueError, TypeError):
            pass
    elif before:
        try:
            from django.utils.dateparse import parse_datetime
            dt = parse_datetime(before)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            if dt:
                qs = qs.filter(created_at__lt=dt)
        except Exception:
            pass
    search_words = []
    if search_q:
        search_words = [w.strip() for w in search_q.split() if w.strip()]
        for word in search_words:
            qs = qs.filter(content__icontains=word)
    # Initial load: return the 100 most recent messages (ascending for display). Previously we
    # returned the 100 oldest, so users missed recent history.
    if not after and not before and not before_id:
        qs = qs.order_by('-created_at')[:100]
        iter_msgs = reversed(list(qs))
        limit = 100
    else:
        # Load older: get the 50 most recent messages that are older than the cursor (ascending).
        if before_id or before:
            qs = qs.order_by('-created_at')[:50]
            iter_msgs = reversed(list(qs))
        else:
            iter_msgs = qs.order_by('-created_at')[:50]
            iter_msgs = list(iter_msgs)
        limit = 50
    messages = []
    snippet_radius = 60
    for m in iter_msgs:
        file_url = None
        if getattr(m, 'file', None) and m.file:
            try:
                file_url = request.build_absolute_uri(
                    reverse('messaging:api_serve_message_file', args=[m.id])
                )
            except Exception:
                file_url = getattr(m.file, 'url', None) if getattr(m, 'file', None) else None
        payload = {
            'id': m.id,
            'sender_id': m.sender_id,
            'sender_name': m.sender.get_full_name() or m.sender.email,
            'content': m.content,
            'reply_to_id': m.reply_to_id,
            'reply_preview': (m.reply_to.content or '(file)')[:80] if m.reply_to else None,
            'file': file_url,
            'is_image': bool(m.is_image),
            'created_at': m.created_at.isoformat(),
            'is_deleted': getattr(m, 'is_deleted', False),
        }
        if search_words and (m.content or ''):
            import re
            text = (m.content or '').replace('\n', ' ')
            match = None
            for word in search_words:
                m_obj = re.search(re.escape(word), text, re.IGNORECASE)
                if m_obj:
                    match = m_obj
                    break
            if match:
                first_start, first_end = match.start(), match.end()
                start = max(0, first_start - snippet_radius)
                end = min(len(text), first_end + snippet_radius)
                snippet = text[start:end]
                if start > 0:
                    snippet = '…' + snippet
                if end < len(text):
                    snippet = snippet + '…'
                payload['snippet'] = snippet
            else:
                payload['snippet'] = (text[:120] + '…') if len(text) > 120 else text
        messages.append(payload)
    deleted_ids = []
    if after:
        try:
            from django.utils.dateparse import parse_datetime
            dt = parse_datetime(after)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            if dt:
                since_cutoff = dt - timedelta(seconds=10)
                deleted_ids = list(Message.objects.filter(
                    conversation=conv, is_deleted=True,
                    deleted_at__isnull=False, deleted_at__gt=since_cutoff
                ).values_list('id', flat=True))
        except Exception:
            pass
    return JsonResponse({'messages': messages, 'deleted_ids': deleted_ids})


@never_cache
@require_GET
def deleted_ids_since(request, conversation_id):
    """Lightweight: return only message IDs deleted since timestamp. For fast real-time delete sync."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    since = request.GET.get('since')
    if not since:
        return JsonResponse({'deleted_ids': []})
    try:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(since)
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        if not dt:
            return JsonResponse({'deleted_ids': []})
        since_cutoff = dt - timedelta(seconds=10)
        ids = list(Message.objects.filter(
            conversation=conv, is_deleted=True,
            deleted_at__isnull=False, deleted_at__gt=since_cutoff
        ).values_list('id', flat=True))
        return JsonResponse({'deleted_ids': ids})
    except Exception:
        return JsonResponse({'deleted_ids': []})


# Max file size (bytes) and allowed MIME types for uploads
MESSAGING_MAX_FILE_SIZE = getattr(settings, 'MESSAGING_MAX_FILE_SIZE', 10 * 1024 * 1024)  # 10MB
MESSAGING_ALLOWED_FILE_TYPES = getattr(settings, 'MESSAGING_ALLOWED_FILE_TYPES', [
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain', 'text/csv',
])
# Fallback: allow by extension when browser sends empty or generic MIME (e.g. application/octet-stream)
MESSAGING_ALLOWED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.doc', '.docx', '.txt', '.csv')


def _allowed_file_type(content_type, filename):
    """Return True if file is allowed by MIME type or by extension (when MIME is missing/generic)."""
    if content_type and content_type in MESSAGING_ALLOWED_FILE_TYPES:
        return True
    if not content_type or content_type == 'application/octet-stream':
        if filename:
            ext = '.' + (filename.rsplit('.', 1)[-1].lower() if '.' in filename else '')
            if ext in MESSAGING_ALLOWED_EXTENSIONS:
                return True
    return False


def _is_image_content(content_type, filename):
    """Return True if file is an image (for display)."""
    if content_type and content_type.startswith('image/'):
        return True
    if filename:
        ext = '.' + (filename.rsplit('.', 1)[-1].lower() if '.' in filename else '')
        if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            return True
    return False


@never_cache
@require_POST
def upload_file(request, conversation_id):
    """POST: upload file (multipart); optional content. Returns message payload."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    f = request.FILES.get('file')
    if not f:
        return _json_400('No file provided')
    if f.size > MESSAGING_MAX_FILE_SIZE:
        return _json_400(f'File too large. Maximum size is {MESSAGING_MAX_FILE_SIZE // (1024 * 1024)}MB.')
    content_type = getattr(f, 'content_type', '') or ''
    filename = getattr(f, 'name', '') or ''
    if not _allowed_file_type(content_type, filename):
        return _json_400(f'File type not allowed. Use images, PDF, Word, or text files.')
    content = (request.POST.get('content') or '').strip()
    is_image = _is_image_content(content_type, filename)
    try:
        msg = Message.objects.create(
            conversation=conv,
            sender=user,
            content=content or None,
            file=f,
            is_image=is_image,
            is_deleted=False,
        )
    except Exception:
        return JsonResponse({'error': 'Upload failed. Check that file storage is configured.'}, status=500)
    msg.refresh_from_db()
    if not msg.file:
        return JsonResponse({'error': 'Upload failed. File was not saved. Please try again.'}, status=500)
    file_url = None
    try:
        file_url = request.build_absolute_uri(reverse('messaging:api_serve_message_file', args=[msg.id]))
    except Exception:
        file_url = msg.file.url if msg.file else None
    payload = {
        'id': msg.id,
        'conversation_id': conv.id,
        'sender_id': user.id,
        'content': msg.content,
        'reply_to_id': None,
        'file': file_url,
        'is_image': msg.is_image,
        'created_at': msg.created_at.isoformat(),
    }
    _push_message_to_websocket(conv.id, _message_payload_for_ws(msg, request))
    return JsonResponse(payload)


@require_POST
def start_call(request, conversation_id):
    """POST: create a call session (signaling only)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    session = CallSession.objects.create(
        conversation=conv,
        started_by=user,
        status='calling',
    )
    return JsonResponse({
        'id': session.id,
        'conversation_id': conv.id,
        'started_by_id': user.id,
        'status': session.status,
        'created_at': session.created_at.isoformat(),
    })


@never_cache
@require_GET
def poll_call_status(request, conversation_id):
    """GET: latest call session status for conversation."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    session = CallSession.objects.filter(conversation=conv).order_by('-created_at').first()
    if not session:
        return JsonResponse({'call': None})
    return JsonResponse({
        'call': {
            'id': session.id,
            'status': session.status,
            'started_by_id': session.started_by_id,
            'created_at': session.created_at.isoformat(),
        },
    })


@require_POST
def remove_member(request, conversation_id):
    """POST: remove a member (admin or group admin only). Body: user_id. Cannot remove last member."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_is_group_admin(conv, user, request):
        return _json_403('Only group admin or company admin can remove members')
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = request.POST.dict()
    target_user_id = body.get('user_id')
    if not target_user_id:
        return _json_400('user_id required')
    try:
        target_user_id = int(target_user_id)
    except (ValueError, TypeError):
        return _json_400('Invalid user_id')
    if conv.members.filter(left_at__isnull=True).count() <= 1:
        return _json_400('Cannot remove the last member')
    membership = ConversationMember.objects.filter(
        conversation=conv, user_id=target_user_id
    ).first()
    if not membership:
        return _json_400('User is not a member of this conversation')
    membership.delete()
    return JsonResponse({'ok': True})


@require_POST
def leave_conversation(request, conversation_id):
    """POST: current user leaves the conversation."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    account = get_account_for_user(user)
    if not account or conv.account_id != account.id:
        return _json_403('Not a member of this conversation')
    membership = ConversationMember.objects.filter(conversation=conv, user=user).first()
    if not membership:
        return _json_403('Not a member of this conversation')
    if membership.left_at:
        return _json_400('You have already left this conversation. Rejoin to continue.')
    active_count = conv.members.filter(left_at__isnull=True).count()
    if active_count <= 1:
        return _json_400('Cannot leave; you are the only active member. Add others first.')
    membership.left_at = timezone.now()
    membership.save(update_fields=['left_at'])
    return JsonResponse({'ok': True})


@require_POST
def rejoin_conversation(request, conversation_id):
    """POST: current user rejoins a conversation they left (can continue from where they left off)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    membership = ConversationMember.objects.filter(conversation=conv, user=user).first()
    if not membership:
        return _json_403('Not a member of this conversation')
    if not membership.left_at:
        return JsonResponse({'ok': True})
    membership.left_at = None
    membership.save(update_fields=['left_at'])
    return JsonResponse({'ok': True})


@require_POST
def add_member(request, conversation_id):
    """POST: add a member to group (same account only; group admin or company admin). Body: user_id."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not conv.is_group:
        return _json_400('Only group conversations can have members added')
    if not user_is_group_admin(conv, user, request):
        return _json_403('Only group admin or company admin can add members')
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = request.POST.dict()
    target_user_id = body.get('user_id')
    if not target_user_id:
        return _json_400('user_id required')
    try:
        target_user_id = int(target_user_id)
    except (ValueError, TypeError):
        return _json_400('Invalid user_id')
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        new_user = User.objects.get(pk=target_user_id, account=account)
    except User.DoesNotExist:
        return _json_400('User not found or not in same account')
    obj, created = ConversationMember.objects.get_or_create(
        conversation=conv, user=new_user, defaults={'is_admin': False}
    )
    return JsonResponse({'ok': True, 'added': created})


@require_POST
def delete_message(request, conversation_id):
    """
    POST: delete a message.
    Body: message_id, delete_for ("me" | "all").
    - delete_for=me: hide from current user only (any member can do this).
    - delete_for=all: soft-delete for everyone (sender or group admin only).
    """
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = request.POST.dict()
    msg_id = body.get('message_id')
    if not msg_id:
        return _json_400('message_id required')
    delete_for = (body.get('delete_for') or 'all').strip().lower()
    if delete_for not in ('me', 'all'):
        return _json_400('delete_for must be "me" or "all"')
    try:
        msg = Message.objects.get(pk=int(msg_id), conversation=conv)
    except (ValueError, Message.DoesNotExist):
        return _json_400('Message not found')
    if delete_for == 'me':
        # Any conversation member can hide a message from their own view
        MessageHiddenForUser.objects.get_or_create(
            message=msg, user=user,
            defaults={'hidden_at': timezone.now()},
        )
        return JsonResponse({'ok': True})
    # delete_for == 'all': only sender or group admin
    if msg.sender_id != user.id and not user_is_group_admin(conv, user, request):
        return _json_403('Only sender or group admin can delete this message for everyone')
    msg.is_deleted = True
    msg.deleted_at = timezone.now()
    msg.save(update_fields=['is_deleted', 'deleted_at'])
    return JsonResponse({'ok': True})


@require_POST
def mark_read(request, conversation_id):
    """POST: mark conversation as read for current user (update last_read_at)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    membership = ConversationMember.objects.filter(conversation=conv, user=user).first()
    if membership:
        membership.last_read_at = timezone.now()
        membership.save(update_fields=['last_read_at'])
    return JsonResponse({'ok': True})


@require_POST
def rename_conversation(request, conversation_id):
    """POST: rename group. Body: name. Group admin or company admin only."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not conv.is_group:
        return _json_400('Only group conversations can be renamed')
    if not user_is_group_admin(conv, user, request):
        return _json_403('Only group admin or company admin can rename')
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = request.POST.dict()
    name = (body.get('name') or '').strip()
    if not name:
        return _json_400('name required')
    conv.name = name[:255]
    conv.save(update_fields=['name'])
    return JsonResponse({'ok': True, 'name': conv.name})


@require_POST
def typing_start(request, conversation_id):
    """POST: set typing indicator for current user (lightweight; poll typing state elsewhere)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    obj, _ = TypingIndicator.objects.update_or_create(
        conversation=conv, user=user,
        defaults={'last_typing_at': timezone.now()}
    )
    return JsonResponse({'ok': True})


@require_POST
def typing_stop(request, conversation_id):
    """POST: clear typing indicator so others see 'stopped typing' immediately."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    past = timezone.now() - timedelta(seconds=15)
    TypingIndicator.objects.update_or_create(
        conversation=conv, user=user,
        defaults={'last_typing_at': past}
    )
    return JsonResponse({'ok': True})


@never_cache
@require_GET
def typing_list(request, conversation_id):
    """GET: list users currently typing (last_typing_at within last 10s, exclude current user)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    threshold = timezone.now() - timezone.timedelta(seconds=10)
    typers = TypingIndicator.objects.filter(
        conversation=conv, last_typing_at__gte=threshold
    ).exclude(user=user).select_related('user')
    result = [
        {'user_id': t.user_id, 'name': t.user.get_full_name() or t.user.email}
        for t in typers
    ]
    return JsonResponse({'typing': result})


@require_POST
def end_call(request, conversation_id):
    """POST: set latest call session status to ended."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    conv, err = _get_conversation_or_404(conversation_id)
    if err:
        return err
    if not user_can_access_conversation(conv, user, request):
        return _json_403('Not a member of this conversation')
    session = CallSession.objects.filter(conversation=conv).order_by('-created_at').first()
    if not session:
        return JsonResponse({'ok': True, 'call': None})
    session.status = 'ended'
    session.save(update_fields=['status'])
    return JsonResponse({'ok': True, 'call': {'id': session.id, 'status': session.status}})


@require_POST
def update_presence_view(request):
    """POST: heartbeat for online presence (~30s)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    try:
        update_presence(user, request)
    except OperationalError:
        pass
    return JsonResponse({'ok': True})


@require_POST
def set_presence_offline_view(request):
    """POST: mark current user offline immediately (e.g. on leave or tab close)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    try:
        set_presence_offline(user, request)
    except OperationalError:
        pass
    return JsonResponse({'ok': True})


def _content_type_for_message_file(msg):
    """Return Content-Type for message file so browsers display images inline."""
    if not getattr(msg, 'file', None) or not msg.file.name:
        return None
    import mimetypes
    name = msg.file.name
    ct, _ = mimetypes.guess_type(name)
    if ct:
        return ct
    if getattr(msg, 'is_image', False):
        ext = (name.rsplit('.', 1)[-1].lower() if '.' in name else '')
        return {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/jpeg')
    return None


@never_cache
@require_GET
def serve_message_file(request, message_id):
    """Serve message file only if user has access to the conversation (member or admin). Errors return JSON."""
    from django.http import FileResponse
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    msg = Message.objects.filter(pk=message_id).first()
    if msg is None:
        return _json_404('Message not found')
    if not user_can_access_conversation(msg.conversation, user, request):
        return _json_403('Not a member of this conversation')
    if not msg.file:
        return _json_404('File not found')
    try:
        f = msg.file.open('rb')
        import os
        filename = os.path.basename(msg.file.name)
        content_type = _content_type_for_message_file(msg)
        response = FileResponse(f, as_attachment=False, filename=filename)
        if content_type:
            response['Content-Type'] = content_type
        return response
    except Exception:
        return JsonResponse({'error': 'File unavailable'}, status=500)


@never_cache
@require_GET
def presence_list(request):
    """GET: list user ids considered online in the account (for current company)."""
    user, account, company = _require_auth_company(request)
    if not user or not account:
        return _json_403('Authentication required')
    from .models import UserPresence
    threshold = timezone.now() - timezone.timedelta(seconds=90)
    online = list(
        UserPresence.objects.filter(
            account=account, last_seen__gte=threshold
        ).values_list('user_id', flat=True).distinct()
    )
    return JsonResponse({'online_user_ids': online})
