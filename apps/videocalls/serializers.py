from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import VideoCallRoom, CallParticipant, SignalMessage, CallRecording, CallSession

User = get_user_model()


class UserBriefSerializer(serializers.ModelSerializer):
    """Brief serializer for user data in video call context."""
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'profile_picture']
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['full_name'] = instance.get_full_name()
        data['initials'] = ''.join([n[0] for n in instance.get_full_name().split() if n])[:2].upper()
        return data


class CallParticipantSerializer(serializers.ModelSerializer):
    """Serializer for call participants."""
    
    user = UserBriefSerializer(read_only=True)
    display_name = serializers.ReadOnlyField()
    allow_screen_share = serializers.ReadOnlyField()
    
    class Meta:
        model = CallParticipant
        fields = [
            'id', 'room', 'user', 'participant_name', 'session_id',
            'joined_at', 'left_at', 'is_host', 'is_screen_sharing',
            'is_audio_muted', 'is_video_off', 'display_name',
            'allow_screen_share'
        ]
        read_only_fields = ['id', 'joined_at', 'left_at']


class CallParticipantCreateSerializer(serializers.Serializer):
    """Serializer for creating a new participant."""
    
    session_id = serializers.CharField(max_length=255)
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    password = serializers.CharField(max_length=128, required=False, allow_blank=True)


class VideoCallRoomSerializer(serializers.ModelSerializer):
    """Serializer for video call rooms."""
    
    host = UserBriefSerializer(read_only=True)
    participant_count = serializers.ReadOnlyField()
    is_group_room = serializers.ReadOnlyField()
    has_password = serializers.SerializerMethodField()
    active_participants = serializers.SerializerMethodField()
    
    class Meta:
        model = VideoCallRoom
        fields = [
            'id', 'room_code', 'host', 'room_name', 'room_type',
            'max_participants', 'is_active', 'has_password', 'password',
            'created_at', 'ended_at', 'participant_count', 'is_group_room',
            'active_participants', 'is_locked', 'mute_all_audio', 'mute_all_video',
            'allow_participants_to_unmute', 'allow_participants_to_share',
            'waiting_room_enabled'
        ]
        read_only_fields = ['id', 'room_code', 'host', 'created_at', 'ended_at']
    
    def get_has_password(self, obj):
        return obj.has_password()
    
    def get_active_participants(self, obj):
        participants = obj.participants.filter(left_at__isnull=True)
        return CallParticipantSerializer(participants, many=True).data


class VideoCallRoomCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new video call room."""
    
    password = serializers.CharField(max_length=128, required=False, allow_blank=True, write_only=True)
    
    class Meta:
        model = VideoCallRoom
        fields = ['room_name', 'room_type', 'max_participants', 'password']
    
    def validate_max_participants(self, value):
        if value < 2:
            raise serializers.ValidationError('Maximum participants must be at least 2.')
        if value > 50:
            raise serializers.ValidationError('Maximum participants cannot exceed 50.')
        return value
    
    def validate_room_type(self, value):
        if value not in ['one_to_one', 'group']:
            raise serializers.ValidationError('Invalid room type.')
        return value
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        room = VideoCallRoom.objects.create(**validated_data)
        if password:
            room.password = password
            room.save()
        return room


class SignalMessageSerializer(serializers.ModelSerializer):
    """Serializer for signaling messages."""
    
    class Meta:
        model = SignalMessage
        fields = [
            'id', 'room', 'sender_session_id', 'target_session_id',
            'message_type', 'payload', 'created_at', 'is_read'
        ]
        read_only_fields = ['id', 'created_at']


class SignalMessageCreateSerializer(serializers.Serializer):
    """Serializer for creating signaling messages."""
    
    room_code = serializers.CharField(max_length=8)
    sender_session_id = serializers.CharField(max_length=255)
    target_session_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    message_type = serializers.ChoiceField(choices=SignalMessage.MESSAGE_TYPES)
    payload = serializers.JSONField(default=dict)


class CallRecordingSerializer(serializers.ModelSerializer):
    """Serializer for call recordings."""
    
    recorded_by = UserBriefSerializer(read_only=True)
    file_size_mb = serializers.ReadOnlyField()
    duration_formatted = serializers.ReadOnlyField()
    
    class Meta:
        model = CallRecording
        fields = [
            'id', 'room', 'recording_file', 'recorded_by', 'duration_seconds',
            'file_size', 'file_name', 'created_at', 'file_size_mb', 'duration_formatted'
        ]
        read_only_fields = ['id', 'created_at', 'file_size', 'duration_seconds']


class CallRecordingCreateSerializer(serializers.Serializer):
    """Serializer for creating/updating recordings."""
    
    room_code = serializers.CharField(max_length=8)
    recording_data = serializers.CharField()
    duration_seconds = serializers.IntegerField(min_value=0)
    file_name = serializers.CharField(max_length=255)


class CallSessionSerializer(serializers.ModelSerializer):
    """Serializer for call sessions."""
    
    duration_formatted = serializers.ReadOnlyField()
    
    class Meta:
        model = CallSession
        fields = [
            'id', 'room', 'session_id', 'started_at', 'ended_at',
            'peak_participants', 'total_messages', 'duration_formatted'
        ]
        read_only_fields = ['id', 'started_at']


class RoomStatusSerializer(serializers.Serializer):
    """Serializer for room status response."""
    
    room_code = serializers.CharField()
    is_active = serializers.BooleanField()
    participant_count = serializers.IntegerField()
    max_participants = serializers.IntegerField()
    is_full = serializers.BooleanField()
    has_password = serializers.BooleanField()
    host_id = serializers.IntegerField(allow_null=True)
    participants = CallParticipantSerializer(many=True)
