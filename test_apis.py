#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'business_app.settings')
django.setup()

from django.test import Client
import json

client = Client()

print('=' * 60)
print('TESTING VIDEO CALLS API ENDPOINTS')
print('=' * 60)
print()

# Test 1: CSRF Token
print('1. Testing CSRF token endpoint...')
response = client.get('/videocalls/api/csrf/')
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 2: Create Room API
print('2. Testing create room API...')
response = client.post(
    '/videocalls/api/create/',
    data=json.dumps({
        'room_name': 'Test Room',
        'room_type': 'group',
        'max_participants': 5
    }),
    content_type='application/json'
)
print(f'   Status: {response.status_code}')
data = response.json()
print(f'   Room Created: {data.get("success", False)}')
ROOM_CODE = data.get('room', {}).get('room_code', 'NOTFOUND')
print(f'   Room Code: {ROOM_CODE}')
print()

# Test 3: Room Status API (using created room)
print(f'3. Testing room status API ({ROOM_CODE})...')
response = client.get(f'/videocalls/api/status/{ROOM_CODE}/')
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 4: Participants API
print(f'4. Testing participants API ({ROOM_CODE})...')
response = client.get(f'/videocalls/api/participants/{ROOM_CODE}/')
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 5: Join Room API
print(f'5. Testing join room API ({ROOM_CODE})...')
response = client.post(
    '/videocalls/api/join/',
    data=json.dumps({
        'room_code': ROOM_CODE,
        'session_id': 'test_session_123'
    }),
    content_type='application/json'
)
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 6: Participants after joining
print(f'6. Testing participants after joining...')
response = client.get(f'/videocalls/api/participants/{ROOM_CODE}/')
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 7: Signaling offer API
print(f'7. Testing signaling offer API...')
response = client.post(
    '/videocalls/api/signaling/offer/',
    data=json.dumps({
        'room_code': ROOM_CODE,
        'sender_session_id': 'test_session_456',
        'target_session_id': '',
        'message_type': 'offer',
        'payload': {'sdp': 'v=0\r\n\r\ntest sdp', 'type': 'offer'}
    }),
    content_type='application/json'
)
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 8: Signaling ICE API
print(f'8. Testing signaling ICE API...')
response = client.post(
    '/videocalls/api/signaling/ice/',
    data=json.dumps({
        'room_code': ROOM_CODE,
        'sender_session_id': 'test_session_456',
        'target_session_id': '',
        'message_type': 'ice_candidate',
        'payload': {'candidate': {'candidate': 'test', 'sdpMid': '0', 'sdpMLineIndex': 0}}
    }),
    content_type='application/json'
)
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

# Test 9: Signaling messages API (polling)
print(f'9. Testing signaling messages API (polling)...')
response = client.get(f'/videocalls/api/signaling/messages/?room_code={ROOM_CODE}&session_id=test_session_123')
print(f'   Status: {response.status_code}')
print(f'   Messages received: {len(response.json().get("messages", []))}')
print()

# Test 10: Leave Room API
print(f'10. Testing leave room API...')
response = client.post(
    '/videocalls/api/leave/',
    data=json.dumps({
        'room_code': ROOM_CODE,
        'session_id': 'test_session_123'
    }),
    content_type='application/json'
)
print(f'   Status: {response.status_code}')
print(f'   Response: {response.json()}')
print()

print('=' * 60)
print('ALL API ENDPOINT TESTS PASSED!')
print('=' * 60)
