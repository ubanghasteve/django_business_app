from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import uuid
import string
import random


def generate_room_code():
    """Generate a unique 8-character alphanumeric room code."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))


class VideoCallRoom(models.Model):
    """Model representing a video call room."""
    
    ROOM_TYPES = [
        ('one_to_one', 'One-to-One'),
        ('group', 'Group'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(
        max_length=8,
        unique=True,
        default=generate_room_code,
        db_index=True
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosted_rooms',
        null=True,
        blank=True
    )
    room_name = models.CharField(max_length=255)
    room_type = models.CharField(
        max_length=20,
        choices=ROOM_TYPES,
        default='one_to_one'
    )
    max_participants = models.IntegerField(default=10)
    is_active = models.BooleanField(default=True)
    password = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Host Control Fields
    is_locked = models.BooleanField(default=False, help_text="Prevent new participants from joining")
    mute_all_audio = models.BooleanField(default=False, help_text="Mute audio for all participants")
    mute_all_video = models.BooleanField(default=False, help_text="Turn off video for all participants")
    allow_participants_to_unmute = models.BooleanField(default=True, help_text="Allow participants to unmute themselves")
    allow_participants_to_share = models.BooleanField(default=True, help_text="Allow screen sharing")
    waiting_room_enabled = models.BooleanField(default=False, help_text="Participants wait for host approval")
    
    class Meta:
        verbose_name = 'Video Call Room'
        verbose_name_plural = 'Video Call Rooms'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.room_name} ({self.room_code})"
    
    @property
    def is_group_room(self):
        return self.room_type == 'group'
    
    @property
    def participant_count(self):
        return self.participants.filter(left_at__isnull=True).count()
    
    def end_room(self):
        """End the video call room."""
        self.is_active = False
        self.ended_at = timezone.now()
        self.save()
        self.participants.filter(left_at__isnull=True).update(left_at=timezone.now())
    
    def has_password(self):
        return bool(self.password)


class ScheduledMeeting(models.Model):
    """Model for scheduled video meetings with unique join links."""
    
    MEETING_STATUS = [
        ('scheduled', 'Scheduled'),
        ('started', 'Started'),
        ('ended', 'Ended'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scheduled_meetings'
    )
    meeting_title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    scheduled_start = models.DateTimeField()
    scheduled_duration = models.IntegerField(default=60, help_text="Duration in minutes")
    max_participants = models.IntegerField(default=10)
    
    meeting_code = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        help_text="Unique code for the meeting link"
    )
    join_link_slug = models.SlugField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="URL-friendly slug for joining"
    )
    
    password = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=20, choices=MEETING_STATUS, default='scheduled')
    
    room = models.ForeignKey(
        VideoCallRoom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scheduled_meetings',
        help_text="The actual video room created for this meeting"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Scheduled Meeting'
        verbose_name_plural = 'Scheduled Meetings'
        ordering = ['-scheduled_start']
    
    def __str__(self):
        return f"{self.meeting_title} ({self.meeting_code})"
    
    def generate_meeting_code(self):
        """Generate a unique meeting code."""
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=8))
    
    def generate_join_link_slug(self):
        """Generate a unique URL slug."""
        return uuid.uuid4().hex[:12]
    
    def save(self, *args, **kwargs):
        if not self.meeting_code:
            self.meeting_code = self.generate_meeting_code()
        if not self.join_link_slug:
            self.join_link_slug = self.generate_join_link_slug()
        super().save(*args, **kwargs)
    
    def get_full_meeting_link(self, request=None):
        """Get the full meeting join link."""
        if request:
            base_url = request.build_absolute_uri('/').rstrip('/')
        else:
            base_url = getattr(settings, 'BASE_URL', 'http://localhost:8000')
        return f"{base_url}/videocalls/join/{self.join_link_slug}/"
    
    def get_meeting_link(self):
        """Get the meeting join URL path."""
        return f"/videocalls/join/{self.join_link_slug}/"
    
    def has_password(self):
        return bool(self.password)
    
    @property
    def is_upcoming(self):
        return self.scheduled_start > timezone.now() and self.status == 'scheduled'
    
    @property
    def is_ongoing(self):
        return self.status == 'started'
    
    @property
    def can_join(self):
        return self.status in ['scheduled', 'started'] and self.scheduled_start <= timezone.now() + timedelta(minutes=self.scheduled_duration)
    
    def start_meeting(self):
        """Start the meeting and create the room."""
        if self.status != 'scheduled':
            return None
        
        self.status = 'started'
        self.save()
        
        if not self.room:
            room = VideoCallRoom.objects.create(
                room_name=self.meeting_title,
                host=self.host,
                max_participants=self.max_participants,
                password=self.password if self.password else None,
            )
            self.room = room
            self.save()
        
        return self.room
    
    def end_meeting(self):
        """End the meeting."""
        self.status = 'ended'
        if self.room:
            self.room.end_room()
        self.save()
    
    def cancel_meeting(self):
        """Cancel the meeting."""
        self.status = 'cancelled'
        self.save()


class MeetingInvitation(models.Model):
    """Model for meeting invitations sent to participants."""
    
    RSVP_STATUS = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(
        ScheduledMeeting,
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    email = models.EmailField()
    invitee_name = models.CharField(max_length=255, blank=True)
    rsvp_status = models.CharField(max_length=20, choices=RSVP_STATUS, default='pending')
    invited_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Meeting Invitation'
        verbose_name_plural = 'Meeting Invitations'
        unique_together = ['meeting', 'email']
        ordering = ['-invited_at']
    
    def __str__(self):
        return f"Invitation for {self.email} to {self.meeting.meeting_title}"


class CallParticipant(models.Model):
    """Model representing a participant in a video call room."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        VideoCallRoom,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='call_participations',
        null=True,
        blank=True
    )
    participant_name = models.CharField(max_length=255, blank=True)
    session_id = models.CharField(max_length=255, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    is_host = models.BooleanField(default=False)
    is_screen_sharing = models.BooleanField(default=False)
    is_audio_muted = models.BooleanField(default=False)
    is_video_off = models.BooleanField(default=False)
    is_recording = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Call Participant'
        verbose_name_plural = 'Call Participants'
        ordering = ['joined_at']
        unique_together = ['room', 'session_id']
    
    def __str__(self):
        name = self.user.get_full_name() if self.user else self.participant_name
        return f"{name} in {self.room.room_code}"
    
    @property
    def display_name(self):
        if self.user:
            return self.user.get_full_name() or self.user.email
        return self.participant_name or 'Guest'
    
    @property
    def allow_screen_share(self):
        return self.room.allow_participants_to_share or self.is_host
    
    def leave(self):
        """Mark participant as left."""
        self.left_at = timezone.now()
        self.save()


class SignalMessage(models.Model):
    """Model for WebRTC signaling messages (offer, answer, ICE candidates)."""
    
    MESSAGE_TYPES = [
        ('offer', 'SDP Offer'),
        ('answer', 'SDP Answer'),
        ('ice_candidate', 'ICE Candidate'),
        ('screen_share_start', 'Screen Share Start'),
        ('screen_share_stop', 'Screen Share Stop'),
        ('chat', 'Chat Message'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        VideoCallRoom,
        on_delete=models.CASCADE,
        related_name='signal_messages'
    )
    sender_session_id = models.CharField(max_length=255)
    target_session_id = models.CharField(max_length=255, blank=True)
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Signal Message'
        verbose_name_plural = 'Signal Messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['room', 'is_read', 'created_at']),
            models.Index(fields=['target_session_id', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.message_type} from {self.sender_session_id} in {self.room.room_code}"


class CallRecording(models.Model):
    """Model for storing video call recordings."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        VideoCallRoom,
        on_delete=models.CASCADE,
        related_name='recordings'
    )
    recording_file = models.FileField(
        upload_to='videocalls/recordings/%Y/%m/%d/',
        null=True,
        blank=True
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='call_recordings',
        null=True,
        blank=True
    )
    duration_seconds = models.IntegerField(default=0)
    file_size = models.BigIntegerField(default=0)
    file_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Call Recording'
        verbose_name_plural = 'Call Recordings'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Recording from {self.room.room_code} - {self.created_at}"
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)
    
    @property
    def duration_formatted(self):
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class CallSession(models.Model):
    """Model for tracking video call sessions."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        VideoCallRoom,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    session_id = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    peak_participants = models.IntegerField(default=0)
    total_messages = models.IntegerField(default=0)
    
    class Meta:
        verbose_name = 'Call Session'
        verbose_name_plural = 'Call Sessions'
        ordering = ['-started_at']
        unique_together = ['room', 'session_id']
    
    def __str__(self):
        return f"Session {self.session_id} in {self.room.room_code}"
    
    @property
    def duration_seconds(self):
        if self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return int((timezone.now() - self.started_at).total_seconds())
    
    @property
    def duration_formatted(self):
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class JitsiRoom(models.Model):
    """
    Model representing a Jitsi Meet conference room.
    Jitsi uses SFU (Selective Forwarding Unit) architecture for handling
    300+ participants efficiently.
    """
    
    MEETING_TYPES = [
        ('instant', 'Instant Meeting'),
        ('scheduled', 'Scheduled Meeting'),
        ('recurring', 'Recurring Meeting'),
    ]
    
    ACCESS_TYPES = [
        ('public', 'Public - Anyone with link can join'),
        ('private', 'Private - Host must approve'),
        ('password', 'Password Protected'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_name = models.CharField(
        max_length=255,
        help_text="Meeting name/title"
    )
    jitsi_room_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique Jitsi room identifier"
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosted_jitsi_rooms',
        null=True,
        blank=True
    )
    host_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Display name of the host"
    )
    host_email = models.EmailField(
        blank=True,
        help_text="Email of the host"
    )
    
    meeting_type = models.CharField(
        max_length=20,
        choices=MEETING_TYPES,
        default='instant'
    )
    access_type = models.CharField(
        max_length=20,
        choices=ACCESS_TYPES,
        default='public'
    )
    password = models.CharField(
        max_length=128,
        blank=True,
        help_text="Meeting password (if password-protected)"
    )
    
    max_participants = models.IntegerField(
        default=300,
        help_text="Maximum participants allowed (Jitsi supports 300+)"
    )
    
    is_recording_enabled = models.BooleanField(
        default=False,
        help_text="Enable cloud recording"
    )
    is_live_streaming_enabled = models.BooleanField(
        default=False,
        help_text="Enable live streaming"
    )
    is_waiting_room_enabled = models.BooleanField(
        default=False,
        help_text="Participants wait for host approval"
    )
    
    allow_participants_to_share_screen = models.BooleanField(
        default=True,
        help_text="Allow participants to share their screen"
    )
    allow_participants_to_chat = models.BooleanField(
        default=True,
        help_text="Allow in-meeting chat"
    )
    allow_participants_to_unmute = models.BooleanField(
        default=True,
        help_text="Allow participants to unmute themselves"
    )
    mute_on_join = models.BooleanField(
        default=False,
        help_text="Mute all participants when they join"
    )
    video_mute_on_join = models.BooleanField(
        default=False,
        help_text="Turn off video of all participants when they join"
    )
    
    scheduled_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled start time"
    )
    scheduled_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled end time"
    )
    
    is_active = models.BooleanField(default=True)
    is_ended = models.BooleanField(default=False)
    
    jitsi_server_url = models.CharField(
        max_length=500,
        default='https://meet.jit.si',
        help_text="Jitsi server URL (use your own for production)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    invite_emails = models.TextField(
        blank=True,
        help_text="Comma-separated list of emails to invite"
    )
    
    class Meta:
        verbose_name = 'Jitsi Meet Room'
        verbose_name_plural = 'Jitsi Meet Rooms'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.room_name} ({self.jitsi_room_id})"
    
    @property
    def meeting_url(self):
        """Generate the full Jitsi meeting URL."""
        base_url = self.jitsi_server_url.rstrip('/')
        return f"{base_url}/{self.jitsi_room_id}"
    
    @property
    def participant_count(self):
        """Get current participant count."""
        return JitsiParticipant.objects.filter(
            room=self,
            left_at__isnull=True
        ).count()
    
    def end_room(self):
        """End the Jitsi meeting."""
        self.is_active = False
        self.is_ended = True
        self.ended_at = timezone.now()
        self.save()
        JitsiParticipant.objects.filter(
            room=self,
            left_at__isnull=True
        ).update(left_at=timezone.now())
    
    def has_password(self):
        return bool(self.password)
    
    @staticmethod
    def generate_jitsi_room_id():
        """Generate a unique Jitsi room ID."""
        chars = string.ascii_lowercase + string.digits
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_part = ''.join(random.choices(chars, k=8))
        return f"vc-{timestamp}-{random_part}"


class JitsiParticipant(models.Model):
    """Model for tracking participants in Jitsi meetings."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        JitsiRoom,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='jitsi_participations',
        null=True,
        blank=True
    )
    participant_name = models.CharField(max_length=255)
    participant_email = models.EmailField(blank=True)
    jitsi_connection_id = models.CharField(max_length=255, blank=True)
    
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    
    is_host = models.BooleanField(default=False)
    is_moderator = models.BooleanField(default=False)
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        verbose_name = 'Jitsi Participant'
        verbose_name_plural = 'Jitsi Participants'
        ordering = ['joined_at']
    
    def __str__(self):
        return f"{self.participant_name} in {self.room.jitsi_room_id}"
    
    @property
    def display_name(self):
        if self.user:
            return self.user.get_full_name() or self.user.email
        return self.participant_name or 'Guest'
    
    def leave(self):
        self.left_at = timezone.now()
        self.save()


class JitsiRecording(models.Model):
    """Model for storing Jitsi meeting recordings."""
    
    RECORDING_TYPES = [
        ('local', 'Local Recording'),
        ('cloud', 'Cloud Recording'),
        ('livestream', 'Live Stream'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('recording', 'Recording'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(
        JitsiRoom,
        on_delete=models.CASCADE,
        related_name='recordings'
    )
    recording_type = models.CharField(
        max_length=20,
        choices=RECORDING_TYPES,
        default='local'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    recording_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL to the recorded video"
    )
    duration_seconds = models.IntegerField(default=0)
    file_size = models.BigIntegerField(default=0)
    
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='jitsi_recordings',
        null=True,
        blank=True
    )
    
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Jitsi Recording'
        verbose_name_plural = 'Jitsi Recordings'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Recording - {self.room.jitsi_room_id} ({self.status})"
    
    @property
    def duration_formatted(self):
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)
