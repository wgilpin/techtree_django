"""Tests for the evaluate_answer node function."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from typing import cast, Dict, Any, List
import json

from lessons.ai.nodes import evaluate_answer
from lessons.ai.state import LessonState

# Helper to create a basic initial state for tests (copied for independence)
def create_initial_lesson_state(user_message: str) -> LessonState:
    """Creates a basic LessonState dictionary for testing."""
    state: Dict[str, Any] = {
        "user_message": user_message, # Keep user_message for potential_answer source
        "potential_answer": user_message, # Assume message is the potential answer initially
        "history_context": [],
        "current_interaction_mode": "chatting",
        "active_exercise": None,
        "active_assessment": None,
        "topic": "Test Topic",
        "lesson_title": "Test Lesson",
        "user_id": None,
        "lesson_exposition": "",
        "user_knowledge_level": "beginner",
    }
    # Add other keys expected by LessonState with default values
    state.setdefault("new_assistant_message", None)
    state.setdefault("evaluation_feedback", None)
    state.setdefault("score_update", None)
    state.setdefault("error_message", None)
    return cast(LessonState, state)


# --- Test evaluate_answer ---

@patch('lessons.ai.nodes._get_llm')
def test_evaluate_answer_exercise_correct(mock_get_llm):
    """Test evaluating a correct answer for an active exercise."""
    mock_llm_instance = AsyncMock()
    mock_evaluation = {"score": 1.0, "feedback": "Correct! Well done."}
    mock_response = AsyncMock()
    mock_response.content = json.dumps(mock_evaluation)
    mock_llm_instance.invoke = AsyncMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "The answer is 4."
    initial_state = create_initial_lesson_state(user_message)
    active_exercise = {
        "id": "ex1",
        "type": "multiple_choice",
        "question": "What is 2+2?",
        "options": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
        "correct_answer_id": "b",
        "explanation": "Basic addition."
    }
    initial_state["active_exercise"] = active_exercise
    initial_state["current_interaction_mode"] = "awaiting_answer" # Set correct mode

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] is None # Exercise should be cleared
    assert result_state["active_assessment"] is None
    assert result_state["current_interaction_mode"] == "chatting" # Mode reverts
    assert result_state["evaluation_feedback"] == "Correct! Well done."
    assert result_state["score_update"] == 1.0
    assert result_state.get("error_message") is None
    mock_llm_instance.invoke.assert_called_once()
    # Check prompt includes question, answer, explanation etc.
    prompt_arg = mock_llm_instance.invoke.call_args[0][0]
    assert "What is 2+2?" in str(prompt_arg)
    assert user_message in str(prompt_arg)
    # assert "Basic addition." in str(prompt_arg) # Explanation is not included in the evaluation prompt


@patch('lessons.ai.nodes._get_llm')
def test_evaluate_answer_assessment_incorrect(mock_get_llm):
    """Test evaluating an incorrect answer for an active assessment."""
    mock_llm_instance = AsyncMock()
    mock_evaluation = {"score": 0.2, "feedback": "Not quite, the answer involves loops."}
    mock_response_incorrect = AsyncMock()
    mock_response_incorrect.content = json.dumps(mock_evaluation)
    mock_llm_instance.invoke = AsyncMock(return_value=mock_response_incorrect)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Use recursion."
    initial_state = create_initial_lesson_state(user_message)
    active_assessment = {
        "id": "as1",
        "type": "short_answer",
        "question_text": "How to iterate in Python?",
        "correct_answer_id": None, # Not applicable here
        "explanation": "Iteration uses for/while loops."
    }
    initial_state["active_assessment"] = active_assessment
    initial_state["current_interaction_mode"] = "awaiting_answer" # Set correct mode

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] is None
    assert result_state["active_assessment"] is None # Assessment should be cleared
    assert result_state["current_interaction_mode"] == "chatting"
    assert result_state["evaluation_feedback"] == "Not quite, the answer involves loops."
    assert result_state["score_update"] == 0.2
    assert result_state.get("error_message") is None
    mock_llm_instance.invoke.assert_called_once()
    prompt_arg = mock_llm_instance.invoke.call_args[0][0]
    assert "How to iterate in Python?" in str(prompt_arg)
    assert user_message in str(prompt_arg)


def test_evaluate_answer_no_active_task():
    """Test evaluation when no exercise or assessment is active."""
    user_message = "My answer."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["current_interaction_mode"] = "submit_answer" # Mode indicates submission
    initial_state["potential_answer"] = user_message # Ensure potential answer is set

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should revert to chatting and indicate no task was active
    assert result_state["current_interaction_mode"] == "chatting"
    assert "No active exercise or assessment found" in result_state.get("error_message", "")
    assert result_state.get("evaluation_feedback") is None
    assert result_state.get("score_update") is None


@patch('lessons.ai.nodes._get_llm')
def test_evaluate_answer_llm_error(mock_get_llm):
    """Test evaluation when LLM call fails."""
    mock_llm_instance = AsyncMock()
    mock_llm_instance.invoke.side_effect = Exception("LLM Eval Error")
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Answer."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_exercise"] = {"id": "ex1", "question": "Q?"}
    initial_state["current_interaction_mode"] = "awaiting_answer" # Set correct mode

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "chatting"
    assert "LLM Eval Error" in result_state.get("error_message", "")
    assert result_state.get("evaluation_feedback") is None
    assert result_state.get("score_update") is None
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_evaluate_answer_invalid_json(mock_get_llm):
    """Test evaluation when LLM returns invalid JSON."""
    mock_llm_instance = AsyncMock()
    mock_response_invalid = AsyncMock()
    mock_response_invalid.content = 'invalid json'
    mock_llm_instance.invoke = AsyncMock(return_value=mock_response_invalid)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Answer."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_exercise"] = {"id": "ex1", "question": "Q?"}
    initial_state["current_interaction_mode"] = "awaiting_answer" # Set correct mode

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "chatting"
    assert "Received invalid evaluation format from LLM" in result_state.get("error_message", "")
    assert result_state.get("evaluation_feedback") is None
    assert result_state.get("score_update") is None
    mock_llm_instance.invoke.assert_called_once()


def test_evaluate_answer_no_llm():
    """Test evaluation when LLM is not configured."""
    with patch('lessons.ai.nodes._get_llm', return_value=None):
        user_message = "Answer."
        initial_state = create_initial_lesson_state(user_message)
        initial_state["active_exercise"] = {"id": "ex1", "question": "Q?"}
        initial_state["current_interaction_mode"] = "awaiting_answer" # Set correct mode

        result_state_dict = evaluate_answer(initial_state)
        result_state = cast(LessonState, result_state_dict)

        assert result_state["current_interaction_mode"] == "chatting"
        assert "LLM not configured" in result_state.get("error_message", "")
        assert result_state.get("evaluation_feedback") is None
        assert result_state.get("score_update") is None

def test_evaluate_answer_no_user_answer():
    """Test evaluation when user answer is missing from state."""
    initial_state = create_initial_lesson_state("") # Empty user message
    initial_state["potential_answer"] = None # Ensure potential answer is None
    initial_state["active_exercise"] = {"id": "ex1", "question": "Q?"}
    initial_state["current_interaction_mode"] = "submit_answer" # Mode indicates submission

    result_state_dict = evaluate_answer(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should stay in awaiting_answer mode and indicate no answer found
    assert result_state["current_interaction_mode"] == "awaiting_answer"
    assert "No answer found in state to evaluate." in result_state.get("error_message", "")
    assert result_state.get("evaluation_feedback") is None
    assert result_state.get("score_update") is None
    assert result_state["active_exercise"] is not None # Task should remain active