"""
WebSocket consumers for lessons app (HTMX/Channels integration).
"""

# pylint: disable=no-member

import json
import logging
from typing import cast

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import User as AuthUserType  # Use alias for clarity
from django.template.loader import render_to_string

from core.models import ConversationHistory, Lesson, UserProgress
from taskqueue.models import AITask
from taskqueue.tasks import process_ai_task  # Import the background task function

logger = logging.getLogger(__name__)


class ContentConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for lesson content websocket updates.
    Joins a group based on lesson_id and relays content updates to the client.
    """

    def __init__(self):
        super().__init__()
        self.lesson_id = None
        self.group_name = None

    async def connect(self):
        self.lesson_id = self.scope["url_route"]["kwargs"]["lesson_id"]
        self.group_name = f"lesson_content_{self.lesson_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, _):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # No client-initiated messages expected for content updates
        pass

    async def content_update(self, event):
        """
        Handler for content update events sent via the channel layer.
        Expects event to have 'html' (HTML partial to send to client).
        """
        html = event.get("html", "")
        await self.send(text_data=html)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Placeholder consumer for lesson chat websocket updates.
    """

    def __init__(self):
        super().__init__()
        self.lesson_id = None
        self.group_name = None

    async def connect(self):
        self.lesson_id = self.scope["url_route"]["kwargs"]["lesson_id"]
        self.group_name = f"lesson_chat_{self.lesson_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, _):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle incoming chat messages via WebSocket.

        1. Parses the message (sent as JSON by HTMX form).
        2. Creates a ConversationHistory entry for the user message.
        3. Creates an AITask to process the interaction.
        4. Triggers the background task.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning("ChatConsumer received message from unauthenticated user.")
            await self.close()
            return

        if not text_data:
            logger.warning("ChatConsumer received empty message.")
            return

        try:
            # Log the full message for debugging
            logger.debug(f"ChatConsumer received raw message: {text_data}")

            data = json.loads(text_data)
            # Log the parsed data structure
            logger.debug(f"ChatConsumer parsed data: {data}")

            # Extract user message - try different possible locations
            user_message_content = ""

            # Direct access (most likely for HTMX websocket form)
            if "user-message" in data:
                user_message_content = data.get("user-message", "").strip()
            # Check in HEADERS (alternative HTMX format)
            elif "HEADERS" in data and isinstance(data["HEADERS"], dict):
                user_message_content = data["HEADERS"].get("user-message", "").strip()
            # Try other common locations
            elif "message" in data:
                user_message_content = data.get("message", "").strip()

            logger.debug(f"Extracted user message: '{user_message_content}'")

            if not user_message_content:
                logger.warning(
                    "ChatConsumer received message with no user-message content."
                )
                logger.warning(f"Message keys: {list(data.keys())}")
                return

            # Fetch related objects asynchronously
            lesson = await self.get_lesson(self.lesson_id)
            if not lesson:
                logger.error(f"Lesson {self.lesson_id} not found for ChatConsumer.")
                await self.close()
                return

            progress = await self.get_user_progress(user, lesson)
            if not progress:
                logger.error(
                    f"UserProgress not found for user {user.pk} and lesson {lesson.pk}."
                )
                await self.close()
                return

            # Send user message to channel layer immediately
            await self.send_user_message(user, lesson, progress, user_message_content)
            # Create and trigger background task
            task = await self.create_ai_task(
                user, lesson, progress, user_message_content
            )
            await sync_to_async(process_ai_task)(str(task.task_id))  # Wrap sync call for async context

            logger.info(f"Created AITask {task.task_id} for lesson interaction.")

        except json.JSONDecodeError:
            logger.error(f"ChatConsumer failed to decode JSON: {text_data}")
        except Exception as e:
            logger.error(f"Error in ChatConsumer.receive: {e}", exc_info=True)

    @database_sync_to_async
    def get_lesson(self, lesson_id):
        """Fetches the Lesson object."""
        try:
            return Lesson.objects.get(pk=lesson_id)
        except Lesson.DoesNotExist:
            return None

    @database_sync_to_async
    def get_user_progress(self, user, lesson):
        """Fetches the UserProgress object."""
        try:
            # Assuming syllabus is linked via lesson -> module -> syllabus
            return UserProgress.objects.get(
                user=user, lesson=lesson, syllabus=lesson.module.syllabus
            )
        except UserProgress.DoesNotExist:
            return None
        except (
            AttributeError
        ):  # Handle case where lesson.module or lesson.module.syllabus is None
            logger.error(f"Could not determine syllabus for lesson {lesson.pk}")
            return None

    @database_sync_to_async
    def save_user_message(self, progress, content):
        """Saves the user's message to ConversationHistory."""
        ConversationHistory.objects.create(
            progress=progress, role="user", message_type="chat", content=content
        )

    @database_sync_to_async
    def create_ai_task(self, user, lesson, progress, user_message):
        """Creates an AITask for the lesson interaction."""
        user_obj = cast(AuthUserType, user)
        return AITask.objects.create(
            task_type=AITask.TaskType.LESSON_INTERACTION,
            input_data={
                "user_message": user_message,
                "lesson_id": str(lesson.pk),
                "progress_id": str(progress.pk),
                "submission_type": "chat",  # Explicitly set for chat
            },
            user=user_obj,
            lesson=lesson,
        )

    async def send_user_message(self, user, lesson, progress, user_message_content):
        """Sends the user's message to the channel layer."""
        from django.template.loader import render_to_string

        user_message = await database_sync_to_async(ConversationHistory.objects.create)(
            progress=progress, role="user", message_type="chat", content=user_message_content
        )
        user_message_html = render_to_string("lessons/_chat_message.html", {"message": user_message})
        oob_chat_message = f'<div id="chat-history" hx-swap-oob="beforeend">{user_message_html}<script>var chatHistory = document.getElementById("chat-history"); chatHistory.scrollTop = chatHistory.scrollHeight;</script></div>'

        # Send OOB update to the group
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",
                "message": oob_chat_message,
            },
        )

    async def lesson_interaction_result(self, event):
        """
        Handler for lesson interaction result events sent via the channel layer.
        Now expects event to have 'assistant_message_id' and 'final_state_dict'.
        Renders templates in the main Django process.
        """
        assistant_message_id = event.get("assistant_message_id")
        final_state_dict = event.get("final_state_dict", {})

        assistant_message = None
        if assistant_message_id is not None:
            try:
                assistant_message = await database_sync_to_async(
                    ConversationHistory.objects.get
                )(message_id=assistant_message_id)
            except ConversationHistory.DoesNotExist:
                logger.warning(
                    f"Assistant message {assistant_message_id} not found in DB for OOB swap."
                )
                assistant_message = None

        assistant_message_html = ""
        if assistant_message:
            assistant_message_html = render_to_string(
                "lessons/_chat_message.html", {"message": assistant_message}
            )

        context = {
            "active_exercise": final_state_dict.get("active_exercise"),
            "active_assessment": final_state_dict.get("active_assessment"),
            "task_prompt": final_state_dict.get("task_prompt"),
        }
        active_task_html = render_to_string("lessons/_active_task_area.html", context)

        # Construct Out-of-Band (OOB) swaps for HTMX
        # Combine user and assistant messages for chat history update
        combined_chat_html = f"{assistant_message_html}"
        scroll_script = (
            '<script>var chatHistory = document.getElementById("chat-history"); '
            "chatHistory.scrollTop = chatHistory.scrollHeight;</script>"
        )
        oob_chat_message = ""
        if combined_chat_html:
            oob_chat_message = (
                '<div id="chat-history" hx-swap-oob="beforeend">'
                f"{combined_chat_html}{scroll_script}</div>"
            )
        oob_active_task = f'<div id="active-task-area" hx-swap-oob="innerHTML">{active_task_html}</div>'

        # Send both OOB updates in a single message
        await self.send(text_data=f"{oob_chat_message}{oob_active_task}")

    async def chat_message(self, event):
        """
        Handler for chat message events.
        """
        message = event["message"]
        await self.send(text_data=message)
