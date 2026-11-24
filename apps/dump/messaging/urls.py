from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('', views.inbox_page, name='inbox'),
    path('conversation/<int:conversation_id>/', views.chat_page, name='chat'),
    # AJAX API
    path('api/csrf/', views.csrf_token_view, name='api_csrf_token'),
    path('api/account-users/', views.account_users, name='api_account_users'),
    path('api/conversations/create/', views.create_conversation, name='api_create_conversation'),
    path('api/conversations/', views.conversation_list, name='api_conversation_list'),
    path('api/conversations/<int:conversation_id>/', views.conversation_detail, name='api_conversation_detail'),
    path('api/conversations/<int:conversation_id>/messages/', views.fetch_messages, name='api_fetch_messages'),
    path('api/conversations/<int:conversation_id>/messages/deleted-since/', views.deleted_ids_since, name='api_deleted_ids_since'),
    path('api/conversations/<int:conversation_id>/send/', views.send_message, name='api_send_message'),
    path('api/conversations/<int:conversation_id>/upload/', views.upload_file, name='api_upload_file'),
    path('api/conversations/<int:conversation_id>/call/start/', views.start_call, name='api_start_call'),
    path('api/conversations/<int:conversation_id>/call/status/', views.poll_call_status, name='api_poll_call_status'),
    path('api/conversations/<int:conversation_id>/call/end/', views.end_call, name='api_end_call'),
    path('api/conversations/<int:conversation_id>/members/remove/', views.remove_member, name='api_remove_member'),
    path('api/conversations/<int:conversation_id>/leave/', views.leave_conversation, name='api_leave_conversation'),
    path('api/conversations/<int:conversation_id>/rejoin/', views.rejoin_conversation, name='api_rejoin_conversation'),
    path('api/conversations/<int:conversation_id>/members/add/', views.add_member, name='api_add_member'),
    path('api/conversations/<int:conversation_id>/messages/delete/', views.delete_message, name='api_delete_message'),
    path('api/conversations/<int:conversation_id>/mark-read/', views.mark_read, name='api_mark_read'),
    path('api/conversations/<int:conversation_id>/rename/', views.rename_conversation, name='api_rename_conversation'),
    path('api/conversations/<int:conversation_id>/typing/', views.typing_start, name='api_typing_start'),
    path('api/conversations/<int:conversation_id>/typing/stop/', views.typing_stop, name='api_typing_stop'),
    path('api/conversations/<int:conversation_id>/typing/list/', views.typing_list, name='api_typing_list'),
    path('api/presence/', views.update_presence_view, name='api_update_presence'),
    path('api/presence/offline/', views.set_presence_offline_view, name='api_presence_offline'),
    path('api/presence/list/', views.presence_list, name='api_presence_list'),
    path('api/message-file/<int:message_id>/', views.serve_message_file, name='api_serve_message_file'),
]

