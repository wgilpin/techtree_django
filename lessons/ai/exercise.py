"""Exercise generation node for lesson AI."""

import json
import logging
from typing import Any, Dict, List, Optional, cast

from .prompts import GENERATE_EXERCISE_PROMPT, LATEX_FORMATTING_INSTRUCTIONS
from .state import LessonState
from .utils import (
    _truncate_history,
    _format_history_for_prompt,
    _get_llm,
    _parse_llm_json_response,
    Exercise,
)

logger = logging.getLogger(__name__)

def generate_new_exercise(state: LessonState) -> LessonState:
    """Generates a new, unique exercise."""
    logger.info("Generating new exercise.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None
    updated_state["active_exercise"] = None
    updated_state["active_assessment"] = None
    updated_state["new_assistant_message"] = None

    user_id: Optional[str] = updated_state.get("user_id")

    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:1000]
    existing_exercise_descriptions_json = json.dumps([])
    syllabus_context = (
        f"Module: {updated_state.get('module_title', 'N/A')}, Lesson: {lesson_title}"
    )

    if not exposition_summary:
        error_message = "Sorry, I couldn't generate an exercise because the lesson content is missing."
        logger.warning(error_message)
        updated_state["error_message"] = error_message
        updated_state["new_assistant_message"] = error_message
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    new_exercise: Optional[Exercise] = None
    llm = _get_llm(temperature=0.5)
    if not llm:
        error_message = "LLM not configured for exercise generation."
        logger.error(error_message)
        updated_state["new_assistant_message"] = (
            "Sorry, I cannot generate an exercise right now (LLM unavailable)."
        )
        updated_state["error_message"] = error_message
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    try:
        prompt_input = {
            "topic": topic,
            "lesson_title": lesson_title,
            "user_level": user_level,
            "exposition_summary": exposition_summary,
            "syllabus_context": syllabus_context,
            "existing_exercise_descriptions_json": existing_exercise_descriptions_json,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = GENERATE_EXERCISE_PROMPT.format(**prompt_input)
        response = llm.invoke(formatted_prompt)  # type: ignore

        try:
            parsed_result = _parse_llm_json_response(response)
            if (
                parsed_result
                and isinstance(parsed_result, dict)
                and "type" in parsed_result
            ):
                new_exercise = cast(Exercise, parsed_result)
                logger.info("LLM exercise response parsed: %s", new_exercise.get("id"))
            else:
                logger.warning(
                    "LLM exercise JSON invalid format or missing keys: %s",
                    response.content if hasattr(response, "content") else response,
                )
                updated_state["error_message"] = (
                    "Received invalid exercise format from LLM."
                )
        except Exception as parse_err:
            logger.error(
                f"Failed during exercise JSON processing: {parse_err}", exc_info=True
            )
            updated_state["error_message"] = (
                f"Failed to process exercise JSON: {parse_err}"
            )

    except Exception as e:
        error_msg = f"LLM call/parsing failed during exercise generation: {e}"
        logger.error(error_msg, exc_info=True)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, I encountered an error while generating the exercise."
        )
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    if new_exercise:
        updated_state["active_exercise"] = cast(Dict[str, Any], new_exercise)
        updated_state["current_interaction_mode"] = "awaiting_answer"

        confirmation_content = (
            f"Okay, here's an exercise for you:\n\n**Type:** {new_exercise.get('type')}\n**Instructions:** "
            f"{new_exercise.get('instructions')}"
        )
        if new_exercise.get("question"):
            confirmation_content += f"\n**Question:** {new_exercise.get('question')}"
        options = new_exercise.get("options")
        if options:
            confirmation_content += "\n**Options:**\n"
            for option in options:
                confirmation_content += f"- ({option.get('id')}) {option.get('text')}\n"
        items = new_exercise.get("items")
        if items:
            confirmation_content += "\n**Items to order:**\n"
            for item in items:
                confirmation_content += f"- {item}\n"

        updated_state["new_assistant_message"] = confirmation_content
        logger.info(f"Generated exercise {new_exercise.get('id')} for user {user_id}.")
    else:
        error_message = "Sorry, I couldn't generate an exercise at this time."
        updated_state["new_assistant_message"] = error_message
        if not updated_state.get("error_message"):
            updated_state["error_message"] = (
                "Exercise generation failed (invalid format or LLM error)."
            )
        updated_state["current_interaction_mode"] = "chatting"

    return updated_state