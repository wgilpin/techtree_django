"""Chat response node for lesson AI."""

from typing import Any, Dict, List, Optional, cast
import logging

from .prompts import CHAT_RESPONSE_PROMPT, LATEX_FORMATTING_INSTRUCTIONS
from .state import LessonState
from .utils import _truncate_history, _format_history_for_prompt, _get_llm

logger = logging.getLogger(__name__)

def generate_chat_response(state: LessonState) -> LessonState:
    """Generates a chat response."""
    logger.info("Generating chat response.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None
    updated_state["new_assistant_message"] = None

    history_maybe_none = updated_state.get("history_context")
    history: List[Dict[str, str]] = (
        history_maybe_none if isinstance(history_maybe_none, list) else []
    )
    user_id: Optional[str] = updated_state.get("user_id")

    if not history or history[-1].get("role") != "user":
        logger.warning(
            f"Cannot generate chat response: No user message for user {user_id}."
        )
        updated_state["new_assistant_message"] = (
            "It seems I missed your last message. Could you please repeat it?"
        )
        return updated_state

    llm = _get_llm(temperature=0.7)
    if not llm:
        error_msg = "LLM not configured for chat response."
        logger.error(error_msg)
        updated_state["new_assistant_message"] = (
            "Sorry, I cannot respond right now (LLM unavailable)."
        )
        updated_state["error_message"] = error_msg
        return updated_state

    last_user_message = history[-1].get("content", "")
    formatted_history = _format_history_for_prompt(_truncate_history(history[:-1]))

    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:1000]
    active_task_context = "None"

    ai_response_content: Optional[str] = None
    try:
        syllabus = updated_state.get("syllabus")
        syllabus_str = "No syllabus information available."
        if syllabus and isinstance(syllabus, dict):
            modules = syllabus.get("modules", [])
            syllabus_str = f"Course Topic: {syllabus.get('topic', 'Unknown')}\n"
            syllabus_str += f"Level: {syllabus.get('level', 'Unknown')}\n\n"
            syllabus_str += "Course Outline:\n"
            for i, module in enumerate(modules):
                module_title = module.get("title", f"Module {i+1}")
                syllabus_str += f"Module {i+1}: {module_title}\n"
                lessons = module.get("lessons", [])
                for j, lesson in enumerate(lessons):
                    lesson_title_in_syllabus = lesson.get("title", f"Lesson {j+1}")
                    syllabus_str += f"  Lesson {j+1}: {lesson_title_in_syllabus}\n"

        prompt_input = {
            "user_message": last_user_message,
            "history_json": formatted_history,
            "topic": topic,
            "lesson_title": lesson_title,
            "level": user_level,
            "exposition": exposition_summary,
            "syllabus": syllabus_str,
            "active_task_context": active_task_context,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = CHAT_RESPONSE_PROMPT.format(**prompt_input)
        response = llm.invoke(formatted_prompt)  # type: ignore
        content: Any = response.content  # type: ignore
        if isinstance(content, str):
            ai_response_content = content.strip()
        elif isinstance(content, list):
            ai_response_content = str(content).strip()
        else:
            ai_response_content = str(content).strip()
    except Exception as e:
        error_msg = f"LLM call failed during chat response generation: {e}"
        logger.error(error_msg, exc_info=True)
        ai_response_content = (
            "Sorry, I encountered an error while generating a response."
        )
        updated_state["error_message"] = error_msg

    if ai_response_content is None:
        ai_response_content = "Sorry, I couldn't generate a response."

    logger.info(f"Generated chat response content for user {user_id}.")
    updated_state["new_assistant_message"] = ai_response_content
    updated_state["current_interaction_mode"] = "chatting"

    return updated_state