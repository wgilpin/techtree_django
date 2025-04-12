"""Onboarding assessment logic functions."""

from django.conf import settings

from core.constants import DIFFICULTY_BEGINNER, DIFFICULTY_VALUES
from .ai import TechTreeAI

MAX_QUESTIONS = 10

def get_ai_instance() -> TechTreeAI:
    """Instantiates the AI logic class."""
    return TechTreeAI()

def generate_next_question(assessment_state: dict, ai_instance, settings=settings) -> dict:
    """Generate the next question and update assessment state, enforcing max questions and early termination."""
    question_results = ai_instance.generate_question(assessment_state.copy())

    assessment_state["current_question"] = question_results.get("current_question", "Error")
    assessment_state["current_question_difficulty"] = question_results.get(
        "current_question_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
    )
    assessment_state["questions_asked"] = question_results.get(
        "questions_asked", assessment_state.get("questions_asked", [])
    )
    assessment_state["question_difficulties"] = question_results.get(
        "question_difficulties", assessment_state.get("question_difficulties", [])
    )
    if "step" in question_results:
        assessment_state["step"] = question_results["step"]

    # Determine current question number (1-based)
    question_number = len(assessment_state.get("questions_asked", []))
    assessment_state["question_number"] = question_number
    assessment_state["max_questions"] = MAX_QUESTIONS

    # Early termination: 2 consecutive 0 scores at bottom level
    min_difficulty = DIFFICULTY_VALUES[DIFFICULTY_BEGINNER]
    at_min_difficulty = assessment_state.get("current_question_difficulty", min_difficulty) == min_difficulty
    answer_evals = assessment_state.get("answer_evaluations", [])
    if (
        at_min_difficulty and
        len(answer_evals) >= 2 and
        answer_evals[-1] == 0.0 and
        answer_evals[-2] == 0.0
    ):
        assessment_state["is_complete"] = True
        assessment_state["knowledge_level"] = "Beginner"
        assessment_state["feedback"] = "Assessment ended early due to repeated incorrect answers at the lowest level."
        return assessment_state

    # Enforce max questions
    if question_number >= MAX_QUESTIONS:
        assessment_state["is_complete"] = True
        if "knowledge_level" not in assessment_state:
            assessment_state["knowledge_level"] = "Beginner"  # Or use a more sophisticated calculation
   
    return assessment_state

def handle_normal_answer(assessment_state: dict, ai_instance, answer: str, settings=settings) -> dict:
    """
    Update assessment state for a normal answer submission.
    Implements: after 2 consecutive correct answers at the same level, increase difficulty.
    """
    eval_results = ai_instance.evaluate_answer(assessment_state.copy(), answer)

    answers = eval_results.get("answers", assessment_state.get("answers", []))
    answer_evaluations = eval_results.get("answer_evaluations", assessment_state.get("answer_evaluations", []))
    current_target_difficulty = eval_results.get(
        "current_target_difficulty",
        assessment_state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY),
    )
    consecutive_wrong = eval_results.get(
        "consecutive_wrong_at_current_difficulty",
        assessment_state.get("consecutive_wrong_at_current_difficulty", 0),
    )
    feedback = eval_results.get("feedback")

    # Track consecutive correct answers at the current difficulty
    prev_consec_correct = assessment_state.get("consecutive_correct_at_current_difficulty", 0)
    last_eval = answer_evaluations[-1] if answer_evaluations else 0.0
    prev_difficulty = assessment_state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY)
    # If the last answer was correct (score >= 1.0) and at the same difficulty, increment counter
    if last_eval >= 1.0 and prev_difficulty == current_target_difficulty:
        consecutive_correct = prev_consec_correct + 1
    else:
        consecutive_correct = 1 if last_eval >= 1.0 else 0

    # If 2 consecutive correct at this level, increase difficulty (up to max)
    max_difficulty = max(DIFFICULTY_VALUES.values())
    if consecutive_correct >= 2 and current_target_difficulty < max_difficulty:
        current_target_difficulty += 1
        consecutive_correct = 0  # Reset after promotion
        feedback = (feedback or "") + " Difficulty increased due to consecutive correct answers."

    assessment_state["answers"] = answers
    assessment_state["answer_evaluations"] = answer_evaluations
    assessment_state["consecutive_wrong_at_current_difficulty"] = consecutive_wrong
    assessment_state["current_target_difficulty"] = current_target_difficulty
    assessment_state["consecutive_correct_at_current_difficulty"] = consecutive_correct
    assessment_state["feedback"] = feedback

    return assessment_state

def handle_skip_answer(assessment_state: dict, settings=settings) -> dict:
    """
    Update assessment state for a skipped answer.
    Lowers difficulty if needed, resets consecutive wrongs, and always returns the updated state.
    """
    target_difficulty = assessment_state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY)
    consecutive_wrong = assessment_state.get("consecutive_wrong_at_current_difficulty", 0) + 1
    consecutive_hard_correct = 0
    min_difficulty = 0

    # Add the skip to the state before checking for early termination
    assessment_state["answers"] = assessment_state.get("answers", []) + ["[SKIPPED]"]
    assessment_state["answer_evaluations"] = assessment_state.get("answer_evaluations", []) + [0.0]

    # Early termination: two consecutive 0/0.0 at min difficulty
    at_min_difficulty = target_difficulty == min_difficulty
    answer_evals = assessment_state.get("answer_evaluations", [])
    if (
        at_min_difficulty and
        len(answer_evals) >= 2 and
        answer_evals[-1] == 0.0 and
        answer_evals[-2] == 0.0
    ):
        assessment_state["is_complete"] = True
        assessment_state["knowledge_level"] = "Beginner"
        assessment_state["feedback"] = "Assessment ended early due to repeated incorrect/skipped answers at the lowest level."
        return assessment_state

    if consecutive_wrong >= 2 and target_difficulty > min_difficulty:
        target_difficulty -= 1
        consecutive_wrong = 0

    assessment_state["feedback"] = "Question skipped."
    assessment_state["consecutive_wrong_at_current_difficulty"] = consecutive_wrong
    assessment_state["consecutive_hard_correct_or_partial"] = consecutive_hard_correct
    assessment_state["current_target_difficulty"] = target_difficulty

    return assessment_state

