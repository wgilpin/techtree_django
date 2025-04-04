"""LangGraph nodes for the lesson interaction graph."""

import json
import logging
from typing import Any, Dict, List, Optional, cast, TypedDict
import re  # Import re for _parse_llm_json_response

from langchain_google_genai import ChatGoogleGenerativeAI
from django.conf import settings
from syllabus.ai.utils import call_with_retry  # Reuse retry logic
from .state import LessonState
from .prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    CHAT_RESPONSE_PROMPT,
    GENERATE_EXERCISE_PROMPT,
    EVALUATE_ANSWER_PROMPT,
    GENERATE_ASSESSMENT_PROMPT,
    LATEX_FORMATTING_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)

# --- Constants ---
MAX_HISTORY_TURNS = 10


# --- Helper Functions ---
def _truncate_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Truncates conversation history."""
    return history[-MAX_HISTORY_TURNS:]


def _format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    """Formats conversation history for prompts."""
    formatted = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        formatted.append(f"{role.capitalize()}: {content}")
    return "\n".join(formatted)


# --- Data Structures ---
# (Keep TypedDict definitions as they are)
class IntentClassificationResult(TypedDict, total=False):
    intent: str
    reasoning: Optional[str]


class ExerciseOption(TypedDict, total=False):
    id: str
    text: str


class ExerciseMisconception(TypedDict, total=False):
    pass  # Define more strictly if needed


class Exercise(TypedDict, total=False):
    id: str
    type: str
    question: Optional[str]
    instructions: str
    items: Optional[List[str]]
    options: Optional[List[ExerciseOption]]
    correct_answer_id: Optional[str]
    expected_solution_format: Optional[str]
    correct_answer: Optional[str]
    hints: Optional[List[str]]
    explanation: str
    misconception_corrections: Optional[ExerciseMisconception]


class EvaluationResult(TypedDict, total=False):
    score: float
    is_correct: bool
    feedback: str
    explanation: Optional[str]


class AssessmentOption(TypedDict, total=False):  # Similar to ExerciseOption
    id: str
    text: str


class AssessmentQuestion(TypedDict, total=False):
    id: str
    type: str  # e.g., "multiple_choice", "true_false", "short_answer"
    question_text: str
    options: Optional[List[AssessmentOption]]  # For multiple_choice / true_false
    correct_answer_id: Optional[str]  # For multiple_choice / true_false
    correct_answer: Optional[str]  # For short_answer
    explanation: str
    confidence_check: Optional[bool]  # Default false


logger = logging.getLogger(__name__)


# --- LLM Initialization Helper ---
def _get_llm(temperature: float = 0.2) -> Optional[ChatGoogleGenerativeAI]:
    """Initializes and returns the LangChain LLM model."""
    api_key = settings.GEMINI_API_KEY
    model_name = settings.FAST_MODEL
    if not api_key or not model_name:
        logger.error("LLM API key or model name not configured in settings.")
        return None
    try:
        # logger.info(f"Attempting to initialize LLM. Model: {model_name}, API Key Loaded: {bool(api_key)}") # Logging before init might still error
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            convert_system_message_to_human=True,
        )  # type: ignore[call-arg]
        logger.info(
            f"Successfully initialized LLM. Model: {model_name}"
        )  # Log after successful init
        return llm
    except Exception as e:
        logger.error(
            "Failed to initialize ChatGoogleGenerativeAI: %s", e, exc_info=True
        )
        return None


# --- JSON Parsing Helper ---
def _parse_llm_json_response(response: Any) -> Optional[Dict[str, Any]]:
    """Attempts to parse a JSON object from the LLM response text."""
    json_str = None
    try:
        # Handle both string responses and response objects with a 'content' or 'text' attribute
        if isinstance(response, str):
            response_text = response
        elif hasattr(response, "content") and isinstance(response.content, str):
            response_text = response.content
        elif hasattr(response, "text") and isinstance(response.text, str):
            response_text = response.text
        else:
            logger.error(f"Unexpected response type for JSON parsing: {type(response)}")
            return None

        # Try to find JSON within markdown code blocks first
        match = re.search(r"```(?:json)?\s*({.*?})\s*```", response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
            logger.info("Found JSON within markdown block.")
        else:
            # If no markdown block, assume the whole text is JSON (after stripping)
            json_str = response_text.strip()
            # Basic check if it looks like JSON before attempting parse
            if not (json_str.startswith("{") and json_str.endswith("}")):
                logger.warning("Response does not appear to be JSON or markdown block.")
                return None
            logger.info("Attempting to parse response text directly as JSON.")

        # Clean up common escape issues before parsing
        json_str = re.sub(r"\\n", "", json_str)  # Remove escaped newlines
        json_str = re.sub(
            r"\\(?![\"\\/bfnrtu])", "", json_str
        )  # Remove invalid escapes

        # Parse the extracted JSON string
        parsed_json = json.loads(json_str)
        if not isinstance(parsed_json, dict):
            logger.warning(f"Parsed JSON is not a dictionary: {type(parsed_json)}")
            return None

        logger.info("Successfully parsed JSON from LLM response.")
        return parsed_json

    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse JSON from response: {e}. String was: {json_str}..."
        )  # Removed slicing
        return None
    except Exception as e:
        logger.error(f"Unexpected error during JSON parsing: {e}", exc_info=True)
        return None


# --- Node Functions ---


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

    user_message = updated_state.get("user_message")
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
    active_task_context = "None"  # Already handled above

    # Call LLM
    intent_classification: Optional[IntentClassificationResult] = None
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
        logger.debug("Formatted intent prompt:\n%s", formatted_prompt)
        response = call_with_retry(llm.invoke, formatted_prompt)

        try:
            # Use robust parser
            parsed_result = _parse_llm_json_response(response)
            if parsed_result and "intent" in parsed_result:
                intent_classification = cast(IntentClassificationResult, parsed_result)
                logger.info("LLM intent response parsed: %s", intent_classification)
            else:
                logger.warning(
                    "LLM intent JSON missing 'intent' or invalid: %s",
                    response.content if hasattr(response, "content") else response,
                )
                updated_state["error_message"] = "LLM returned invalid intent format."
        except Exception as parse_err:  # Catch any parsing error
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
    if intent_classification and intent_classification.get("intent"):
        classified_intent = intent_classification["intent"].lower()
        logger.info(f"Classified intent for user {user_id}: {classified_intent}")
        interaction_mode = _map_intent_to_mode(
            classified_intent, updated_state
        )  # Pass state for context
        updated_state["current_interaction_mode"] = interaction_mode
        # Store potential answer only if mode is submit_answer
        updated_state["potential_answer"] = (
            user_message_str if interaction_mode == "submit_answer" else None
        )
    else:
        logger.warning(
            f"Intent classification failed or returned invalid data for user {user_id}. Defaulting to chatting."
        )
        updated_state["current_interaction_mode"] = "chatting"
        updated_state["potential_answer"] = None
        if not updated_state.get("error_message"):  # Avoid overwriting parsing error
            updated_state["error_message"] = "Intent classification failed."

    # user_message is not part of the state to be returned
    return updated_state


def generate_chat_response(state: LessonState) -> LessonState:
    """Generates a chat response."""
    logger.info("Generating chat response.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None  # Clear previous error
    updated_state["new_assistant_message"] = None  # Clear previous message

    history_maybe_none = updated_state.get("history_context")
    history: List[Dict[str, str]] = (
        history_maybe_none if isinstance(history_maybe_none, list) else []
    )
    user_id: Optional[str] = updated_state.get("user_id")

    # Check for user message *first*
    if not history or history[-1].get("role") != "user":
        logger.warning(
            f"Cannot generate chat response: No user message for user {user_id}."
        )
        # Set a default message if no user message
        updated_state["new_assistant_message"] = (
            "It seems I missed your last message. Could you please repeat it?"
        )
        # No error message needed here, just return the state with the assistant message
        return updated_state

    # Check for LLM *after* confirming user message exists
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

    # Context
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:1000]
    active_task_context = "None"  # TODO: Add active task context if needed for chat

    # Call LLM
    ai_response_content: Optional[str] = None
    try:
        prompt_input = {
            "user_message": last_user_message,
            "history_json": formatted_history,
            "topic": topic,
            "lesson_title": lesson_title,
            "level": user_level,
            "exposition": exposition_summary,
            "active_task_context": active_task_context,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        prompt = CHAT_RESPONSE_PROMPT.format(**prompt_input)
        logger.debug("Formatted chat response prompt:\n%s", prompt)
        response = call_with_retry(llm.invoke, prompt)
        ai_response_content = response.content.strip()
    except Exception as e:
        error_msg = f"LLM call failed during chat response generation: {e}"
        logger.error(error_msg, exc_info=True)
        ai_response_content = (
            "Sorry, I encountered an error while generating a response."
        )
        updated_state["error_message"] = error_msg

    # Prepare output
    if ai_response_content is None:
        ai_response_content = "Sorry, I couldn't generate a response."

    logger.info(f"Generated chat response content for user {user_id}.")
    updated_state["new_assistant_message"] = (
        ai_response_content  # Return only the string content
    )
    updated_state["current_interaction_mode"] = "chatting"  # Ensure mode is chatting

    return updated_state


def generate_new_exercise(state: LessonState) -> LessonState:
    """Generates a new, unique exercise."""
    logger.info("Generating new exercise.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None  # Clear previous error
    updated_state["active_exercise"] = None  # Clear previous exercise
    updated_state["active_assessment"] = None  # Clear assessment
    updated_state["new_assistant_message"] = None  # Clear previous message

    user_id: Optional[str] = updated_state.get("user_id")

    # Context
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:1000]
    # TODO: Improve tracking of generated exercises
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

    # Call LLM
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
        logger.debug("Formatted exercise prompt:\n%s", formatted_prompt)
        response = call_with_retry(llm.invoke, formatted_prompt)

        try:
            # Use the robust parser
            parsed_result = _parse_llm_json_response(response)
            # Basic validation (can be expanded)
            # Basic validation (check if it's a dict and has a 'type')
            if (
                parsed_result
                and isinstance(parsed_result, dict)  # Ensure it's a dict
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
        except Exception as parse_err:  # Catch any parsing error
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

    # Update State
    if new_exercise:
        # Cast TypedDict to Dict for state assignment
        updated_state["active_exercise"] = cast(Dict[str, Any], new_exercise)
        updated_state["current_interaction_mode"] = "awaiting_answer"

        confirmation_content = (
            f"Okay, here's an exercise for you:\n\n**Type:** {new_exercise.get('type')}\n**Instructions:** "
            f"{new_exercise.get('instructions')}")
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
        if not updated_state.get("error_message"):  # Set default error if none exists
            updated_state["error_message"] = (
                "Exercise generation failed (invalid format or LLM error)."
            )
        updated_state["current_interaction_mode"] = "chatting"

    return updated_state


def _prepare_evaluation_context(
    active_exercise: Optional[Dict[str, Any]],  # Expect dict from state
    active_assessment: Optional[Dict[str, Any]],  # Expect dict from state
) -> Dict[str, str]:
    """Prepares the context dictionary needed for the evaluation prompt."""
    context = {
        "task_type": "Unknown",
        "task_details": "N/A",
        "correct_answer_details": "N/A",
    }
    task = (
        active_exercise or active_assessment
    )  # Prioritize exercise if both somehow exist
    if task:
        context["task_type"] = "Exercise" if active_exercise else "Assessment Question"
        instructions = task.get("instructions")
        question = (
            task.get("question") if active_exercise else task.get("question_text")
        )
        details = f"Type: {task.get('type')}\nInstructions/Question: {instructions or question}"
        options = task.get("options")
        if options and isinstance(options, list):  # Add type check
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
        ):  # Add type check
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
    updated_state["error_message"] = None  # Clear previous error
    updated_state["evaluation_feedback"] = None  # Clear previous feedback
    updated_state["score_update"] = None  # Clear previous score
    updated_state["new_assistant_message"] = None  # Clear previous message

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
        # Ensure active tasks are None
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
        # Keep mode as awaiting_answer, keep task active
        updated_state["current_interaction_mode"] = "awaiting_answer"
        return updated_state

    # Prepare context for LLM
    # Cast state dicts (which are Dict[str, Any]) for the function call
    eval_context = _prepare_evaluation_context(
        cast(
            Optional[Dict[str, Any]], active_exercise
        ),  # Mypy Error Fix 4a - Cast to Dict
        cast(
            Optional[Dict[str, Any]], active_assessment
        ),  # Mypy Error Fix 4b - Cast to Dict
    )
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")

    # Call LLM
    evaluation_result: Optional[EvaluationResult] = None
    llm = _get_llm(temperature=0.1)
    if not llm:
        error_msg = "LLM not configured for evaluation."
        logger.error(error_msg)
        updated_state["error_message"] = error_msg
        updated_state["new_assistant_message"] = (
            "Sorry, I cannot evaluate your answer right now (LLM unavailable)."
        )
        updated_state["current_interaction_mode"] = "chatting"  # Revert mode
        # Clear active task on LLM error
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
        logger.debug("Formatted evaluation prompt:\n%s", formatted_prompt)
        response = call_with_retry(llm.invoke, formatted_prompt)

        try:
            # Use robust parser
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
        except Exception as parse_err:  # Catch any parsing error
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
        updated_state["current_interaction_mode"] = "chatting"  # Revert mode
        # Clear active task on LLM error
        updated_state["active_exercise"] = None
        updated_state["active_assessment"] = None
        return updated_state

    # Update State based on evaluation
    if evaluation_result:
        updated_state["evaluation_feedback"] = evaluation_result.get(
            "feedback", "Evaluation complete."
        )
        updated_state["score_update"] = evaluation_result.get("score")
        updated_state["new_assistant_message"] = evaluation_result.get(
            "feedback", "Okay, let's continue."
        )
    else:
        # Handle case where parsing failed but LLM call didn't raise exception
        updated_state["new_assistant_message"] = (
            "Sorry, I had trouble processing the evaluation."
        )
        if not updated_state.get("error_message"):
            updated_state["error_message"] = (
                "Evaluation failed (invalid format or LLM error)."
            )

    # Clear active task and revert mode after evaluation attempt
    updated_state["active_exercise"] = None
    updated_state["active_assessment"] = None
    updated_state["current_interaction_mode"] = "chatting"
    updated_state["potential_answer"] = None  # Clear potential answer

    return updated_state


def generate_new_assessment(state: LessonState) -> LessonState:
    """Generates a new assessment question."""
    logger.info("Generating new assessment question.")
    updated_state = cast(LessonState, state.copy())
    updated_state["error_message"] = None  # Clear previous error
    updated_state["active_exercise"] = None  # Clear exercise
    updated_state["active_assessment"] = None  # Clear previous assessment
    updated_state["new_assistant_message"] = None  # Clear previous message

    user_id: Optional[str] = updated_state.get("user_id")

    # Context
    topic: str = updated_state.get("lesson_topic", "Unknown Topic")
    lesson_title: str = updated_state.get("lesson_title", "Unknown Lesson")
    user_level: str = updated_state.get("user_knowledge_level", "beginner")
    exposition_summary: str = updated_state.get("lesson_exposition", "")[:1000]
    # TODO: Track generated assessment questions
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

    # Call LLM
    new_assessment_q: Optional[AssessmentQuestion] = None
    llm = _get_llm(temperature=0.4)  # Slightly higher temp for variety
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
            "existing_question_descriptions_json": existing_questions_json,  # Match prompt template key
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = GENERATE_ASSESSMENT_PROMPT.format(**prompt_input)
        logger.debug("Formatted assessment prompt:\n%s", formatted_prompt)
        response = call_with_retry(llm.invoke, formatted_prompt)

        try:
            # Use robust parser
            parsed_result = _parse_llm_json_response(response)
            # Basic validation
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
        except Exception as parse_err:  # Catch any parsing error
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
            "Sorry, I encountered an error while generating  assessment question."
        )
        updated_state["current_interaction_mode"] = "chatting"
        return updated_state

    # Update State
    if new_assessment_q:
        # Cast TypedDict to Dict for state assignment
        updated_state["active_assessment"] = cast(
            Dict[str, Any], new_assessment_q
        )  # Mypy Error Fix 5
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
        if not updated_state.get("error_message"):  # Set default error if none exists
            updated_state["error_message"] = (
                "Assessment generation failed (invalid format or LLM error)."
            )
        updated_state["current_interaction_mode"] = "chatting"

    return updated_state
