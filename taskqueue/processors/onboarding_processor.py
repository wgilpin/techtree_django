"""Processor for onboarding assessment background tasks."""

from django.conf import settings
from onboarding.logic import (
    get_ai_instance,
    handle_normal_answer,
    handle_skip_answer,
    generate_next_question,
)

def process_onboarding_assessment(task):
    """
    Process an onboarding assessment task.

    Args:
        task: The AITask instance containing onboarding assessment data.

    Returns:
        dict: The updated assessment state and next question.
    """
    input_data = task.input_data
    assessment_state = input_data.get("assessment_state", {})
    answer = input_data.get("answer")
    is_skip = input_data.get("skip", False)

    ai_instance = get_ai_instance()

    if is_skip:
        assessment_state = handle_skip_answer(assessment_state, settings)
    else:
        assessment_state = handle_normal_answer(assessment_state, ai_instance, answer, settings)

    assessment_state = generate_next_question(assessment_state, ai_instance, settings)

    return {
        "assessment_state": assessment_state,
        "question": assessment_state.get("current_question"),
        "difficulty": assessment_state.get("current_question_difficulty"),
        "is_complete": assessment_state.get("is_complete", False),
        "feedback": assessment_state.get("feedback"),
    }