"""Classifies the user's intent and updates the state."""

import logging
from typing import Any, Dict, List, Optional, TypedDict, cast

from syllabus.services import SyllabusService

from .prompts import INTENT_CLASSIFICATION_PROMPT
from .state import LessonState

logger = logging.getLogger(__name__)


def _truncate_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Truncates conversation history."""
    return history[-10:]


def _format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    """Formats conversation history for prompts."""
    formatted = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        formatted.append(f"{role.capitalize()}: {content}")
    return "\\n".join(formatted)


class IntentClassificationResult(TypedDict, total=False):
    """Represents the result of intent classification with optional reasoning."""

    intent: str
    reasoning: Optional[str]


def _map_intent_to_mode(intent_str: str, state: LessonState) -> str:
    """Maps the classified intent string to an interaction mode."""
    intent_lower = intent_str.lower().strip()
    if "exercise" in intent_lower:
        return "request_exercise"
    if "assessment" in intent_lower or "quiz" in intent_lower:
        return "request_assessment"
    # Check for answer submission only if an active task exists
    if state.get("active_exercise") or state.get("active_assessment"):
        # If a task is active, any non-request intent might be an answer
        # More sophisticated check might be needed, but this is a start
        if (
            "answer" in intent_lower
            or "submit" in intent_lower
            or intent_lower
            not in ["request_exercise", "request_assessment", "chatting"]
        ):
            return "submit_answer"
    # Default to chatting
    return "chatting"


def classify_intent(state: LessonState) -> LessonState:
    """Classifies the user's intent and updates the state."""
    logger.info("Classifying user intent.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None  # Clear previous error
    updated_state["potential_answer"] = None  # Clear previous potential answer

    user_message = updated_state.get("last_user_message")
    user_id: Optional[str] = updated_state.get("user_id")
    # Ensure user_message is treated as Optional[str]
    user_message_str: Optional[str] = (
        cast(Optional[str], user_message) if user_message is not None else None
    )

    # Prioritize active tasks
    active_exercise = updated_state.get("active_exercise")
    active_assessment = updated_state.get("active_assessment")
    if active_exercise or active_assessment:
        logger.info("Active task found, classifying as submit_answer.")
        updated_state["current_interaction_mode"] = "submit_answer"
        # Assign user_message safely to potential_answer (Optional[str])
        updated_state["potential_answer"] = user_message_str
        return updated_state

    if not user_message_str:
        logger.warning(
            f"Cannot classify intent: No user message provided for user {user_id}."
        )
        updated_state["current_interaction_mode"] = "chatting"  # Default if no message
        updated_state["error_message"] = (
            "No user message found for intent classification."
        )
        return updated_state

    history_maybe_none = updated_state.get("history_context")
    history: List[Dict[str, str]] = (
        history_maybe_none if isinstance(history_maybe_none, list) else []
    )
    # Ensure history includes the current user message for context
    current_turn_history = history + [{"role": "user", "content": user_message_str}]
    formatted_history = _format_history_for_prompt(
        _truncate_history(current_turn_history[:-1])
    )  # Format history *before* last message

    # Context
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:500]
    # Fetch syllabus and add to state
    syllabus_id = updated_state.get("syllabus_id")
    syllabus: Optional[Dict[str, Any]] = None
    if syllabus_id:
        try:
            # Cast syllabus_id to str to match the expected type
            syllabus = SyllabusService().get_syllabus_by_id(str(syllabus_id))
            updated_state["syllabus"] = syllabus
        except Exception as e:
            logger.error(f"Failed to fetch syllabus: {e}", exc_info=True)
            updated_state["error_message"] = f"Failed to fetch syllabus: {e}"

    # Determine active task context dynamically
    active_exercise = updated_state.get("active_exercise")
    active_assessment = updated_state.get("active_assessment")
    active_task_context = "None"
    if active_exercise and isinstance(active_exercise, dict):
        active_task_context = active_exercise.get(
            "question", "Active exercise exists, but question text is missing."
        )
    elif active_assessment and isinstance(active_assessment, dict):
        active_task_context = active_assessment.get(
            "question", "Active assessment exists, but question text is missing."
        )

    # Call LLM
    intent_classification: Optional[IntentClassificationResult] = None
    from .utils import _get_llm
    llm = _get_llm(temperature=0.1)
    if not llm:
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["error_message"] = "LLM unavailable for intent classification."
        return updated_state

    try:
        prompt_input = {
            "user_input": user_message_str,  # Use the safe string version
            "history_json": formatted_history,
            "topic": topic,
            "lesson_title": lesson_title,
            "level": user_level,
            "exposition_summary": exposition_summary,
            "active_task_context": active_task_context,
        }
        formatted_prompt = INTENT_CLASSIFICATION_PROMPT.format(**prompt_input)
        response = llm.invoke(formatted_prompt)  # type: ignore

        try:
            # Use robust parser
            from .utils import _parse_llm_json_response
            parsed_result = _parse_llm_json_response(response)
            if isinstance(parsed_result, dict):
                if "intent" in parsed_result:  # pylint: disable=unsupported-membership-test
                    intent_classification = cast(IntentClassificationResult, parsed_result)
                logger.info("LLM intent response parsed: %s", intent_classification)
            else:
                logger.warning(
                    "LLM intent JSON missing 'intent' or invalid: %s",
                    response.content if hasattr(response, "content") else response,
                )
                updated_state["error_message"] = "LLM returned invalid intent format."
                intent_classification = None
        except Exception as parse_err:  # Catch any parsing error
            intent_classification = None
            logger.error(
                f"Failed during intent JSON processing: {parse_err}", exc_info=True
            )
            updated_state["error_message"] = (
                f"Failed to process intent JSON: {parse_err}"
            )

    except Exception as e:
        logger.error(
            f"LLM call/parsing failed during intent classification: {e}", exc_info=True
        )
        updated_state["error_message"] = f"LLM Error during intent classification: {e}"
        # Default to chatting on error
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    # Update State based on classification
    if isinstance(intent_classification, dict) and intent_classification.get("intent"):
        # pylint: disable=unsubscriptable-object
        classified_intent = intent_classification["intent"].lower()  # type: ignore[index]
        logger.info(f"Classified intent for user {user_id}: {classified_intent}")
        interaction_mode = _map_intent_to_mode(classified_intent, updated_state)
        updated_state["current_interaction_mode"] = interaction_mode
        updated_state["potential_answer"] = (
            user_message_str if interaction_mode == "submit_answer" else None
        )
    else:
        logger.warning(
            f"Intent classification failed or returned invalid data for user {user_id}. Defaulting to chatting."
        )
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["potential_answer"] = None
        if not updated_state.get("error_message"):
            updated_state["error_message"] = "Intent classification failed."

    # user_message is not part of the state to be returned
    return updated_state
