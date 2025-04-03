"""Tests for the generate_new_exercise node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast, Dict, Any, List
import json

from lessons.ai.nodes import generate_new_exercise
from lessons.ai.state import LessonState

# Helper to create a basic initial state for tests (copied for independence)
def create_initial_lesson_state(user_message: str) -> LessonState:
    """Creates a basic LessonState dictionary for testing."""
    state: Dict[str, Any] = {
        "user_message": user_message,
        "history_context": [],
        "current_interaction_mode": "chatting",
        "active_exercise": None,
        "active_assessment": None,
        "topic": "Test Topic",
        "lesson_title": "Test Lesson",
        "user_id": None,
        "lesson_exposition": "", # Add exposition for context
        "user_knowledge_level": "beginner",
    }
    # Add other keys expected by LessonState with default values
    state.setdefault("potential_answer", None)
    state.setdefault("new_assistant_message", None)
    state.setdefault("evaluation_feedback", None)
    state.setdefault("score_update", None)
    state.setdefault("error_message", None)
    return cast(LessonState, state)


# --- Test generate_new_exercise ---

@patch('lessons.ai.nodes._get_llm')
def test_generate_new_exercise_success(mock_get_llm):
    """Test generating a new exercise successfully."""
    mock_llm_instance = MagicMock()
    mock_exercise_data = {
        "id": "ex1",
        "type": "multiple_choice",
        "question": "What is 2+2?",
        "options": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
        "correct_answer_id": "b",
        "explanation": "Basic addition."
    }
    # Mock the response object structure
    mock_llm_instance.invoke.return_value = MagicMock(content=json.dumps(mock_exercise_data))
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Give me an exercise")
    initial_state["lesson_exposition"] = "Some lesson content about addition."

    result_state_dict = generate_new_exercise(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] == mock_exercise_data
    assert result_state["current_interaction_mode"] == "awaiting_answer"
    assert result_state.get("error_message") is None
    mock_llm_instance.invoke.assert_called_once()
    # Check prompt includes relevant context
    prompt_arg = mock_llm_instance.invoke.call_args[0][0]
    assert "Some lesson content about addition." in str(prompt_arg)
    assert "Test Lesson" in str(prompt_arg)


@patch('lessons.ai.nodes._get_llm')
def test_generate_new_exercise_llm_error(mock_get_llm):
    """Test exercise generation when LLM fails."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.side_effect = Exception("LLM Exercise Error")
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Give me an exercise")
    initial_state["lesson_exposition"] = "Some content" # Need exposition

    result_state_dict = generate_new_exercise(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] is None
    assert result_state["current_interaction_mode"] == "chatting" # Reverts on error
    assert "LLM Exercise Error" in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_generate_new_exercise_invalid_json(mock_get_llm):
    """Test exercise generation when LLM returns invalid JSON."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = MagicMock(content='invalid json')
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Give me an exercise")
    initial_state["lesson_exposition"] = "Some content" # Need exposition

    result_state_dict = generate_new_exercise(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] is None
    assert result_state["current_interaction_mode"] == "chatting"
    assert "Received invalid exercise format from LLM" in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()


def test_generate_new_exercise_no_llm():
    """Test exercise generation when LLM is not configured."""
    with patch('lessons.ai.nodes._get_llm', return_value=None):
        initial_state = create_initial_lesson_state("Give me an exercise")
        initial_state["lesson_exposition"] = "Some content" # Need exposition

        result_state_dict = generate_new_exercise(initial_state)
        result_state = cast(LessonState, result_state_dict)

        assert result_state["active_exercise"] is None
        assert result_state["current_interaction_mode"] == "chatting"
        assert "LLM not configured" in result_state.get("error_message", "")

def test_generate_new_exercise_no_exposition():
    """Test exercise generation when lesson exposition is missing."""
    initial_state = create_initial_lesson_state("Give me an exercise")
    initial_state["lesson_exposition"] = "" # Empty exposition

    result_state_dict = generate_new_exercise(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_exercise"] is None
    assert result_state["current_interaction_mode"] == "chatting"
    assert "lesson content is missing" in result_state.get("error_message", "")
    assert "lesson content is missing" in result_state.get("new_assistant_message", "")