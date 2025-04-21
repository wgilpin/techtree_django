"""
WebSocket routing for lessons app (HTMX/Channels integration).
"""

from django.urls import re_path

# Placeholder consumers; replace with actual implementations
from lessons import consumers

websocket_urlpatterns = [
    re_path(r"^ws/lesson/(?P<lesson_id>\d+)/content/$", consumers.ContentConsumer.as_asgi()),
    re_path(r"^ws/lesson/(?P<lesson_id>\d+)/chat/$", consumers.ChatConsumer.as_asgi()),
]
