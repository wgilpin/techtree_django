"""Tests for the classify_intent node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast, Dict, Any

from lessons.ai.nodes import classify_intent
from lessons.ai.state import LessonState


# Helper to create a basic initial state for tests
def create_initial_lesson_state(user_message: str) -> LessonState:
    """Creates a basic LessonState dictionary for testing."""
    state: Dict[str, Any] = {
        "user_message": user_message,
        "history_context": [], # Assume empty history for basic intent test
        "current_interaction_mode": "chatting", # Default mode
        "active_exercise": None,
        "active_assessment": None,
        # Add other minimal required keys if nodes expect them
        "topic": "Test Topic",
        "lesson_title": "Test Lesson",
        "user_id": None, # Add user_id for logging context
        "lesson_exposition": "", # Add exposition for context
        "user_knowledge_level": "beginner", # Add level for context
    }
    # Add other keys expected by LessonState with default values
    state.setdefault("potential_answer", None)
    state.setdefault("new_assistant_message", None)
    state.setdefault("evaluation_feedback", None)
    state.setdefault("score_update", None)
    state.setdefault("error_message", None)

    return cast(LessonState, state)


# --- Test classify_intent ---

@patch('lessons.ai.nodes._get_llm') # Mock the LLM call
def test_classify_intent_chat(mock_get_llm):
    """Test classifying a general chat message."""
    mock_llm_instance = MagicMock()
    # Mock the LLM response to indicate 'chatting' intent
    mock_response_chat = MagicMock()
    mock_response_chat.content = '{"intent": "chatting"}'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_chat)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Tell me more about Python."
    initial_state = create_initial_lesson_state(user_message)
    # Simulate history context being added before the node call
    initial_state["history_context"] = [{"role": "user", "content": user_message}]


    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "chatting"
    assert result_state["user_message"] == user_message # Should persist
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_request_exercise(mock_get_llm):
    """Test classifying a request for an exercise."""
    mock_llm_instance = MagicMock()
    mock_response_exercise = MagicMock()
    mock_response_exercise.content = '{"intent": "request_exercise"}'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_exercise)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Give me an exercise."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "request_exercise"
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_request_assessment(mock_get_llm):
    """Test classifying a request for an assessment."""
    mock_llm_instance = MagicMock()
    mock_response_assessment = MagicMock()
    mock_response_assessment.content = '{"intent": "request_assessment"}'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_assessment)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Quiz me."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "request_assessment"
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_submit_answer_exercise(mock_get_llm):
    """Test classifying an answer submission when an exercise is active."""
    mock_llm_instance = MagicMock()
    # Even if LLM misclassifies, the presence of active_exercise should force submit_answer
    mock_response_chat2 = MagicMock()
    mock_response_chat2.content = '{"intent": "chatting"}'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_chat2)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "The answer is B."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_exercise"] = {"id": "ex1", "question": "Q?"} # Mark exercise as active
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "submit_answer"
    # LLM should NOT be called if active exercise/assessment forces the mode
    mock_llm_instance.invoke.assert_not_called()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_submit_answer_assessment(mock_get_llm):
    """Test classifying an answer submission when an assessment is active."""
    mock_llm_instance = MagicMock()
    mock_response_chat3 = MagicMock()
    mock_response_chat3.content = '{"intent": "chatting"}'
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_chat3)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "My final answer is C."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_assessment"] = {"id": "as1", "question": "Q?"} # Mark assessment as active
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "submit_answer"
    mock_llm_instance.invoke.assert_not_called()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_llm_error(mock_get_llm):
    """Test intent classification when the LLM call fails."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.side_effect = Exception("LLM Error") # Simulate LLM failure
    mock_get_llm.return_value = mock_llm_instance

    user_message = "This should cause an error."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should default to 'chatting' on error
    assert result_state["current_interaction_mode"] == "chatting"
    assert "LLM Error" in result_state.get("error_message", "") # Check error message is set
    mock_llm_instance.invoke.assert_called_once()


@patch('lessons.ai.nodes._get_llm')
def test_classify_intent_invalid_json(mock_get_llm):
    """Test intent classification when LLM returns invalid JSON."""
    mock_llm_instance = MagicMock()
    mock_response_invalid = MagicMock()
    mock_response_invalid.content = '{"intent": "chatting'  # Invalid JSON
    mock_llm_instance.invoke = MagicMock(return_value=mock_response_invalid)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Testing invalid JSON."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]

    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should default to 'chatting' on parsing error
    assert result_state["current_interaction_mode"] == "chatting"
    assert "LLM returned invalid intent format." in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()