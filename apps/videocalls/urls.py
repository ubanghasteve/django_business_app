from django.urls import path
from . import views

app_name = 'videocalls'

urlpatterns = [
    path('', views.lobby_view, name='lobby'),
    
    path('create/', views.create_room_view, name='create_room'),
    path('join/', views.join_room_view, name='join_room'),
    path('room/<str:room_code>/prejoin/', views.prejoin_room_view, name='prejoin_room'),
    path('room/<str:room_code>/', views.room_detail_view, name='room'),
    # Alias without trailing slash to avoid browser redirect edge-cases on localhost.
    path('room/<str:room_code>', views.room_detail_view, name='room_no_slash'),
    path('leave/<str:room_code>/', views.leave_room_view, name='leave_room'),
    path('end/<str:room_code>/', views.end_room_view, name='end_room'),
    path('my-rooms/', views.room_list_view, name='my_rooms'),
    path('recordings/<str:room_code>/', views.room_recordings_view, name='room_recordings'),
    path('download-recording/<uuid:recording_id>/', views.download_recording_view, name='download_recording'),
    
    path('local-recordings/', views.local_recordings_view, name='local_recordings'),
    
    path('schedule/', views.schedule_meeting_view, name='schedule_meeting'),
    path('my-scheduled-meetings/', views.my_scheduled_meetings_view, name='my_scheduled_meetings'),
    path('meeting/<str:meeting_slug>/', views.meeting_detail_view, name='meeting_detail'),
    path('meeting/<str:meeting_slug>/edit/', views.edit_meeting_view, name='edit_meeting'),
    path('meeting/<str:meeting_slug>/delete/', views.delete_meeting_view, name='delete_meeting'),
    path('meeting/<str:meeting_slug>/send-invite/', views.send_meeting_invite_view, name='send_meeting_invite'),
    path('meeting/<str:meeting_slug>/start/', views.start_meeting_view, name='start_meeting'),
    path('join/<str:meeting_slug>/', views.join_meeting_view, name='join_meeting'),
    
    path('api/meeting/<str:meeting_slug>/status/', views.meeting_status_api, name='api_meeting_status'),
    path('api/create/', views.room_create_api, name='api_create_room'),
    path('api/join/', views.room_join_api, name='api_join_room'),
    path('api/leave/', views.room_leave_api, name='api_leave_room'),
    path('api/status/<str:room_code>/', views.room_status_api, name='api_room_status'),
    path('api/signaling/offer/', views.signaling_offer_api, name='api_signaling_offer'),
    path('api/signaling/answer/', views.signaling_answer_api, name='api_signaling_answer'),
    path('api/signaling/ice/', views.signaling_ice_api, name='api_signaling_ice'),
    path('api/signaling/', views.signaling_message_api, name='api_signaling_message'),
    path('api/signaling/messages/', views.signaling_messages_api, name='api_signaling_messages'),
    path('api/participants/<str:room_code>/', views.get_participants_api, name='api_participants'),
    path('api/update-participant/', views.update_participant_api, name='api_update_participant'),
    path('api/upload-recording/', views.upload_recording_api, name='api_upload_recording'),
    path('api/recording/<uuid:recording_id>/', views.recording_detail_api, name='api_recording_detail'),
    path('api/update-room/', views.update_room_settings_api, name='api_update_room'),
    path('api/delete-room/', views.delete_room_api, name='api_delete_room'),
    path('api/csrf/', views.get_csrf_token, name='api_csrf'),
    path('api/host-control/', views.host_control_api, name='api_host_control'),
    path('api/send-invite/', views.send_invite_api, name='api_send_invite'),
    path('api/config/', views.get_video_call_config, name='api_config'),
]
