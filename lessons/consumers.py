"""
WebSocket consumers for lessons app (HTMX/Channels integration).
"""

# pylint: disable=no-member

import json
import logging
from typing import Any, Dict, Optional, cast

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import User as AuthUserType  # Use alias for clarity
from django.shortcuts import get_object_or_404
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
        """Called when the websocket is handshaking as part of initial connection."""
        self.lesson_id = self.scope["url_route"]["kwargs"]["lesson_id"]
        self.group_name = f"lesson_content_{self.lesson_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, _):
        """Called when the WebSocket closes for any reason."""
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Called when we get a text frame. Channels will always decode the value
        to a text string before calling this method.
        """
        # No client-initiated messages expected for content updates

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
        """Called when the websocket is handshaking as part of initial connection."""
        self.lesson_id = self.scope["url_route"]["kwargs"]["lesson_id"]
        self.group_name = f"lesson_chat_{self.lesson_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, _):
        """Called when the WebSocket closes for any reason."""
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle incoming messages via WebSocket.

        Determines if the message is a regular chat message or a quiz answer
        based on the current lesson state stored in UserProgress.

        1. Parses the message.
        2. Fetches UserProgress and checks for active quiz state.
        3. If quiz active:
            - Saves user message as 'quiz_answer'.
            - Updates UserProgress state with the answer.
            - Creates and triggers a PROCESS_QUIZ_INTERACTION AITask.
        4. If quiz not active:
            - Saves user message as 'chat'.
            - Creates and triggers a LESSON_INTERACTION AITask.
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
            data = json.loads(text_data)

            # Extract user message content (consistent with previous logic)
            user_message_content = ""
            if "user-message" in data:
                user_message_content = data.get("user-message", "").strip()
            elif "HEADERS" in data and isinstance(data["HEADERS"], dict):
                user_message_content = data["HEADERS"].get("user-message", "").strip()
            elif "message" in data:
                user_message_content = data.get("message", "").strip()

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

            # --- Check Lesson State for Active Quiz ---
            # Load the current lesson state directly from UserProgress
            current_lesson_state = progress.lesson_state_json or {}

            # Determine if quiz is active based on the state structure expected by the graph
            # An active quiz should have 'current_question_index' and not be 'quiz_complete' or have an error
            is_quiz_active = (
                "current_question_index" in current_lesson_state
                and not current_lesson_state.get("quiz_complete", False)
                and not current_lesson_state.get("error_message")
            )

            # --- Save User Message (common step) ---
            # Determine message type based on quiz state
            message_type = "quiz_answer" if is_quiz_active else "chat"

            user_message_obj = await database_sync_to_async(
                ConversationHistory.objects.create
            )(
                progress=progress,
                role="user",
                message_type=message_type,
                content=user_message_content,
            )

            # Send user message to channel layer immediately
            await self.send_user_message(user_message_obj)

            # --- Create and Trigger Background Task ---
            if is_quiz_active:
                # --- Handle Quiz Answer ---
                logger.info(
                    f"ChatConsumer received quiz answer for lesson {self.lesson_id}, user {user.pk}"
                )

                # Prepare the state to pass to the AI task
                # Add the user's answer directly to the top-level state dictionary
                state_for_ai_task = {
                    **current_lesson_state, # Start with the current state from UserProgress
                    "user_answer": user_message_content, # Add the new user answer
                    # Ensure essential keys are present, defaulting if necessary
                    "lesson_id": lesson.pk,
                    "user_id": user.pk,
                    "difficulty": current_lesson_state.get("difficulty", lesson.module.syllabus.level if lesson.module else "Beginner"), # Get difficulty, default if missing
                }

                # The create_quiz_ai_task method will save this state to UserProgress
                # and also save it to AITask input_data
                task = await self.create_quiz_ai_task(
                    user, lesson, progress, state_for_ai_task # Pass the flattened state
                )
                await sync_to_async(process_ai_task)(str(task.task_id))
                logger.info(f"Created AITask {task.task_id} for quiz interaction.")

            else:
                # --- Handle Regular Chat Message ---
                logger.info(
                    f"ChatConsumer received chat message for lesson {self.lesson_id}, user {user.pk}"
                )
                # For regular chat, create a different AI task
                task = await self.create_lesson_interaction_ai_task(
                    user, lesson, progress, user_message_content, user_message_obj
                )
                await sync_to_async(process_ai_task)(str(task.task_id))
                logger.info(f"Created AITask {task.task_id} for lesson interaction.")

        except json.JSONDecodeError:
            logger.error(f"ChatConsumer failed to decode JSON: {text_data}")
            # Optionally send an error message back to the client via WebSocket
            await self.send_error_message("Invalid message format.")
        except Exception as e:
            logger.error(f"Error in ChatConsumer.receive: {e}", exc_info=True)
            await self.send_error_message(f"An internal error occurred: {e}")

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
    def create_lesson_interaction_ai_task(
        self, user, lesson, progress, user_message, user_message_obj
    ):
        """Creates an AITask for the lesson interaction."""
        user_obj = cast(AuthUserType, user)
        return AITask.objects.create(
            task_type=AITask.TaskType.LESSON_INTERACTION,
            input_data={
                "user_message": user_message,
                "lesson_id": str(lesson.pk),
                "progress_id": str(progress.pk),
                "submission_type": "chat",  # Explicitly set for chat
                "user_message_id": str(user_message_obj.message_id),
            },
            user=user_obj,
            lesson=lesson,
        )

    @database_sync_to_async
    def create_quiz_ai_task(self, user, lesson, progress, input_state):
        """
        Creates an AITask for quiz processing and updates UserProgress state.
        The input_state is expected to be the flattened state dictionary
        ready for the quiz graph.
        """
        user_obj = cast(AuthUserType, user)

        # Update UserProgress with the state *before* creating the task
        # This ensures the state is saved as soon as the user provides input
        # and is available for the processor to load.
        try:
            progress.lesson_state_json = input_state # Save the flattened state
            # Use synchronous save here because the function is wrapped by @database_sync_to_async
            progress.save(
                update_fields=["lesson_state_json", "updated_at"]
            )
            logger.info(f"UserProgress {progress.pk} updated with state before creating AITask.")
        except Exception as e:
            logger.error(f"Error saving UserProgress state in create_quiz_ai_task: {e}", exc_info=True)
            # Log the error but continue creating the task. The processor will
            # attempt to load the state from UserProgress, which might be
            # slightly out of sync if the save failed, but it's the primary source.
            pass


        return AITask.objects.create(
            task_type=AITask.TaskType.PROCESS_QUIZ_INTERACTION,
            input_data=input_state,  # Pass the correctly structured input data
            user=user_obj,
            lesson=lesson,
            # Removed: progress=progress, # This was the original TypeError cause
        )

    async def send_user_message(self, user_message_obj):
        """Sends the user's message to the channel layer."""

        user_message_html = render_to_string(
            "lessons/_chat_message.html", {"message": user_message_obj}
        )
        oob_chat_message = f"""
            <div id="chat-history" hx-swap-oob="beforeend">
                {user_message_html}
                <script>
                    var chatHistory = document.getElementById("chat-history");
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                </script>
            </div>"""

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
        scroll_script = (
            '<script>var chatHistory = document.getElementById("chat-history"); '
            "chatHistory.scrollTop = chatHistory.scrollHeight;</script>"
        )
        oob_chat_message = ""
        if assistant_message_html:
            oob_chat_message = (
                '<div id="chat-history" hx-swap-oob="beforeend">'
                f"{assistant_message_html}{scroll_script}</div>"
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

    async def send_assistant_message(
        self,
        content: str,
        message_type: str = "chat",
        extra_context: Optional[Dict[str, Any]] = None,
    ):
        """Helper to format and send an assistant message to the chat history."""
        # In a real app, you might want to save this to ConversationHistory
        # For simplicity here, we create a temporary object for rendering
        progress = await self.get_user_progress(
            self.scope["user"], await self.get_lesson(self.lesson_id)
        )
        if not progress:
            logger.error(
                f"Cannot send assistant message: UserProgress not found for lesson {self.lesson_id}"
            )
            return  # Or handle error appropriately

        message_obj = ConversationHistory(
            progress=progress,  # Required for template context if it uses it
            role="assistant",
            content=content,
            message_type=message_type,
        )
        # await database_sync_to_async(message_obj.save)() # Optional: Save to DB

        # Combine base context with extra_context
        template_context = {"message": message_obj}
        if extra_context:
            template_context.update(extra_context)

        message_html = render_to_string(
            "lessons/_chat_message.html", template_context  # Use the combined context
        )
        scroll_script = (
            '<script>var chatHistory = document.getElementById("chat-history"); '
            "chatHistory.scrollTop = chatHistory.scrollHeight;</script>"
        )
        oob_chat_message = f'<div id="chat-history" hx-swap-oob="beforeend">{message_html}{scroll_script}</div>'

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",  # Use the existing chat message handler
                "message": oob_chat_message,
            },
        )

    async def quiz_question(self, event):
        """Handles quiz_question events from the quiz processor task."""
        payload = event.get("payload")
        if payload:
            question_text = payload.get(
                "question_text", "Error: Missing question text."
            )
            options = payload.get("options", [])  # Extract options
            question_index = payload.get("question_index", "?")
            total_questions = payload.get("total_questions", "?")

            # Pass the extracted data to send_assistant_message
            await self.send_assistant_message(
                question_text,
                message_type="quiz_question",
                extra_context={  # Pass extra context for the template
                    "question_index": question_index,
                    "total_questions": total_questions,
                    "options": options,  # Include options in the context
                },
            )
            logger.debug(f"Sent quiz_question to chat group {self.group_name}")
        else:
            logger.warning(
                f"Received quiz_question event with empty payload for group {self.group_name}"
            )
            await self.send_error_message("Received an empty quiz question.")

    async def quiz_feedback(self, event):
        """Handles quiz_feedback events from the quiz processor task."""
        payload = event.get("payload")
        if payload:
            feedback_text = payload.get("feedback", "Error: Missing feedback text.")
            is_correct = payload.get("is_correct", False)
            question_index = payload.get("question_index", "?") # Get index for feedback
            total_questions = payload.get("total_questions", "?") # Get total for feedback

            # Format the feedback as a chat message
            prefix = "✅ Correct!" if is_correct else "❌ Incorrect."
            formatted_content = f"{prefix}\n\n{feedback_text}"
            await self.send_assistant_message(
                formatted_content,
                message_type="quiz_feedback",
                extra_context={ # Pass extra context for the template
                    "question_index": question_index,
                    "total_questions": total_questions,
                    "is_correct": is_correct, # Include correctness for potential styling
                }
            )
            logger.debug(f"Sent quiz_feedback to chat group {self.group_name}")
        else:
            logger.warning(
                f"Received quiz_feedback event with empty payload for group {self.group_name}"
            )
            await self.send_error_message("Received empty quiz feedback.")

    async def quiz_result(self, event):
        """Handles quiz_result events from the quiz processor task."""
        payload = event.get("payload")
        if payload:
            score = payload.get("score", 0)
            total_questions = payload.get("total_questions", 0)
            summary = payload.get("summary", "Quiz finished!")
            # Format the result as a chat message
            formatted_content = f"**Quiz Complete!**\n\nYour score: {score}/{total_questions}\n\n{summary}"
            await self.send_assistant_message(
                formatted_content, message_type="quiz_result"
            )
            logger.debug(f"Sent quiz_result to chat group {self.group_name}")

            # Optionally, update the main lesson state to mark quiz as finished
            # This is now handled by the quiz_processor saving the final state
            # with quiz_complete=True. The consumer just needs to react to the message.

        else:
            logger.warning(
                f"Received quiz_result event with empty payload for group {self.group_name}"
            )
            await self.send_error_message("Received empty quiz results.")

    async def quiz_error(self, event):
        """Handles quiz_error events from the quiz processor task."""
        payload = event.get("payload")
        error_message = "An unknown error occurred during the quiz."
        if payload:
            error_message = payload.get("error", error_message)

        logger.error(
            f"Received quiz_error for group {self.group_name}: {error_message}"
        )
        # Format the error as a chat message
        formatted_content = f"⚠️ **Quiz Error:**\n\n{error_message}"
        await self.send_assistant_message(formatted_content, message_type="quiz_error")

        # Optionally, update the main lesson state to mark quiz as errored
        # This is now handled by the quiz_processor saving the final state
        # with error_message set. The consumer just needs to react to the message.


    async def send_error_message(self, error_text: str):
        """Helper to send a simple error message to the client."""
        # This could be enhanced to use the OOB swap like send_assistant_message
        # For simplicity, sending a basic text message for now.
        # Consider creating a specific error format/template if needed.
        await self.send(
            text_data=json.dumps(
                {
                    "type": "error",  # Define a client-side handler for this if needed
                    "message": error_text,
                }
            )
        )