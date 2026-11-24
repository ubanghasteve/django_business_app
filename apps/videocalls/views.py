from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden, FileResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
import json
import uuid
import base64
import os

from .models import (
    VideoCallRoom, CallParticipant, SignalMessage,
    CallRecording, CallSession, JitsiRoom, JitsiParticipant, JitsiRecording,
    ScheduledMeeting, MeetingInvitation
)
from .forms import CreateRoomForm, JoinRoomForm, ParticipantForm, RoomSettingsForm, CreateJitsiRoomForm, JoinJitsiRoomForm
from .serializers import (
    VideoCallRoomSerializer, VideoCallRoomCreateSerializer,
    CallParticipantSerializer, SignalMessageSerializer,
    SignalMessageCreateSerializer, CallRecordingSerializer,
    RoomStatusSerializer
)


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def generate_session_id():
    """Generate a unique session ID for a participant."""
    return str(uuid.uuid4())


@login_required
@permission_required('videocalls.add_videocallroom', raise_exception=True)
def create_room_view(request):
    """View for creating a new video call room."""
    if request.method == 'POST':
        form = CreateRoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.host = request.user
            
            use_password = form.cleaned_data.get('use_password', False)
            password = form.cleaned_data.get('password', '')
            
            if use_password and password:
                room.password = password
            
            room.save()
            messages.success(request, f'Room "{room.room_name}" created successfully!')
            return redirect('videocalls:room', room_code=room.room_code)
    else:
        form = CreateRoomForm()
    
    return render(request, 'videocalls/create_room.html', {
        'form': form,
        'page_title': 'Create Video Room'
    })


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def join_room_view(request, room_code=None):
    """View for joining an existing video call room."""
    if request.method == 'POST':
        form = JoinRoomForm(request.POST)
        if form.is_valid():
            room_code_input = form.cleaned_data['room_code'].upper()
            password = form.cleaned_data.get('password', '')
            display_name = form.cleaned_data.get('display_name', '')
            
            try:
                room = VideoCallRoom.objects.get(room_code=room_code_input)
                
                if not room.is_active:
                    messages.error(request, 'This room is no longer active.')
                    return redirect('videocalls:join_room')
                
                if room.has_password():
                    if not password or room.password != password:
                        messages.error(request, 'Invalid room password.')
                        return redirect('videocalls:join_room')
                
                if room.participant_count >= room.max_participants:
                    messages.error(request, 'This room is full.')
                    return redirect('videocalls:join_room')
                
                if request.user.is_authenticated:
                    display_name = request.user.get_full_name()
                
                session_id = generate_session_id()
                participant, created = CallParticipant.objects.get_or_create(
                    room=room,
                    session_id=session_id,
                    defaults={
                        'user': request.user if request.user.is_authenticated else None,
                        'participant_name': display_name,
                        'is_host': room.host == request.user if request.user.is_authenticated else False
                    }
                )
                
                if not created:
                    participant.left_at = None
                    participant.save()
                
                return redirect('videocalls:room', room_code=room.room_code)
                
            except VideoCallRoom.DoesNotExist:
                messages.error(request, 'Room not found.')
                return redirect('videocalls:join_room')
    else:
        form = JoinRoomForm()
    
    return render(request, 'videocalls/join_room.html', {
        'form': form,
        'page_title': 'Join Video Room',
        'room_code': room_code
    })


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def room_detail_view(request, room_code):
    """View for entering a video call room - uses SFU for large meetings."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
    except VideoCallRoom.DoesNotExist:
        messages.error(request, 'Room not found.')
        return redirect('videocalls:create_room')
    
    if not room.is_active:
        messages.error(request, 'This room is no longer active.')
        return redirect('videocalls:create_room')
    
    use_sfu = settings.MEDIASOUP_ENABLED and room.max_participants > settings.MEDIASOUP_LARGE_ROOM_THRESHOLD
    
    site_url = getattr(settings, 'VIDEO_CALL_SITE_URL', None)
    if not site_url:
        site_url = request.build_absolute_uri('/videocalls/').rstrip('/')
    
    display_name_session_key = f'videocall_display_name_{room.room_code}'
    prejoin_display_name = request.session.get(display_name_session_key, '')

    context = {
        'room': room,
        'page_title': f'{room.room_name} - Video Call',
        'is_host': room.host == request.user if request.user.is_authenticated else False,
        'use_sfu': use_sfu,
        'site_url': site_url,
        'prejoin_display_name': prejoin_display_name,
    }
    
    if use_sfu:
        return render(request, 'videocalls/sfu_room.html', context)
    
    return render(request, 'videocalls/room.html', context)


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def prejoin_room_view(request, room_code):
    """Name-first pre-join page before entering the video room."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
    except VideoCallRoom.DoesNotExist:
        messages.error(request, 'Room not found.')
        return redirect('videocalls:create_room')

    if not room.is_active:
        messages.error(request, 'This room is no longer active.')
        return redirect('videocalls:create_room')

    display_name_session_key = f'videocall_display_name_{room.room_code}'
    initial_name = ''
    if request.user.is_authenticated:
        initial_name = request.user.get_full_name() or request.user.email or ''
    if not initial_name:
        initial_name = request.session.get(display_name_session_key, '')

    if request.method == 'POST':
        display_name = request.POST.get('display_name', '').strip()
        if not display_name:
            messages.error(request, 'Please enter your name before joining.')
        else:
            request.session[display_name_session_key] = display_name
            return redirect('videocalls:room', room_code=room.room_code)

    return render(request, 'videocalls/prejoin_room.html', {
        'room': room,
        'initial_name': initial_name,
        'page_title': f'Join {room.room_name}'
    })


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def leave_room_view(request, room_code):
    """View for leaving a video call room."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
        
        session_id = request.headers.get('X-Session-Id', '')
        if session_id:
            try:
                participant = CallParticipant.objects.get(
                    room=room,
                    session_id=session_id
                )
                participant.leave()
                
                if participant.is_host and room.host == request.user:
                    remaining_participants = room.participants.filter(left_at__isnull=True).exclude(id=participant.id).count()
                    if remaining_participants == 0:
                        room.end_room()
                    else:
                        new_host = room.participants.filter(left_at__isnull=True).first()
                        if new_host:
                            new_host.is_host = True
                            new_host.save()
                            room.host = new_host.user
                            room.save()
            except CallParticipant.DoesNotExist:
                pass
        
        return JsonResponse({'success': True, 'message': 'Left room successfully'})
    except VideoCallRoom.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Room not found'}, status=404)


@login_required
@permission_required('videocalls.change_videocallroom', raise_exception=True)
def end_room_view(request, room_code):
    """View for ending a video call room (host only)."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
        
        if room.host != request.user:
            return JsonResponse({'success': False, 'error': 'Only the host can end this room'}, status=403)
        
        room.end_room()
        
        CallSession.objects.filter(room=room).update(ended_at=timezone.now())
        
        messages.success(request, 'Room ended successfully.')
        return JsonResponse({'success': True, 'message': 'Room ended successfully'})
    except VideoCallRoom.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Room not found'}, status=404)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def delete_room_api(request):
    """API endpoint for deleting a room (host only)."""
    room_code = request.data.get('room_code', '').upper()
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        if room.host != request.user:
            return Response({
                'success': False,
                'error': 'Only the host can delete this room'
            }, status=status.HTTP_403_FORBIDDEN)
        
        room_name = room.room_name
        room.delete()
        
        return Response({
            'success': True,
            'message': f'Room "{room_name}" deleted successfully'
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def room_list_view(request):
    """View for listing user's rooms."""
    hosted_rooms = VideoCallRoom.objects.filter(host=request.user).order_by('-created_at')[:20]
    participated_rooms = VideoCallRoom.objects.filter(
        participants__user=request.user,
        participants__left_at__isnull=True
    ).exclude(host=request.user).order_by('-created_at')[:20]
    
    return render(request, 'videocalls/room_list.html', {
        'hosted_rooms': hosted_rooms,
        'participated_rooms': participated_rooms,
        'page_title': 'My Video Rooms'
    })


@login_required
@permission_required('videocalls.view_callrecording', raise_exception=True)
def room_recordings_view(request, room_code):
    """View for listing recordings of a specific room."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
        
        if room.host != request.user:
            return HttpResponseForbidden('Only the host can view recordings.')
        
        recordings = room.recordings.all().order_by('-created_at')
        
        return render(request, 'videocalls/recordings.html', {
            'room': room,
            'recordings': recordings,
            'page_title': f'Recordings - {room.room_name}'
        })
    except VideoCallRoom.DoesNotExist:
        messages.error(request, 'Room not found.')
        return redirect('videocalls:my_rooms')


@login_required
@permission_required('videocalls.view_callrecording', raise_exception=True)
def download_recording_view(request, recording_id):
    """View for downloading a recording."""
    try:
        recording = CallRecording.objects.get(id=recording_id)
        
        if recording.room.host != request.user and recording.recorded_by != request.user:
            return HttpResponseForbidden('You do not have permission to download this recording.')
        
        if recording.recording_file:
            return FileResponse(
                recording.recording_file.open('rb'),
                as_attachment=True,
                filename=recording.file_name or f'recording_{recording.id}.webm'
            )
        else:
            messages.error(request, 'Recording file not found.')
            return redirect('videocalls:room_recordings', room_code=recording.room.room_code)
    except CallRecording.DoesNotExist:
        messages.error(request, 'Recording not found.')
        return redirect('videocalls:my_rooms')


@login_required
@permission_required('videocalls.view_videocallroom', raise_exception=True)
def lobby_view(request):
    """Lobby view for video calls with options to create or join."""
    return render(request, 'videocalls/lobby.html', {
        'page_title': 'Video Calls'
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def room_create_api(request):
    """API endpoint for creating a new room."""
    serializer = VideoCallRoomCreateSerializer(data=request.data)
    if serializer.is_valid():
        room = serializer.save()
        if request.user.is_authenticated:
            room.host = request.user
            room.save()
        return Response({
            'success': True,
            'room': VideoCallRoomSerializer(room).data
        }, status=status.HTTP_201_CREATED)
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def room_join_api(request):
    """API endpoint for joining a room."""
    room_code = request.data.get('room_code', '').upper()
    password = request.data.get('password', '')
    session_id = request.data.get('session_id', generate_session_id())
    display_name = (request.data.get('display_name', '') or '').strip()
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        if not room.is_active:
            return Response({
                'success': False,
                'error': 'Room is no longer active'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if room.has_password() and room.password != password:
            return Response({
                'success': False,
                'error': 'Invalid password'
            }, status=status.HTTP_403_FORBIDDEN)
        
        if room.participant_count >= room.max_participants:
            return Response({
                'success': False,
                'error': 'Room is full'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not display_name:
            session_display_name = request.session.get(f'videocall_display_name_{room.room_code}', '')
            display_name = (session_display_name or '').strip()

        participant, created = CallParticipant.objects.get_or_create(
            room=room,
            session_id=session_id,
            defaults={
                'user': request.user if request.user.is_authenticated else None,
                'participant_name': display_name or (request.user.get_full_name() if request.user.is_authenticated else 'Guest'),
                'is_host': room.host == request.user if request.user.is_authenticated else False
            }
        )
        
        if not created:
            participant.left_at = None
            if display_name and participant.participant_name != display_name:
                participant.participant_name = display_name
            participant.save()
        
        return Response({
            'success': True,
            'room': VideoCallRoomSerializer(room).data,
            'participant': CallParticipantSerializer(participant).data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])
def room_leave_api(request):
    """API endpoint for leaving a room."""
    room_code = request.data.get('room_code', '').upper()
    session_id = request.data.get('session_id', '')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        if session_id:
            try:
                participant = CallParticipant.objects.get(
                    room=room,
                    session_id=session_id
                )
                participant.leave()
                
                if participant.is_host:
                    remaining = room.participants.filter(left_at__isnull=True).exclude(id=participant.id).count()
                    if remaining == 0:
                        room.end_room()
                    else:
                        new_host = room.participants.filter(left_at__isnull=True).exclude(id=participant.id).first()
                        if new_host:
                            new_host.is_host = True
                            new_host.save()
                            room.host = new_host.user
                            room.save()
            except CallParticipant.DoesNotExist:
                pass
        
        return Response({'success': True})
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([AllowAny])
def room_status_api(request, room_code):
    """API endpoint for getting room status."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
        
        participants = room.participants.filter(left_at__isnull=True)
        
        data = {
            'room_code': room.room_code,
            'is_active': room.is_active,
            'participant_count': participants.count(),
            'max_participants': room.max_participants,
            'is_full': participants.count() >= room.max_participants,
            'has_password': room.has_password(),
            'host_id': room.host.id if room.host else None,
            'participants': CallParticipantSerializer(participants, many=True).data
        }
        
        return Response(data)
    except VideoCallRoom.DoesNotExist:
        return Response({
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])
def signaling_offer_api(request):
    """API endpoint for sending SDP offer."""
    serializer = SignalMessageCreateSerializer(data=request.data)
    if serializer.is_valid():
        room_code = serializer.validated_data['room_code']
        try:
            room = VideoCallRoom.objects.get(room_code=room_code.upper())
            
            signal_msg = SignalMessage.objects.create(
                room=room,
                sender_session_id=serializer.validated_data['sender_session_id'],
                target_session_id=serializer.validated_data.get('target_session_id', ''),
                message_type='offer',
                payload=serializer.validated_data['payload']
            )
            
            return Response({
                'success': True,
                'message_id': str(signal_msg.id)
            })
        except VideoCallRoom.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Room not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def signaling_answer_api(request):
    """API endpoint for sending SDP answer."""
    serializer = SignalMessageCreateSerializer(data=request.data)
    if serializer.is_valid():
        room_code = serializer.validated_data['room_code']
        try:
            room = VideoCallRoom.objects.get(room_code=room_code.upper())
            
            signal_msg = SignalMessage.objects.create(
                room=room,
                sender_session_id=serializer.validated_data['sender_session_id'],
                target_session_id=serializer.validated_data.get('target_session_id', ''),
                message_type='answer',
                payload=serializer.validated_data['payload']
            )
            
            return Response({
                'success': True,
                'message_id': str(signal_msg.id)
            })
        except VideoCallRoom.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Room not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def signaling_ice_api(request):
    """API endpoint for sending ICE candidate."""
    serializer = SignalMessageCreateSerializer(data=request.data)
    if serializer.is_valid():
        room_code = serializer.validated_data['room_code']
        try:
            room = VideoCallRoom.objects.get(room_code=room_code.upper())
            
            signal_msg = SignalMessage.objects.create(
                room=room,
                sender_session_id=serializer.validated_data['sender_session_id'],
                target_session_id=serializer.validated_data.get('target_session_id', ''),
                message_type='ice_candidate',
                payload=serializer.validated_data['payload']
            )
            
            return Response({
                'success': True,
                'message_id': str(signal_msg.id)
            })
        except VideoCallRoom.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Room not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def signaling_message_api(request):
    """Generic API endpoint for sending signaling messages."""
    serializer = SignalMessageCreateSerializer(data=request.data)
    if serializer.is_valid():
        room_code = serializer.validated_data['room_code']
        message_type = serializer.validated_data['message_type']
        
        try:
            room = VideoCallRoom.objects.get(room_code=room_code.upper())
            
            signal_msg = SignalMessage.objects.create(
                room=room,
                sender_session_id=serializer.validated_data['sender_session_id'],
                target_session_id=serializer.validated_data.get('target_session_id', ''),
                message_type=message_type,
                payload=serializer.validated_data['payload']
            )
            
            return Response({
                'success': True,
                'message_id': str(signal_msg.id)
            })
        except VideoCallRoom.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Room not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def signaling_messages_api(request):
    """API endpoint for polling signaling messages."""
    room_code = request.GET.get('room_code', '').upper()
    session_id = request.GET.get('session_id', '')
    last_message_id = request.GET.get('last_message_id', '')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        base_query = SignalMessage.objects.filter(
            room=room
        ).exclude(sender_session_id=session_id).filter(
            Q(target_session_id='') | Q(target_session_id=session_id)
        ).order_by('created_at', 'id')

        messages_query = base_query
        if last_message_id:
            try:
                last_msg = SignalMessage.objects.only('id', 'created_at').get(id=last_message_id, room=room)
                messages_query = messages_query.filter(
                    Q(created_at__gt=last_msg.created_at) |
                    Q(created_at=last_msg.created_at, id__gt=last_msg.id)
                )
            except SignalMessage.DoesNotExist:
                pass

        # Keep payload bounded while preserving order for deterministic handling.
        if last_message_id:
            messages = list(messages_query[:50])
        else:
            messages = list(base_query.order_by('-created_at')[:50])
            messages.reverse()

        messages_data = SignalMessageSerializer(messages, many=True).data
        
        return Response({
            'success': True,
            'messages': messages_data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_participants_api(request, room_code):
    """API endpoint for getting room participants."""
    try:
        room = VideoCallRoom.objects.get(room_code=room_code.upper())
        participants = room.participants.filter(left_at__isnull=True)
        
        return Response({
            'success': True,
            'participants': CallParticipantSerializer(participants, many=True).data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])
def update_participant_api(request):
    """API endpoint for updating participant status."""
    room_code = request.data.get('room_code', '').upper()
    session_id = request.data.get('session_id', '')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        participant = CallParticipant.objects.get(room=room, session_id=session_id)
        
        if 'is_audio_muted' in request.data:
            participant.is_audio_muted = request.data['is_audio_muted']
        if 'is_video_off' in request.data:
            participant.is_video_off = request.data['is_video_off']
        if 'is_screen_sharing' in request.data:
            participant.is_screen_sharing = request.data['is_screen_sharing']
        if 'participant_name' in request.data:
            participant.participant_name = request.data['participant_name']
        
        participant.save()
        
        return Response({
            'success': True,
            'participant': CallParticipantSerializer(participant).data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except CallParticipant.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Participant not found'
        }, status=status.HTTP_404_NOT_FOUND)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def upload_recording_api(request):
    """API endpoint for uploading recording to server."""
    room_code = request.data.get('room_code', '').upper()
    session_id = request.data.get('session_id', '')
    duration_seconds = int(request.data.get('duration_seconds', 0))
    file_name = request.data.get('file_name', f'recording_{uuid.uuid4().hex}.webm')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        participant = CallParticipant.objects.get(room=room, session_id=session_id)
        
        recording_data = request.data.get('recording_data')
        if not recording_data:
            return Response({
                'success': False,
                'error': 'No recording data provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            media_data = base64.b64decode(recording_data)
        except Exception:
            return Response({
                'success': False,
                'error': 'Invalid recording data format'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'videocalls', 'recordings', 
                                  timezone.now().strftime('%Y'), timezone.now().strftime('%m'))
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, file_name)
        with open(file_path, 'wb') as f:
            f.write(media_data)
        
        file_size = len(media_data)
        
        recording = CallRecording.objects.create(
            room=room,
            recorded_by=request.user if request.user.is_authenticated else participant.user,
            duration_seconds=duration_seconds,
            file_size=file_size,
            file_name=file_name
        )
        
        from django.core.files import File
        with open(file_path, 'rb') as f:
            recording.recording_file.save(file_name, File(f), save=True)
        
        return Response({
            'success': True,
            'recording': CallRecordingSerializer(recording).data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except CallParticipant.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Participant not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([AllowAny])
def recording_detail_api(request, recording_id):
    """API endpoint for getting recording details."""
    try:
        recording = CallRecording.objects.get(id=recording_id)
        
        if recording.room.host != request.user and recording.recorded_by != request.user:
            return Response({
                'error': 'Permission denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        return Response({
            'success': True,
            'recording': CallRecordingSerializer(recording).data
        })
    except CallRecording.DoesNotExist:
        return Response({
            'error': 'Recording not found'
        }, status=status.HTTP_404_NOT_FOUND)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_room_settings_api(request):
    """API endpoint for updating room settings (host only)."""
    room_code = request.data.get('room_code', '').upper()
    session_id = request.data.get('session_id', '')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        if room.host != request.user:
            participant = CallParticipant.objects.get(room=room, session_id=session_id)
            if not participant.is_host:
                return Response({
                    'success': False,
                    'error': 'Only the host can update room settings'
                }, status=status.HTTP_403_FORBIDDEN)
        
        if 'room_name' in request.data:
            room.room_name = request.data['room_name']
        if 'max_participants' in request.data:
            room.max_participants = max(2, min(50, request.data['max_participants']))
        if 'password' in request.data:
            room.password = request.data['password'] if request.data['password'] else None
        
        room.save()
        
        return Response({
            'success': True,
            'room': VideoCallRoomSerializer(room).data
        })
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@ensure_csrf_cookie
def get_csrf_token(request):
    """API endpoint to get CSRF token."""
    return JsonResponse({'csrfToken': request.META.get('CSRF_COOKIE', '')})


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def host_control_api(request):
    """API endpoint for host control actions."""
    room_code = request.data.get('room_code', '').upper()
    session_id = request.data.get('session_id', '')
    action = request.data.get('action', '')
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
        
        # Check if user is host
        is_host = False
        if room.host == request.user:
            is_host = True
        else:
            try:
                participant = CallParticipant.objects.get(room=room, session_id=session_id)
                is_host = participant.is_host
            except CallParticipant.DoesNotExist:
                pass
        
        if not is_host:
            return Response({
                'success': False,
                'error': 'Only the host can perform this action'
            }, status=status.HTTP_403_FORBIDDEN)
        
        result = {'success': True}
        
        # Handle different actions
        if action == 'lock_room':
            room.is_locked = True
            room.save()
            result['message'] = 'Room locked successfully'
            result['is_locked'] = True
            
        elif action == 'unlock_room':
            room.is_locked = False
            room.save()
            result['message'] = 'Room unlocked successfully'
            result['is_locked'] = False
            
        elif action == 'mute_all_audio':
            room.mute_all_audio = True
            room.allow_participants_to_unmute = False
            room.save()
            # Update all participants
            CallParticipant.objects.filter(
                room=room,
                left_at__isnull=True,
                is_host=False
            ).update(is_audio_muted=True)
            result['message'] = 'All participants muted'
            result['mute_all_audio'] = True
            
        elif action == 'unmute_all_audio':
            room.mute_all_audio = False
            room.allow_participants_to_unmute = True
            room.save()
            # Update all participants
            CallParticipant.objects.filter(
                room=room,
                left_at__isnull=True,
                is_host=False
            ).update(is_audio_muted=False)
            result['message'] = 'All participants unmuted'
            result['mute_all_audio'] = False
            
        elif action == 'mute_all_video':
            room.mute_all_video = True
            room.save()
            # Update all participants
            CallParticipant.objects.filter(
                room=room,
                left_at__isnull=True,
                is_host=False
            ).update(is_video_off=True)
            result['message'] = 'All videos turned off'
            result['mute_all_video'] = True
            
        elif action == 'unmute_all_video':
            room.mute_all_video = False
            room.save()
            # Update all participants
            CallParticipant.objects.filter(
                room=room,
                left_at__isnull=True,
                is_host=False
            ).update(is_video_off=False)
            result['message'] = 'All videos turned on'
            result['mute_all_video'] = False
            
        elif action == 'allow_screen_share':
            room.allow_participants_to_share = True
            room.save()
            result['message'] = 'Screen sharing enabled'
            result['allow_screen_share'] = True
            
        elif action == 'disallow_screen_share':
            room.allow_participants_to_share = False
            room.save()
            result['message'] = 'Screen sharing disabled'
            result['allow_screen_share'] = False
            
        elif action == 'enable_waiting_room':
            room.waiting_room_enabled = True
            room.save()
            result['message'] = 'Waiting room enabled'
            result['waiting_room_enabled'] = True
            
        elif action == 'disable_waiting_room':
            room.waiting_room_enabled = False
            room.save()
            result['message'] = 'Waiting room disabled'
            result['waiting_room_enabled'] = False
            
        elif action == 'remove_participant':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                if not target_participant.is_host:
                    target_participant.leave()
                    result['message'] = f'Participant removed'
                else:
                    result['success'] = False
                    result['error'] = 'Cannot remove the host'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'mute_participant':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                target_participant.is_audio_muted = True
                target_participant.save()
                result['message'] = f'{target_participant.display_name} muted'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'unmute_participant':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                target_participant.is_audio_muted = False
                target_participant.save()
                result['message'] = f'{target_participant.display_name} unmuted'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'turn_off_participant_video':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                target_participant.is_video_off = True
                target_participant.save()
                result['message'] = f'{target_participant.display_name}\'s video turned off'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'turn_on_participant_video':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                target_participant.is_video_off = False
                target_participant.save()
                result['message'] = f'{target_participant.display_name}\'s video turned on'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'transfer_host':
            target_session_id = request.data.get('target_session_id', '')
            try:
                target_participant = CallParticipant.objects.get(
                    room=room,
                    session_id=target_session_id
                )
                if target_participant.user:
                    # Update old host
                    old_host = CallParticipant.objects.filter(room=room, is_host=True).first()
                    if old_host:
                        old_host.is_host = False
                        old_host.save()
                    
                    # Update new host
                    target_participant.is_host = True
                    target_participant.save()
                    
                    # Update room host
                    room.host = target_participant.user
                    room.save()
                    
                    result['message'] = f'Host transferred to {target_participant.display_name}'
                else:
                    result['success'] = False
                    result['error'] = 'Can only transfer host to authenticated user'
            except CallParticipant.DoesNotExist:
                result['success'] = False
                result['error'] = 'Participant not found'
                
        elif action == 'get_controls' or action == 'get_status':
            result['room_settings'] = {
                'is_locked': room.is_locked,
                'mute_all_audio': room.mute_all_audio,
                'mute_all_video': room.mute_all_video,
                'allow_participants_to_unmute': room.allow_participants_to_unmute,
                'allow_participants_to_share': room.allow_participants_to_share,
                'waiting_room_enabled': room.waiting_room_enabled
            }
            
        else:
            result['success'] = False
            result['error'] = 'Invalid action'
        
        return Response(result)
        
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])
def send_invite_api(request):
    """API endpoint for sending meeting invitations via email."""
    room_code = request.data.get('room_code', '').upper()
    email = request.data.get('email', '').strip()
    room_link = request.data.get('room_link', '')
    host_name = request.data.get('host_name', 'The host')
    
    if not room_code or not email:
        return Response({
            'success': False,
            'error': 'Room code and email are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        room = VideoCallRoom.objects.get(room_code=room_code)
    except VideoCallRoom.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Room not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
    if not room_link:
        room_link = f"{request.build_absolute_uri('/').rstrip('/')}/videocalls/room/{room_code}/prejoin/"
    
    subject = f"{host_name} invited you to join a video call"
    message = f"""
Hello,

{host_name} has invited you to join a video call.

Room Name: {room.name}
Room Code: {room_code}

Click the link below to join:
{room_link}

---
This is an automated message from the Video Calling system.
    """.strip()
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        
        return Response({
            'success': True,
            'message': 'Invitation sent successfully'
        })
    except Exception as e:
        return Response({
            'success': False,
            'error': f'Failed to send email: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_video_call_config(request):
    """API endpoint to get video call configuration."""
    return Response({
        'success': True,
        'config': {
            'iceServers': settings.VIDEO_CALL_ICE_SERVERS,
            'pollInterval': settings.VIDEO_CALL_POLL_INTERVAL,
            'maxParticipants': settings.VIDEO_CALL_MAX_PARTICIPANTS,
            'recordingEnabled': settings.VIDEO_CALL_RECORDING_ENABLED,
            'chatEnabled': settings.VIDEO_CALL_CHAT_ENABLED,
            'maxDuration': settings.VIDEO_CALL_MAX_DURATION_SECONDS,
            'mediasoupEnabled': settings.MEDIASOUP_ENABLED,
            'mediasoupWsUrl': settings.MEDIASOUP_WS_URL,
            'largeRoomThreshold': settings.MEDIASOUP_LARGE_ROOM_THRESHOLD,
        }
    })


# =============================================================================
# Helper Functions
# =============================================================================

def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


# =============================================================================
# Local Recordings View (stored on user's device)
# =============================================================================

@login_required
@permission_required('videocalls.view_callrecording', raise_exception=True)
def local_recordings_view(request):
    """View for managing local recordings stored on user's device."""
    context = {
        'page_title': 'My Recordings',
        'storage_info': {
            'max_storage_mb': 500,
            'description': 'Recordings are stored directly on your device using browser storage.'
        }
    }
    return render(request, 'videocalls/local_recordings.html', context)


# =============================================================================
# Scheduled Meeting Views
# =============================================================================

@login_required
@permission_required('videocalls.add_scheduledmeeting', raise_exception=True)
def schedule_meeting_view(request):
    """View for scheduling a new meeting."""
    if request.method == 'POST':
        meeting_title = request.POST.get('meeting_title', '').strip()
        description = request.POST.get('description', '').strip()
        scheduled_date = request.POST.get('scheduled_date', '')
        scheduled_time = request.POST.get('scheduled_time', '')
        duration = int(request.POST.get('duration', 60))
        max_participants = int(request.POST.get('max_participants', 10))
        use_password = request.POST.get('use_password') == 'on'
        password = request.POST.get('password', '')
        invite_emails = request.POST.get('invite_emails', '')
        
        if not meeting_title or not scheduled_date or not scheduled_time:
            messages.error(request, 'Please fill in all required fields.')
            return redirect('videocalls:schedule_meeting')
        
        try:
            from datetime import datetime
            scheduled_start = datetime.strptime(f"{scheduled_date} {scheduled_time}", "%Y-%m-%d %H:%M")
            scheduled_start = timezone.make_aware(scheduled_start)
        except ValueError:
            messages.error(request, 'Invalid date or time format.')
            return redirect('videocalls:schedule_meeting')
        
        meeting = ScheduledMeeting.objects.create(
            host=request.user,
            meeting_title=meeting_title,
            description=description,
            scheduled_start=scheduled_start,
            scheduled_duration=duration,
            max_participants=max_participants,
            password=password if use_password and password else None,
        )
        
        if invite_emails:
            emails = [e.strip() for e in invite_emails.split(',') if e.strip()]
            for email in emails:
                MeetingInvitation.objects.create(
                    meeting=meeting,
                    email=email,
                )
        
        messages.success(request, 'Meeting scheduled successfully!')
        return redirect('videocalls:meeting_detail', meeting_slug=meeting.join_link_slug)
    
    return render(request, 'videocalls/schedule_meeting.html', {
        'page_title': 'Schedule Meeting'
    })


@login_required
@permission_required('videocalls.view_scheduledmeeting', raise_exception=True)
def my_scheduled_meetings_view(request):
    """View for listing user's scheduled meetings."""
    upcoming_meetings = ScheduledMeeting.objects.filter(
        host=request.user,
        status__in=['scheduled', 'started']
    ).order_by('scheduled_start')
    
    past_meetings = ScheduledMeeting.objects.filter(
        host=request.user,
        status='ended'
    ).order_by('-scheduled_start')[:20]
    
    return render(request, 'videocalls/my_scheduled_meetings.html', {
        'upcoming_meetings': upcoming_meetings,
        'past_meetings': past_meetings,
        'page_title': 'My Scheduled Meetings'
    })


@login_required
@permission_required('videocalls.view_scheduledmeeting', raise_exception=True)
def meeting_detail_view(request, meeting_slug):
    """View for meeting details with shareable link."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        messages.error(request, 'Meeting not found.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if meeting.host != request.user:
        messages.error(request, 'You do not have permission to view this meeting.')
        return redirect('videocalls:my_scheduled_meetings')
    
    meeting_link = meeting.get_full_meeting_link(request)
    invitations = meeting.invitations.all()
    
    return render(request, 'videocalls/meeting_detail.html', {
        'meeting': meeting,
        'meeting_link': meeting_link,
        'invitations': invitations,
        'page_title': meeting.meeting_title
    })


@login_required
@permission_required('videocalls.change_scheduledmeeting', raise_exception=True)
def edit_meeting_view(request, meeting_slug):
    """View for editing a scheduled meeting."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        messages.error(request, 'Meeting not found.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if meeting.host != request.user:
        messages.error(request, 'You do not have permission to edit this meeting.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if request.method == 'POST':
        meeting.meeting_title = request.POST.get('meeting_title', meeting.meeting_title)
        meeting.description = request.POST.get('description', meeting.description)
        meeting.scheduled_duration = int(request.POST.get('duration', meeting.scheduled_duration))
        meeting.max_participants = int(request.POST.get('max_participants', meeting.max_participants))
        
        use_password = request.POST.get('use_password') == 'on'
        password = request.POST.get('password', '')
        meeting.password = password if use_password and password else None
        meeting.save()
        
        messages.success(request, 'Meeting updated successfully!')
        return redirect('videocalls:meeting_detail', meeting_slug=meeting.join_link_slug)
    
    return render(request, 'videocalls/edit_meeting.html', {
        'meeting': meeting,
        'page_title': f'Edit: {meeting.meeting_title}'
    })


@login_required
@permission_required('videocalls.delete_scheduledmeeting', raise_exception=True)
def delete_meeting_view(request, meeting_slug):
    """View for deleting/cancelling a scheduled meeting."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        messages.error(request, 'Meeting not found.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if meeting.host != request.user:
        messages.error(request, 'You do not have permission to delete this meeting.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if request.method == 'POST':
        meeting.cancel_meeting()
        messages.success(request, 'Meeting cancelled.')
        return redirect('videocalls:my_scheduled_meetings')
    
    return render(request, 'videocalls/delete_meeting.html', {
        'meeting': meeting,
        'page_title': 'Cancel Meeting'
    })


@login_required
def send_meeting_invite_view(request, meeting_slug):
    """API endpoint for sending meeting invitations via email."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Meeting not found'}, status=404)
    
    if meeting.host != request.user:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    email = request.POST.get('email', '').strip()
    if not email:
        return JsonResponse({'success': False, 'error': 'Email is required'})
    
    invite_link = meeting.get_full_meeting_link(request)
    
    subject = f"Invitation: {meeting.meeting_title}"
    message = f"""
Hello,

You have been invited to join a video meeting.

Meeting: {meeting.meeting_title}
Date & Time: {meeting.scheduled_start.strftime('%B %d, %Y at %I:%M %p')}
Duration: {meeting.scheduled_duration} minutes

Join the meeting using this link:
{invite_link}

{"This meeting is password protected. You will be asked for a password when joining." if meeting.has_password() else ""}

Best regards,
{request.user.get_full_name() or request.user.email}
"""
    
    try:
        send_mail(
            subject=subject,
            message=message.strip(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        
        MeetingInvitation.objects.create(
            meeting=meeting,
            email=email,
        )
        
        return JsonResponse({'success': True, 'message': 'Invitation sent successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def join_meeting_view(request, meeting_slug):
    """View for joining a meeting via shareable link - shows registration form."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        messages.error(request, 'This meeting link is invalid or has expired.')
        return redirect('videocalls:lobby')
    
    if meeting.status == 'cancelled':
        messages.error(request, 'This meeting has been cancelled.')
        return redirect('videocalls:lobby')
    
    if meeting.status == 'ended':
        messages.error(request, 'This meeting has ended.')
        return redirect('videocalls:lobby')
    
    if request.method == 'POST':
        display_name = request.POST.get('display_name', '').strip()
        password = request.POST.get('password', '')
        
        if not display_name:
            messages.error(request, 'Please enter your name.')
            return render(request, 'videocalls/meeting_join.html', {
                'meeting': meeting,
                'page_title': f"Join: {meeting.meeting_title}",
                'error': 'Please enter your name.'
            })
        
        if meeting.has_password() and meeting.password != password:
            messages.error(request, 'Incorrect meeting password.')
            return render(request, 'videocalls/meeting_join.html', {
                'meeting': meeting,
                'page_title': f"Join: {meeting.meeting_title}",
                'error': 'Incorrect password.'
            })
        
        session_id = generate_session_id()
        
        if not meeting.room:
            meeting.start_meeting()
        
        if meeting.room.participant_count >= meeting.max_participants:
            messages.error(request, 'This meeting is full.')
            return render(request, 'videocalls/meeting_join.html', {
                'meeting': meeting,
                'page_title': f"Join: {meeting.meeting_title}",
                'error': 'Meeting is full.'
            })
        
        participant, created = CallParticipant.objects.get_or_create(
            room=meeting.room,
            session_id=session_id,
            defaults={
                'user': request.user if request.user.is_authenticated else None,
                'participant_name': display_name,
                'is_host': meeting.host == request.user if request.user.is_authenticated else False
            }
        )
        
        if not created:
            participant.left_at = None
            participant.save()
        
        return redirect('videocalls:room', room_code=meeting.room.room_code)
    
    return render(request, 'videocalls/meeting_join.html', {
        'meeting': meeting,
        'page_title': f"Join: {meeting.meeting_title}"
    })


@login_required
def start_meeting_view(request, meeting_slug):
    """View for starting a scheduled meeting (host only)."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
    except ScheduledMeeting.DoesNotExist:
        messages.error(request, 'Meeting not found.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if meeting.host != request.user:
        messages.error(request, 'Only the host can start this meeting.')
        return redirect('videocalls:my_scheduled_meetings')
    
    if meeting.status == 'started' and meeting.room:
        return redirect('videocalls:room', room_code=meeting.room.room_code)
    
    room = meeting.start_meeting()
    if room:
        messages.success(request, 'Meeting started!')
        return redirect('videocalls:room', room_code=room.room_code)
    else:
        messages.error(request, 'Could not start meeting.')
        return redirect('videocalls:meeting_detail', meeting_slug=meeting.join_link_slug)


@api_view(['GET'])
@permission_classes([AllowAny])
def meeting_status_api(request, meeting_slug):
    """API endpoint for checking meeting status."""
    try:
        meeting = ScheduledMeeting.objects.get(join_link_slug=meeting_slug)
        
        return Response({
            'success': True,
            'meeting': {
                'title': meeting.meeting_title,
                'status': meeting.status,
                'scheduled_start': meeting.scheduled_start.isoformat(),
                'can_join': meeting.can_join,
                'has_password': meeting.has_password(),
                'participant_count': meeting.room.participant_count if meeting.room else 0,
                'max_participants': meeting.max_participants,
            }
        })
    except ScheduledMeeting.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Meeting not found'
        }, status=404)

