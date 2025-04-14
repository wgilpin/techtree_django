"""
Synchronous lesson interaction processor for background task execution.
"""

# pylint: disable=no-member

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from core.models import ConversationHistory, UserProgress, LessonContent
from lessons.ai.lesson_graph import LessonInteractionGraph

logger = logging.getLogger(__name__)

def process_lesson_interaction(task):
    """
    Process a lesson interaction task synchronously.

    Args:
        task: The AITask instance containing input data for the lesson interaction

    Returns:
        dict: The interaction result data including the assistant's response
    """
    # Extract parameters from input_data
    progress_id = task.input_data.get("progress_id")
    user_message_content = task.input_data.get("user_message")
    submission_type = task.input_data.get("submission_type", "chat")

    if not progress_id or not user_message_content:
        raise ValueError(
            "Missing required parameters: progress_id and user_message are required"
        )

    logger.info(
        f"Processing lesson interaction for progress_id '{progress_id}', "
        f"submission_type '{submission_type}'"
    )

    # Get the progress
    progress = UserProgress.objects.get(pk=progress_id)

    # Save user message (moved from consumer to ensure atomicity with assistant response)
    if submission_type == "answer":
        user_message_type = "exercise_response"
    elif submission_type == "assessment":
        user_message_type = "assessment_response"
    else:
        user_message_type = "chat"

    user_msg_obj = ConversationHistory.objects.create(
        progress=progress,
        role="user",
        message_type=user_message_type,
        content=user_message_content,
    )

    # Load current state
    current_state = progress.lesson_state_json.copy()

    # Fetch recent conversation history
    history_limit = 10
    recent_history_qs = ConversationHistory.objects.filter(progress=progress).order_by(
        "-timestamp"
    )[:history_limit]

    # Format for the graph state
    formatted_history = [
        {"role": msg.role, "content": msg.content}
        for msg in reversed(list(recent_history_qs))
    ]

    # Prepare state for graph
    current_state["history_context"] = formatted_history
    current_state.pop("conversation_history", None)
    current_state["last_user_message"] = user_message_content
    current_state["user_message"] = user_message_content
    # Add lesson topic to state for AI context
    try:
        current_state["lesson_topic"] = progress.lesson.module.syllabus.topic
        current_state["lesson_summary"] = progress.lesson.summary or "No summary available."
        # Fetch lesson content for exposition
        lesson_content = LessonContent.objects.filter(lesson=progress.lesson).first()
        if lesson_content and isinstance(lesson_content.content, dict):
            current_state["lesson_exposition"] = lesson_content.content.get("exposition", "")
        else:
            current_state["lesson_exposition"] = ""
            logger.warning(f"Could not retrieve exposition for lesson {progress.lesson.pk}.")

    except AttributeError:
        logger.warning(f"Could not retrieve topic/summary/exposition for progress {progress.pk}. Setting defaults.")
        current_state["lesson_topic"] = "Unknown Topic"
        current_state["lesson_summary"] = "No summary available."
        current_state["lesson_exposition"] = ""
    # Map submission_type to interaction_mode
    if submission_type in ["answer", "assessment"]:
        current_state["current_interaction_mode"] = "submit_answer"
    else:
        current_state["current_interaction_mode"] = "chatting"

    # Clear previous outputs
    current_state.pop("new_assistant_message", None)
    current_state.pop("evaluation_feedback", None)
    current_state.pop("error_message", None)

    # Invoke the graph synchronously
    try:
        graph = LessonInteractionGraph()
        output_state_dict = graph.graph.invoke(current_state, {"recursion_limit": 10})

        # Extract response
        assistant_response_content = output_state_dict.get("new_assistant_message")
        feedback_msg = output_state_dict.get("evaluation_feedback")

        if isinstance(feedback_msg, str):
            assistant_response_content = feedback_msg

        # Save assistant response
        if assistant_response_content:
            # Determine message type
            assistant_message_type = "chat"
            if output_state_dict.get("evaluation_feedback"):
                assistant_message_type = (
                    "exercise_feedback"
                    if output_state_dict.get("active_exercise")
                    else "assessment_feedback"
                )
            elif output_state_dict.get("active_exercise"):
                assistant_message_type = "exercise_prompt"
            elif output_state_dict.get("active_assessment"):
                assistant_message_type = "assessment_prompt"

            ConversationHistory.objects.create(
                progress=progress,
                role="assistant",
                message_type=assistant_message_type,
                content=str(assistant_response_content),
            )

        # Update progress with new state
        final_state_dict = dict(output_state_dict)
        final_state_dict.pop("history_context", None)
        final_state_dict.pop("last_user_message", None)
        final_state_dict.pop("new_assistant_message", None)
        final_state_dict.pop("evaluation_feedback", None)

        progress.lesson_state_json = final_state_dict
        progress.save(update_fields=["lesson_state_json", "updated_at"])

        # --- WebSocket/Channels update ---
        # Get lesson_id for group name
        lesson_id = str(progress.lesson.pk)
        group_name = f"lesson_chat_{lesson_id}"

        # Do NOT render templates in the background task.
        # Only send a notification to the group; the consumer will render templates.

        # Get IDs for the messages just saved
        user_message_id = str(user_msg_obj.message_id) if user_msg_obj else None
        assistant_message = (
            ConversationHistory.objects.filter(progress=progress, role="assistant")
            .order_by("-timestamp")
            .first()
        )
        assistant_message_id = str(assistant_message.message_id) if assistant_message else None

        # Send to Channels group with message IDs and state, not HTML
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "lesson_interaction_result",
                "user_message_id": user_message_id, # Add user message ID
                "assistant_message_id": assistant_message_id,
                "final_state_dict": final_state_dict,
            },
        )

        return {
            "assistant_message": assistant_response_content
            or "Sorry, I couldn't generate a response.",
            "updated_state": final_state_dict,
        }
    except Exception as e:
        logger.error(f"Error in lesson interaction: {str(e)}", exc_info=True)
        # Save error message to conversation history
        ConversationHistory.objects.create(
            progress=progress,
            role="assistant",
            message_type="error",
            content=f"Sorry, an error occurred: {str(e)}",
        )
        raise
