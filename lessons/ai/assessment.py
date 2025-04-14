"""Assessment generation node for lesson AI."""

import json
import logging
from typing import Any, Dict, Optional, cast

from .prompts import GENERATE_ASSESSMENT_PROMPT, LATEX_FORMATTING_INSTRUCTIONS
from .state import LessonState
from .utils import _get_llm, _parse_llm_json_response, AssessmentQuestion

logger = logging.getLogger(__name__)

def generate_new_assessment(state: LessonState) -> LessonState:
    """Generates a new assessment question."""
    logger.info("Generating new assessment question.")
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
    existing_questions_json = json.dumps([])
    syllabus_context = (
        f"Module: {updated_state.get('module_title', 'N/A')}, Lesson: {lesson_title}"
    )

    if not exposition_summary:
        error_message = "Sorry, I couldn't generate an assessment because the lesson content is missing."
        logger.warning(error_message)
        updated_state["error_message"] = error_message
        updated_state["new_assistant_message"] = error_message
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    new_assessment_q: Optional[AssessmentQuestion] = None
    llm = _get_llm(temperature=0.4)
    if not llm:
        error_message = "LLM not configured for assessment generation."
        logger.error(error_message)
        updated_state["new_assistant_message"] = (
            "Sorry, I cannot generate an assessment right now (LLM unavailable)."
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
            "existing_question_descriptions_json": existing_questions_json,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = GENERATE_ASSESSMENT_PROMPT.format(**prompt_input)
        response = llm.invoke(formatted_prompt)  # type: ignore

        try:
            parsed_result = _parse_llm_json_response(response)
            if (
                parsed_result
                and "type" in parsed_result
                and "question_text" in parsed_result
            ):
                new_assessment_q = cast(AssessmentQuestion, parsed_result)
                logger.info(
                    "LLM assessment response parsed: %s", new_assessment_q.get("id")
                )
            else:
                logger.warning(
                    "LLM assessment JSON invalid format: %s",
                    response.content if hasattr(response, "content") else response,
                )
                updated_state["error_message"] = (
                    "Received invalid assessment format from LLM."
                )
        except Exception as parse_err:
            logger.error(
                f"Failed during assessment JSON processing: {parse_err}", exc_info=True
            )
            updated_state["error_message"] = (
                f"Failed to process assessment JSON: {parse_err}"
            )

    except Exception as e:
        error_msg = f"LLM call/parsing failed during assessment generation: {e}"
        logger.error(error_msg, exc_info=True)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, I encountered an error while generating assessment question."
        )
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    if new_assessment_q:
        updated_state["active_assessment"] = cast(Dict[str, Any], new_assessment_q)
        updated_state["current_interaction_mode"] = "awaiting_answer"

        confirmation_content = (
            f"Okay, here's a question for you:\n\n**Type:** {new_assessment_q.get('type')}\n"
            f"**Question:** {new_assessment_q.get('question_text')}"
        )
        options = new_assessment_q.get("options")
        if options:
            confirmation_content += "\n**Options:**\n"
            for option in options:
                confirmation_content += f"- ({option.get('id')}) {option.get('text')}\n"

        updated_state["new_assistant_message"] = confirmation_content
        logger.info(
            f"Generated assessment {new_assessment_q.get('id')} for user {user_id}."
        )
    else:
        error_message = (
            "Sorry, I couldn't generate an assessment question at this time."
        )
        updated_state["new_assistant_message"] = error_message
        if not updated_state.get("error_message"):
            updated_state["error_message"] = (
                "Assessment generation failed (invalid format or LLM error)."
            )
        updated_state["current_interaction_mode"] = "chatting"

    return updated_state