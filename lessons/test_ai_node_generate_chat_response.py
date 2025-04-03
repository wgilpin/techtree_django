"""Tests for the generate_chat_response node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast, Dict, Any, List

from lessons.ai.nodes import generate_chat_response
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
        "lesson_exposition": "",
        "user_knowledge_level": "beginner",
    }
    # Add other keys expected by LessonState with default values
    state.setdefault("potential_answer", None)
    state.setdefault("new_assistant_message", None)
    state.setdefault("evaluation_feedback", None)
    state.setdefault("score_update", None)
    state.setdefault("error_message", None)
    return cast(LessonState, state)


# --- Test generate_chat_response ---

@patch('lessons.ai.nodes._get_llm')
def test_generate_chat_response_success(mock_get_llm):
    """Test generating a standard chat response."""
    mock_llm_instance = MagicMock()
    mock_response_text = "This is the AI chat response."
    # Mock the response object structure expected by the node
    mock_llm_instance.invoke.return_value = MagicMock(content=mock_response_text)
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Explain Python decorators."
    initial_state = create_initial_lesson_state(user_message)
    # Simulate history context being added before the node call
    initial_state["history_context"] = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": user_message}
    ]

    result_state_dict = generate_chat_response(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["new_assistant_message"] == mock_response_text
    assert result_state.get("error_message") is None
    mock_llm_instance.invoke.assert_called_once()
    # Check that history was included in the prompt context
    prompt_arg = mock_llm_instance.invoke.call_args[0][0]
    assert "Hi" in str(prompt_arg)
    assert "Hello!" in str(prompt_arg)
    assert user_message in str(prompt_arg)


@patch('lessons.ai.nodes._get_llm')
def test_generate_chat_response_llm_error(mock_get_llm):
    """Test chat response generation when LLM fails."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.side_effect = Exception("LLM Chat Error")
    mock_get_llm.return_value = mock_llm_instance

    user_message = "Trigger LLM error."
    initial_state = create_initial_lesson_state(user_message)
    # Simulate history context
    initial_state["history_context"] = [{"role": "user", "content": user_message}]


    result_state_dict = generate_chat_response(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert "Sorry, I encountered an error" in result_state["new_assistant_message"]
    assert "LLM Chat Error" in result_state.get("error_message", "")
    mock_llm_instance.invoke.assert_called_once()


def test_generate_chat_response_no_llm():
    """Test chat response generation when LLM is not configured."""
    # Temporarily patch _get_llm to return None for this specific test
    with patch('lessons.ai.nodes._get_llm', return_value=None):
        user_message = "No LLM available."
        initial_state = create_initial_lesson_state(user_message)
        # Simulate history context
        initial_state["history_context"] = [{"role": "user", "content": user_message}]

        result_state_dict = generate_chat_response(initial_state)
        result_state = cast(LessonState, result_state_dict)

        # Check the specific message for LLM unavailable
        assert "Sorry, I cannot respond right now (LLM unavailable)." in result_state["new_assistant_message"]
        assert "LLM not configured" in result_state.get("error_message", "")


@patch('lessons.ai.nodes._get_llm') # Mock LLM even though it shouldn't be called
def test_generate_chat_response_no_user_message(mock_get_llm):
    """Test chat response when the last history item isn't from the user."""
    mock_llm_instance = MagicMock()
    mock_get_llm.return_value = mock_llm_instance

    initial_state = create_initial_lesson_state("This message shouldn't matter")
    # Simulate history ending with an assistant message
    initial_state["history_context"] = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"}
    ]

    result_state_dict = generate_chat_response(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Check the specific message for missing user message
    assert "It seems I missed your last message." in result_state["new_assistant_message"]
    assert result_state.get("error_message") is None # No error should be set
    mock_llm_instance.invoke.assert_not_called() # LLM should not be called