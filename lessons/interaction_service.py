"""
Service layer for handling user interactions within lessons.

This module contains the logic for processing chat messages, exercise submissions,
and assessment answers using the LessonInteractionGraph.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

# pylint: disable=no-member
from django.utils import timezone as django_timezone

# Import necessary models
from core.models import ConversationHistory, UserProgress

from .ai.lesson_graph import LessonInteractionGraph  # Import the graph
from .ai.state import LessonState  # Import the state definition

# For type checking ForeignKey relations to Django's User model
if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def handle_chat_message(
    user: "User",
    progress: UserProgress,
    user_message_content: str,
    submission_type: str = "chat",  # Add submission_type, default to 'chat'
) -> Optional[Dict[str, Any]]:  # Return a dict with message and potentially state info
    """
    Handles a user's message or submission during a lesson using the AI graph.

    1. Saves the user message to history.
    2. Loads the current lesson state from UserProgress.
    3. Prepares the input state for the LessonInteractionGraph.
    4. Invokes the LessonInteractionGraph to process the message/submission.
    5. Extracts the assistant's response and updated state from the graph output.
    6. Saves the assistant's response to history (if any).
    7. Updates and saves the UserProgress with the new state.
    8. Returns the assistant message and the final updated state.
    """
    logger.info(
        "Handling chat message for UserProgress %s, user %s", progress.pk, user.username
    )

    # 1. Save user message
    try:
        # Determine message type based on submission type
        if submission_type == "answer":
            user_message_type = "exercise_response"
        elif submission_type == "assessment":
            user_message_type = "assessment_response"
        else:
            user_message_type = "chat"

        ConversationHistory.objects.create(
            progress=progress,
            role="user",
            message_type=user_message_type,
            content=user_message_content,
        )
    except Exception as e:
        logger.error(
            "Failed to save user message for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Decide if we should proceed without saving the user message? For now, let's return error.
        return None  # Or return {'error': 'Failed to save user message.'} ?

    # 2. Load current state
    if not isinstance(progress.lesson_state_json, dict):
        logger.error(
            "Invalid or missing lesson state for UserProgress %s. Cannot process message.",
            progress.pk,
        )
        # Attempt to re-initialize? For now, return error.
        # Consider calling get_lesson_state_and_history again or raising specific error
        return None  # Or return {'error': 'Lesson state missing or invalid.'} ?
    current_state: LessonState = cast(LessonState, progress.lesson_state_json.copy())

    # 3. Prepare input state for the graph
    # Fetch recent conversation history to provide context to the graph
    try:
        history_limit = 10  # Limit context window
        recent_history_qs = ConversationHistory.objects.filter(
            progress=progress
        ).order_by("-timestamp")[:history_limit]
        # Format for the graph state (role/content dicts, newest first)
        formatted_history = [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(recent_history_qs)  # Reverse to get oldest first
        ]
        # Nodes expect history under 'history_context' key
        current_state["history_context"] = formatted_history
        # Remove the other key if it exists from previous state loads
        current_state.pop("conversation_history", None)
    except Exception as e:
        logger.error(
            "Failed to fetch conversation history for graph state (UserProgress %s): %s",
            progress.pk,
            e,
            exc_info=True,
        )
        current_state["conversation_history"] = []  # Proceed without history context

    # Set the message being processed and the interaction mode
    current_state["last_user_message"] = user_message_content
    # Map submission_type to interaction_mode expected by the graph
    if submission_type in ["answer", "assessment"]:
        current_state["current_interaction_mode"] = "submit_answer"
    else:  # Default to chatting
        current_state["current_interaction_mode"] = "chatting"
    # Clear previous outputs before calling graph
    current_state.pop("new_assistant_message", None)
    current_state.pop("evaluation_feedback", None)
    current_state.pop("error_message", None)

    # 4. Invoke the LessonInteractionGraph
    graph = LessonInteractionGraph()
    output_state: Optional[LessonState] = None
    assistant_response_content: Optional[str] = None

    try:
        logger.info(
            "Invoking LessonInteractionGraph for UserProgress %s (mode: %s)",
            progress.pk,
            current_state["current_interaction_mode"],
        )
        # Access the compiled graph via the 'graph' attribute of the instance
        output_state_dict = graph.graph.invoke(
            current_state, {"recursion_limit": 10}
        )
        if not output_state_dict:
            raise ValueError("Graph invocation returned None.")

        logger.info("Graph invocation successful for UserProgress %s.", progress.pk)

        # Extract potential messages and errors *from the dictionary* before casting
        graph_error_message = output_state_dict.get("error_message")
        new_msg = output_state_dict.get("new_assistant_message")
        assistant_response_content = output_state_dict.get("new_assistant_message")
        feedback_msg = output_state_dict.get("evaluation_feedback")

        # assistant_response_content is already defined outside the try block
        if isinstance(new_msg, str):
            assistant_response_content = new_msg
        elif isinstance(feedback_msg, str):
            assistant_response_content = feedback_msg

        # Log any errors reported by the graph itself
        if graph_error_message:  # Check the extracted error message
            logger.error(
                "Graph reported an error for UserProgress %s: %s",
                progress.pk,
                graph_error_message,
            )
            # Decide if this error should halt processing or just be logged

        # Now cast the dictionary to the TypedDict for type checking elsewhere if needed
        output_state = cast(LessonState, output_state_dict)

    except Exception as e:
        logger.error(
            "Error invoking LessonInteractionGraph for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Save a minimal state update indicating the error?
        current_state["error_message"] = f"Graph invocation failed: {e}"
        progress.lesson_state_json = current_state  # Save state with error
        progress.save(update_fields=["lesson_state_json", "updated_at"])
        # Return a dictionary indicating the error
        return {
            "error": f"Graph invocation failed: {e}",
            "updated_state": current_state,
        }

    # 5. Save assistant response (if any)
    if assistant_response_content:
        try:
            # Determine message type for assistant response
            assistant_message_type = "chat"  # Default
            if output_state and output_state.get("evaluation_feedback"):
                assistant_message_type = (
                    "exercise_feedback"
                    if output_state.get("active_exercise")
                    else "assessment_feedback"
                )
            elif output_state and output_state.get("active_exercise"):
                assistant_message_type = "exercise_prompt"
            elif output_state and output_state.get("active_assessment"):
                assistant_message_type = "assessment_prompt"

            ConversationHistory.objects.create(
                progress=progress,
                role="assistant",
                message_type=assistant_message_type,
                # Ensure we save the string content
                content=str(assistant_response_content),
            )
        except Exception as e:
            logger.error(
                "Failed to save assistant message for UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )
            # Continue processing state update even if saving message fails?

    # 6. Update and save UserProgress with the full new state from the graph
    try:
        if output_state and not assistant_response_content:
            assistant_response_content = output_state.get("new_assistant_message")
        # Remove temporary context keys before saving if they exist
        # Need to operate on the dictionary before saving
        final_state_dict = dict(output_state) if output_state else {}
        final_state_dict.pop("history_context", None)
        final_state_dict.pop(
            "last_user_message", None
        )  # Don't persist the trigger message in state
        # Also remove transient message/feedback keys before saving
        final_state_dict.pop("new_assistant_message", None)
        final_state_dict.pop("evaluation_feedback", None)

        # Ensure we are saving a plain dict, not a mock or cast object
        progress.lesson_state_json = final_state_dict
        progress.updated_at = django_timezone.now()  # Ensure updated_at is set
        # Check if lesson is completed based on state (e.g., a 'completed' flag set by graph)
        # if output_state.get('lesson_completed'): # Hypothetical flag
        #     progress.status = 'completed'
        #     progress.completed_at = django_timezone.now()
        #     progress.save(update_fields=["lesson_state_json", "status", "completed_at", "updated_at"])
        # else:
        progress.save(update_fields=["lesson_state_json", "updated_at"])

        logger.info("Successfully updated state for UserProgress %s.", progress.pk)

    except Exception as e:
        logger.error(
            "Failed to save updated state for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Return the message content, but state saving failed
        return (
            {"assistant_message": assistant_response_content}
            if assistant_response_content
            else None
        )
    if not assistant_response_content:
        assistant_response_content = "Sorry, I couldn't generate a response."

    # Return the assistant message and the final state upon successful completion
    return {
        "assistant_message": assistant_response_content or "Sorry, I couldn't generate a response.",
        "updated_state": final_state_dict,  # Return the final state dict
    }