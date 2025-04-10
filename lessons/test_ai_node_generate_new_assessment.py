"""Tests for the generate_new_assessment node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast, Dict, Any, List
import json

from lessons.ai.nodes import generate_new_assessment
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


# --- Test generate_new_assessment ---

@patch('lessons.ai.nodes._get_llm')
def test_generate_new_assessment_success(mock_get_llm):
    """Test generating a new assessment successfully."""
    mock_llm_instance = MagicMock()
    mock_assessment_data = {
        "id": "as1",
        "type": "multiple_choice",
        "question_text": "Which loop is best for known iterations?",
        "options": [{"id": "a", "text": "while"}, {"id": "b", "text": "for"}],
        "correct_answer_id": "b",
        "explanation": "'for' loops are ideal for known iteration counts."
    }
    mock_response = MagicMock()
    mock_response.content = json.dumps(mock_assessment_data)
    mock_llm_instance.invoke = MagicMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Quiz me")
    initial_state["lesson_exposition"] = "Content about for and while loops."

    result_state_dict = generate_new_assessment(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_assessment"] == mock_assessment_data
    assert result_state["active_exercise"] is None
    assert result_state["current_interaction_mode"] == "awaiting_answer"
    assert result_state.get("error_message") is None
    mock_llm_instance.invoke.assert_called_once()
    # Check prompt includes relevant context
    prompt_arg = mock_llm_instance.invoke.call_args[0][0]
    assert "Content about for and while loops." in str(prompt_arg)
    assert "Test Lesson" in str(prompt_arg)


@patch('lessons.ai.nodes._get_llm')
def test_generate_new_assessment_llm_error(mock_get_llm):
    """Test assessment generation when LLM fails."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.side_effect = Exception("LLM Assessment Error")
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Quiz me")
    initial_state["lesson_exposition"] = "Some content" # Need exposition

    result_state_dict = generate_new_assessment(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_assessment"] is None
    assert result_state["current_interaction_mode"] == "chatting" # Reverts on error
    assert "LLM Assessment Error" in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_generate_new_assessment_invalid_json(mock_get_llm):
    """Test assessment generation when LLM returns invalid JSON."""
    mock_llm_instance = MagicMock()
    mock_response_invalid = MagicMock()
    mock_response_invalid.content = 'invalid json'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_invalid)
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("Quiz me")
    initial_state["lesson_exposition"] = "Some content" # Need exposition

    result_state_dict = generate_new_assessment(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_assessment"] is None
    assert result_state["current_interaction_mode"] == "chatting"
    assert "Received invalid assessment format from LLM" in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()


def test_generate_new_assessment_no_llm():
    """Test assessment generation when LLM is not configured."""
    with patch('lessons.ai.nodes._get_llm', return_value=None):
        initial_state = create_initial_lesson_state("Quiz me")
        initial_state["lesson_exposition"] = "Some content" # Need exposition

        result_state_dict = generate_new_assessment(initial_state)
        result_state = cast(LessonState, result_state_dict)

        assert result_state["active_assessment"] is None
        assert result_state["current_interaction_mode"] == "chatting"
        assert "LLM not configured" in result_state.get("error_message", "")

def test_generate_new_assessment_no_exposition():
    """Test assessment generation when lesson exposition is missing."""
    initial_state = create_initial_lesson_state("Quiz me")
    initial_state["lesson_exposition"] = "" # Empty exposition

    result_state_dict = generate_new_assessment(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["active_assessment"] is None
    assert result_state["current_interaction_mode"] == "chatting"
    assert "lesson content is missing" in result_state.get("error_message", "")
    assert "lesson content is missing" in result_state.get("new_assistant_message", "")