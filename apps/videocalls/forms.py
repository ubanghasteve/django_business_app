from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field, HTML, Div
from crispy_forms.bootstrap import FormActions
from .models import VideoCallRoom, CallParticipant, JitsiRoom


class CreateRoomForm(forms.ModelForm):
    """Form for creating a new video call room."""
    
    use_password = forms.BooleanField(
        required=False,
        label='Password Protection',
        help_text='Require a password to join this room'
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Enter room password',
            'class': 'form-control',
            'id': 'id_password'
        })
    )
    
    class Meta:
        model = VideoCallRoom
        fields = ['room_name', 'room_type', 'max_participants']
        widgets = {
            'room_name': forms.TextInput(attrs={
                'placeholder': 'Enter room name',
                'class': 'form-control'
            }),
            'room_type': forms.Select(attrs={'class': 'form-select'}),
            'max_participants': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 2,
                'max': 50
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'create-room-form'
        self.helper.layout = Layout(
            Field('room_name'),
            Field('room_type'),
            Field('max_participants'),
            Field('use_password'),
            HTML('<div id="password-field" style="display:none;">'),
            Field('password'),
            HTML('</div>'),
            FormActions(
                Submit('create', 'Create Room', css_class='btn-primary w-100'),
            )
        )
    
    def clean(self):
        cleaned_data = super().clean()
        room_type = cleaned_data.get('room_type')
        max_participants = cleaned_data.get('max_participants')
        
        if room_type == 'one_to_one':
            cleaned_data['max_participants'] = 2
        elif max_participants < 2:
            self.add_error('max_participants', 'Maximum participants must be at least 2.')
        elif max_participants > 50:
            self.add_error('max_participants', 'Maximum participants cannot exceed 50.')
        
        return cleaned_data


class JoinRoomForm(forms.Form):
    """Form for joining an existing video call room."""
    
    room_code = forms.CharField(
        max_length=8,
        min_length=8,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter room code',
            'class': 'form-control text-center text-uppercase',
            'maxlength': 8
        }),
        help_text='Enter the 8-character room code'
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Enter room password (if required)',
            'class': 'form-control'
        })
    )
    display_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your display name (for guests)',
            'class': 'form-control'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'join-room-form'
        self.helper.layout = Layout(
            Field('room_code'),
            Field('password'),
            Field('display_name'),
            FormActions(
                Submit('join', 'Join Room', css_class='btn-primary w-100'),
            )
        )
    
    def clean_room_code(self):
        room_code = self.cleaned_data.get('room_code', '').upper()
        return room_code


class ParticipantForm(forms.ModelForm):
    """Form for updating participant settings."""
    
    class Meta:
        model = CallParticipant
        fields = ['participant_name']
        widgets = {
            'participant_name': forms.TextInput(attrs={
                'placeholder': 'Enter your display name',
                'class': 'form-control'
            }),
        }


class RoomSettingsForm(forms.ModelForm):
    """Form for updating room settings (host only)."""
    
    class Meta:
        model = VideoCallRoom
        fields = ['room_name', 'max_participants', 'password']
        widgets = {
            'room_name': forms.TextInput(attrs={
                'placeholder': 'Room name',
                'class': 'form-control'
            }),
            'max_participants': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 2,
                'max': 50
            }),
            'password': forms.PasswordInput(attrs={
                'placeholder': 'New password (leave empty to remove)',
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'room-settings-form'
        self.helper.layout = Layout(
            Field('room_name'),
            Field('max_participants'),
            Field('password'),
            FormActions(
                Submit('save', 'Save Settings', css_class='btn-primary'),
            )
        )


class CreateJitsiRoomForm(forms.ModelForm):
    """Form for creating a new Jitsi Meet room (supports 300+ participants)."""
    
    invite_emails_input = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'placeholder': 'Enter email addresses separated by commas',
            'class': 'form-control',
            'rows': 3,
            'id': 'id_invite_emails_input'
        }),
        help_text='Invite people by email (optional)'
    )
    
    class Meta:
        model = JitsiRoom
        fields = [
            'room_name', 'meeting_type', 'access_type', 'password',
            'max_participants', 'is_recording_enabled', 'is_waiting_room_enabled',
            'allow_participants_to_share_screen', 'allow_participants_to_chat',
            'allow_participants_to_unmute', 'mute_on_join', 'video_mute_on_join'
        ]
        widgets = {
            'room_name': forms.TextInput(attrs={
                'placeholder': 'Enter meeting name',
                'class': 'form-control'
            }),
            'meeting_type': forms.Select(attrs={'class': 'form-select'}),
            'access_type': forms.Select(attrs={'class': 'form-select'}),
            'password': forms.PasswordInput(attrs={
                'placeholder': 'Meeting password (if protected)',
                'class': 'form-control'
            }),
            'max_participants': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 2,
                'max': 500
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'create-jitsi-room-form'
        self.helper.layout = Layout(
            Field('room_name'),
            Row(
                Column('meeting_type', css_class='col-md-6'),
                Column('access_type', css_class='col-md-6'),
            ),
            Div(
                Field('password'),
                css_class='password-field-wrapper'
            ),
            Field('max_participants'),
            
            HTML('<hr><h5 class="mt-3 mb-3"><i class="bi bi-shield-check me-2"></i>Host Controls</h5>'),
            
            Row(
                Column('is_recording_enabled', css_class='col-md-6'),
                Column('is_waiting_room_enabled', css_class='col-md-6'),
            ),
            
            HTML('<hr><h5 class="mt-3 mb-3"><i class="bi bi-person-gear me-2"></i>Participant Permissions</h5>'),
            
            Row(
                Column('allow_participants_to_share_screen', css_class='col-md-6'),
                Column('allow_participants_to_chat', css_class='col-md-6'),
            ),
            Row(
                Column('allow_participants_to_unmute', css_class='col-md-6'),
                Column('mute_on_join', css_class='col-md-6'),
            ),
            Field('video_mute_on_join'),
            
            HTML('<hr>'),
            Field('invite_emails_input'),
            HTML('<div class="alert alert-info">'),
            HTML('<i class="bi bi-info-circle"></i> This meeting uses Jitsi Meet technology and supports up to 500+ participants.'),
            HTML('</div>'),
            FormActions(
                Submit('create', 'Create Meeting', css_class='btn-primary w-100'),
            )
        )
    
    def clean(self):
        cleaned_data = super().clean()
        access_type = cleaned_data.get('access_type')
        password = cleaned_data.get('password')
        invite_emails = cleaned_data.get('invite_emails_input', '')
        
        if access_type == 'password' and not password:
            self.add_error('password', 'Password is required for password-protected meetings.')
        
        cleaned_data['invite_emails'] = invite_emails
        return cleaned_data


class JoinJitsiRoomForm(forms.Form):
    """Form for joining a Jitsi Meet room."""
    
    room_id = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter meeting ID',
            'class': 'form-control'
        }),
        help_text='The unique meeting identifier'
    )
    display_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your display name',
            'class': 'form-control'
        })
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Meeting password (if required)',
            'class': 'form-control'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'join-jitsi-room-form'
        self.helper.layout = Layout(
            Field('room_id'),
            Field('display_name'),
            Field('password'),
            FormActions(
                Submit('join', 'Join Meeting', css_class='btn-primary w-100'),
            )
        )
