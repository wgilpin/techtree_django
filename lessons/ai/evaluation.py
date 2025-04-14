"""Answer evaluation node for lesson AI."""

import logging
from typing import Any, Dict, List, Optional, cast

from .prompts import EVALUATE_ANSWER_PROMPT, LATEX_FORMATTING_INSTRUCTIONS
from .state import LessonState
from .utils import (
    _get_llm,
    _parse_llm_json_response,
    EvaluationResult,
)

logger = logging.getLogger(__name__)

def _prepare_evaluation_context(
    active_exercise: Optional[Dict[str, Any]],
    active_assessment: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Prepares the context dictionary needed for the evaluation prompt."""
    context = {
        "task_type": "Unknown",
        "task_details": "N/A",
        "correct_answer_details": "N/A",
    }
    task = active_exercise or active_assessment
    if task:
        context["task_type"] = "Exercise" if active_exercise else "Assessment Question"
        instructions = task.get("instructions")
        question = (
            task.get("question") if active_exercise else task.get("question_text")
        )
        details = f"Type: {task.get('type')}\nInstructions/Question: {instructions or question}"
        options = task.get("options")
        if options and isinstance(options, list):
            options_str = "\n".join(
                [
                    f"- ({opt.get('id')}) {opt.get('text')}"
                    for opt in options
                    if isinstance(opt, dict)
                ]
            )
            details += f"\nOptions:\n{options_str}"
        items = task.get("items")
        if (
            task.get("type") == "ordering" and items and isinstance(items, list)
        ):
            details += f"\nItems to Order: {json.dumps(items)}"
        context["task_details"] = details

        correct_answer = task.get("correct_answer")
        correct_answer_id = task.get("correct_answer_id")
        correct_details = "N/A"
        if correct_answer:
            correct_details = f"Correct Answer/Solution: {correct_answer}"
        elif correct_answer_id:
            correct_details = f"Correct Answer ID: {correct_answer_id}"

        expected_format = task.get("expected_solution_format")
        if expected_format:
            if correct_details == "N/A":
                correct_details = ""
            else:
                correct_details += "\n"
            correct_details += f"Expected Format: {expected_format}"
        context["correct_answer_details"] = correct_details

    return context

def evaluate_answer(state: LessonState) -> LessonState:
    """Evaluates the user's submitted answer."""
    logger.info("Evaluating user answer.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None
    updated_state["evaluation_feedback"] = None
    updated_state["score_update"] = None
    updated_state["new_assistant_message"] = None

    user_answer: Optional[str] = cast(
        Optional[str],
        updated_state.get("potential_answer") or updated_state.get("user_message"),
    )

    active_exercise = updated_state.get("active_exercise")
    active_assessment = updated_state.get("active_assessment")
    active_task = active_exercise or active_assessment

    if not active_task:
        error_msg = "No active exercise or assessment found to evaluate."
        logger.warning(error_msg)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, there wasn't an active question for me to evaluate."
        )
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["active_exercise"] = None
        updated_state["active_assessment"] = None
        return updated_state

    if not user_answer:
        error_msg = "No answer found in state to evaluate."
        logger.warning(error_msg)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, I couldn't find your answer to evaluate."
        )
        updated_state["current_interaction_mode"] = "awaiting_answer"
        return updated_state

    eval_context = _prepare_evaluation_context(
        cast(Optional[Dict[str, Any]], active_exercise),
        cast(Optional[Dict[str, Any]], active_assessment),
    )
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")

    evaluation_result: Optional[EvaluationResult] = None
    llm = _get_llm(temperature=0.1)
    if not llm:
        error_msg = "LLM not configured for evaluation."
        logger.error(error_msg)
        updated_state["new_assistant_message"] = (
            "Sorry, I cannot evaluate your answer right now (LLM unavailable)."
        )
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["active_exercise"] = None
        updated_state["active_assessment"] = None
        return updated_state

    try:
        prompt_input = {
            "topic": topic,
            "lesson_title": lesson_title,
            "level": user_level,
            "task_type": eval_context["task_type"],
            "task_details": eval_context["task_details"],
            "correct_answer_details": eval_context["correct_answer_details"],
            "user_answer": user_answer,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = EVALUATE_ANSWER_PROMPT.format(**prompt_input)
        response = llm.invoke(formatted_prompt)  # type: ignore

        try:
            parsed_result = _parse_llm_json_response(response)
            if (
                parsed_result
                and "score" in parsed_result
                and "feedback" in parsed_result
            ):
                evaluation_result = cast(EvaluationResult, parsed_result)
                logger.info(
                    "LLM evaluation response parsed: Score %s",
                    evaluation_result.get("score"),
                )
            else:
                logger.warning(
                    "LLM evaluation JSON invalid format: %s",
                    response.content if hasattr(response, "content") else response,
                )
                updated_state["error_message"] = (
                    "Received invalid evaluation format from LLM."
                )
        except Exception as parse_err:
            logger.error(
                f"Failed during evaluation JSON processing: {parse_err}", exc_info=True
            )
            updated_state["error_message"] = (
                f"Failed to process evaluation JSON: {parse_err}"
            )

    except Exception as e:
        error_msg = f"LLM call/parsing failed during evaluation: {e}"
        logger.error(error_msg, exc_info=True)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, I encountered an error evaluating your answer."
        )
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["active_exercise"] = None
        updated_state["active_assessment"] = None
        return updated_state

    if evaluation_result:
        updated_state["evaluation_feedback"] = evaluation_result.get(
            "feedback", "Evaluation complete."
        )
        updated_state["score_update"] = evaluation_result.get("score")
        updated_state["new_assistant_message"] = evaluation_result.get(
            "feedback", "Okay, let's continue."
        )
    else:
        updated_state["new_assistant_message"] = (
            "Sorry, I had trouble processing the evaluation."
        )
        if not updated_state.get("error_message"):
            updated_state["error_message"] = (
                "Evaluation failed (invalid format or LLM error)."
            )

    updated_state["active_exercise"] = None
    updated_state["active_assessment"] = None
    updated_state["current_interaction_mode"] = "chatting"
    updated_state["potential_answer"] = None

    return updated_state