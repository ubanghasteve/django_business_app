"""
WebSocket consumer for real-time messaging.
When a message is sent (via REST), the view pushes to the conversation's channel group;
all connected clients in that conversation receive the message instantly.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import Conversation
from .services import user_can_access_conversation


@database_sync_to_async
def check_can_access(conv_id, user):
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    conv = Conversation.objects.filter(pk=conv_id).first()
    if not conv:
        return False
    return user_can_access_conversation(conv, user, None)


class ChatConsumer(AsyncWebsocketConsumer):
    """One consumer instance per WebSocket; joins the conversation's group to receive new messages."""

    async def connect(self):
        self.user = self.scope.get('user')
        self.conversation_id = self.scope['url_route']['kwargs'].get('conversation_id')
        if not self.conversation_id or not self.user or not getattr(self.user, 'is_authenticated', True):
            await self.close()
            return
        can = await check_can_access(int(self.conversation_id), self.user)
        if not can:
            await self.close()
            return
        self.room_group_name = f"conv_{self.conversation_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def message_created(self, event):
        """Called when the view sends a new message to this conversation's group."""
        payload = event.get('message')
        if payload is not None:
            await self.send(text_data=json.dumps({'type': 'message', 'message': payload}))
