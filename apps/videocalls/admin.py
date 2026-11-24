from django.contrib import admin
from .models import (
    VideoCallRoom, CallParticipant, SignalMessage, 
    CallRecording, CallSession, JitsiRoom, JitsiParticipant, JitsiRecording
)


@admin.register(VideoCallRoom)
class VideoCallRoomAdmin(admin.ModelAdmin):
    list_display = [
        'room_code', 'room_name', 'host', 'room_type',
        'participant_count', 'max_participants', 'is_active', 'created_at'
    ]
    list_filter = ['room_type', 'is_active', 'created_at']
    search_fields = ['room_code', 'room_name', 'host__email']
    readonly_fields = ['id', 'room_code', 'created_at', 'ended_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'room_code', 'host', 'room_name', 'room_type')
        }),
        ('Settings', {
            'fields': ('max_participants', 'password', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'ended_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CallParticipant)
class CallParticipantAdmin(admin.ModelAdmin):
    list_display = [
        'display_name', 'room', 'is_host', 'is_screen_sharing',
        'is_audio_muted', 'is_video_off', 'joined_at', 'left_at'
    ]
    list_filter = ['is_host', 'is_screen_sharing', 'is_audio_muted', 'is_video_off', 'joined_at']
    search_fields = ['user__email', 'participant_name', 'session_id', 'room__room_code']
    readonly_fields = ['id', 'joined_at']
    ordering = ['-joined_at']
    
    fieldsets = (
        ('Participant Info', {
            'fields': ('id', 'room', 'user', 'participant_name', 'session_id')
        }),
        ('Status', {
            'fields': ('is_host', 'is_screen_sharing', 'is_audio_muted', 'is_video_off')
        }),
        ('Timestamps', {
            'fields': ('joined_at', 'left_at'),
        }),
    )


@admin.register(SignalMessage)
class SignalMessageAdmin(admin.ModelAdmin):
    list_display = [
        'room', 'sender_session_id', 'message_type', 'target_session_id',
        'is_read', 'created_at'
    ]
    list_filter = ['message_type', 'is_read', 'created_at']
    search_fields = ['sender_session_id', 'target_session_id', 'room__room_code']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Message Info', {
            'fields': ('id', 'room', 'message_type')
        }),
        ('Participants', {
            'fields': ('sender_session_id', 'target_session_id')
        }),
        ('Payload', {
            'fields': ('payload',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_read', 'created_at'),
        }),
    )


@admin.register(CallRecording)
class CallRecordingAdmin(admin.ModelAdmin):
    list_display = [
        'room', 'recorded_by', 'duration_formatted', 'file_size_mb',
        'created_at'
    ]
    list_filter = ['created_at']
    search_fields = ['room__room_code', 'recorded_by__email', 'file_name']
    readonly_fields = ['id', 'created_at', 'file_size']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Recording Info', {
            'fields': ('id', 'room', 'recorded_by', 'file_name')
        }),
        ('File Details', {
            'fields': ('recording_file', 'file_size', 'duration_seconds')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
        }),
    )


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = [
        'session_id', 'room', 'started_at', 'ended_at',
        'peak_participants', 'total_messages', 'duration_formatted'
    ]
    list_filter = ['started_at']
    search_fields = ['session_id', 'room__room_code']
    readonly_fields = ['id', 'started_at']
    ordering = ['-started_at']
    
    fieldsets = (
        ('Session Info', {
            'fields': ('id', 'room', 'session_id')
        }),
        ('Statistics', {
            'fields': ('peak_participants', 'total_messages')
        }),
        ('Timestamps', {
            'fields': ('started_at', 'ended_at'),
        }),
    )


@admin.register(JitsiRoom)
class JitsiRoomAdmin(admin.ModelAdmin):
    list_display = [
        'room_name', 'jitsi_room_id', 'host_name', 'meeting_type',
        'access_type', 'max_participants', 'is_active', 'is_ended', 'created_at'
    ]
    list_filter = ['meeting_type', 'access_type', 'is_active', 'is_ended', 'created_at']
    search_fields = ['room_name', 'jitsi_room_id', 'host_name', 'host_email']
    readonly_fields = ['id', 'jitsi_room_id', 'created_at', 'ended_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'room_name', 'jitsi_room_id', 'jitsi_server_url')
        }),
        ('Host', {
            'fields': ('host', 'host_name', 'host_email')
        }),
        ('Meeting Settings', {
            'fields': ('meeting_type', 'access_type', 'password', 'max_participants')
        }),
        ('Features', {
            'fields': ('is_recording_enabled', 'is_live_streaming_enabled', 'is_waiting_room_enabled')
        }),
        ('Scheduling', {
            'fields': ('scheduled_start', 'scheduled_end'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'is_ended')
        }),
        ('Invites', {
            'fields': ('invite_emails',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'ended_at'),
        }),
    )


@admin.register(JitsiParticipant)
class JitsiParticipantAdmin(admin.ModelAdmin):
    list_display = [
        'participant_name', 'room', 'is_host', 'is_moderator',
        'joined_at', 'left_at'
    ]
    list_filter = ['is_host', 'is_moderator', 'joined_at']
    search_fields = ['participant_name', 'participant_email', 'room__jitsi_room_id']
    readonly_fields = ['id', 'joined_at']
    ordering = ['-joined_at']
    
    fieldsets = (
        ('Participant Info', {
            'fields': ('id', 'room', 'participant_name', 'participant_email')
        }),
        ('User', {
            'fields': ('user',)
        }),
        ('Jitsi Connection', {
            'fields': ('jitsi_connection_id',)
        }),
        ('Roles', {
            'fields': ('is_host', 'is_moderator')
        }),
        ('Device Info', {
            'fields': ('ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('joined_at', 'left_at'),
        }),
    )


@admin.register(JitsiRecording)
class JitsiRecordingAdmin(admin.ModelAdmin):
    list_display = [
        'room', 'recording_type', 'status', 'duration_formatted',
        'file_size_mb', 'started_at', 'completed_at'
    ]
    list_filter = ['recording_type', 'status', 'created_at']
    search_fields = ['room__jitsi_room_id']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Recording Info', {
            'fields': ('id', 'room', 'recording_type', 'status')
        }),
        ('File', {
            'fields': ('recording_url', 'file_size', 'duration_seconds')
        }),
        ('Who Started', {
            'fields': ('started_by',)
        }),
        ('Timestamps', {
            'fields': ('started_at', 'completed_at', 'created_at'),
        }),
    )
