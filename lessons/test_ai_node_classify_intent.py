"""Tests for the classify_intent node function."""

from typing import Any, Dict, cast
from unittest.mock import MagicMock, patch

from lessons.ai.classify_intent import classify_intent
from lessons.ai.state import LessonState


# Helper to create a basic initial state for tests
def create_initial_lesson_state(user_message: str) -> LessonState:
    """Creates a basic LessonState dictionary for testing."""
    state: Dict[str, Any] = {
        "last_user_message": user_message,
        "history_context": [],  # Assume empty history for basic intent test
        "current_interaction_mode": "chatting", # Default mode
        "active_exercise": None,
        "active_assessment": None,
        # Add other minimal required keys if nodes expect them
        "topic": "Test Topic",
        "lesson_title": "Test Lesson",
        "user_id": None,  # Add user_id for logging context
        "lesson_exposition": "",  # Add exposition for context
        "user_knowledge_level": "beginner",  # Add level for context
    }
    # Add other keys expected by LessonState with default values
    state.setdefault("potential_answer", None)
    state.setdefault("new_assistant_message", None)
    state.setdefault("evaluation_feedback", None)
    state.setdefault("score_update", None)
    state.setdefault("error_message", None)

    return cast(LessonState, state)


# --- Test classify_intent ---


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_chat(mock_get_llm):
    """Test classifying a general chat message."""
    # Setup mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"intent": "chatting"}'
    mock_llm.invoke = MagicMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm
    
    user_message = "Tell me more about Python."
    initial_state = create_initial_lesson_state(user_message)
    # Simulate history context being added before the node call
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "chatting"


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_request_exercise(mock_get_llm):
    """Test classifying a request for an exercise."""
    # Setup mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"intent": "request_exercise"}'
    mock_llm.invoke = MagicMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm
    
    user_message = "Give me an exercise."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "request_exercise"


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_request_assessment(mock_get_llm):
    """Test classifying a request for an assessment."""
    # Setup mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"intent": "request_assessment"}'
    mock_llm.invoke = MagicMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm
    
    user_message = "Quiz me."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "request_assessment"


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_submit_answer_exercise(mock_get_llm):
    """Test classifying an answer submission when an exercise is active."""
    # Setup mock LLM - not needed for this test as active exercise forces submit_answer
    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm
    
    user_message = "The answer is B."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_exercise"] = {
        "id": "ex1",
        "question": "Q?",
    }  # Mark exercise as active
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "submit_answer"


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_submit_answer_assessment(mock_get_llm):
    """Test classifying an answer submission when an assessment is active."""
    # Setup mock LLM - not needed for this test as active assessment forces submit_answer
    mock_llm = MagicMock()
    mock_get_llm.return_value = mock_llm
    
    user_message = "My final answer is C."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["active_assessment"] = {
        "id": "as1",
        "question": "Q?",
    }  # Mark assessment as active
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    assert result_state["current_interaction_mode"] == "submit_answer"


@patch("lessons.ai.utils._get_llm")
def test_classify_intent_llm_error(mock_get_llm):
    """Test intent classification when the LLM call fails."""
    # Setup mock LLM to raise an exception
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = Exception("LLM Error")
    mock_get_llm.return_value = mock_llm
    
    user_message = "This should cause an error."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should default to 'chatting' on error
    assert result_state["current_interaction_mode"] == "chatting"
    assert "LLM Error" in result_state.get("error_message", "")  # Check error message is set


@patch("lessons.ai.utils._get_llm")
@patch("lessons.ai.utils._parse_llm_json_response")
def test_classify_intent_invalid_json(mock_parse_json, mock_get_llm):
    """Test intent classification when LLM returns invalid JSON."""
    # Setup mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"intent": "chatting'  # Invalid JSON
    mock_llm.invoke = MagicMock(return_value=mock_response)
    mock_get_llm.return_value = mock_llm
    
    # Setup mock parser to raise an exception
    mock_parse_json.side_effect = Exception("Invalid JSON")
    
    user_message = "Testing invalid JSON."
    initial_state = create_initial_lesson_state(user_message)
    initial_state["history_context"] = [{"role": "user", "content": user_message}]
    result_state_dict = classify_intent(initial_state)
    result_state = cast(LessonState, result_state_dict)

    # Should default to 'chatting' on parsing error
    assert result_state["current_interaction_mode"] == "chatting"
    assert "Failed to process intent JSON: Invalid JSON" in result_state.get("error_message", "")
