"""Tests for the update_syllabus node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast
import json

from syllabus.ai.nodes import initialize_state, update_syllabus
from syllabus.ai.state import SyllabusState


# --- Test update_syllabus ---

@patch('syllabus.ai.nodes.call_with_retry', new_callable=MagicMock)
def test_update_syllabus_success(mock_call_retry):
    """Test successfully updating a syllabus based on feedback."""
    topic = "Update Topic"
    level = "intermediate"
    initial_syllabus_content = {
        "topic": topic,
        "level": level,
        "duration": 60, # Add required keys
        "learning_objectives": ["Obj0"],
        "modules": [{"title": "Original Module", "lessons": []}]
    }
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = initial_syllabus_content # Assume this was generated
    feedback = "Add a module about advanced concepts."

    # Mock the LLM model and response
    mock_llm = MagicMock()
    # Use a Python dict and json.dumps
    updated_syllabus_content = {
        "topic": topic,
        "level": level,
        "duration": 120, # Updated duration
        "learning_objectives": ["Obj1", "Obj2"], # Updated objectives
        "modules": [
            {"title": "Original Module", "lessons": []},
            {"title": "Advanced Concepts", "summary": "Added based on feedback", "lessons": []}
        ]
    }
    mock_llm_response_obj = MagicMock()
    # Ensure the JSON string is perfectly valid using dumps
    mock_llm_response_obj.text = json.dumps(updated_syllabus_content)
    mock_call_retry.return_value = mock_llm_response_obj

    # Call the node function
    result_state_dict = update_syllabus(initial_state, feedback, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["generated_syllabus"] is not None
    # Check the actual content matches the mock
    assert result_state["generated_syllabus"] == updated_syllabus_content
    assert len(result_state["generated_syllabus"]["modules"]) == 2 # Re-assert length for clarity
    assert result_state["generated_syllabus"]["modules"][1]["title"] == "Advanced Concepts"
    assert result_state["error_message"] is None
    assert result_state["error_generating"] is False # Should reset error flag

    # Check LLM call
    mock_call_retry.assert_called_once()
    call_args, call_kwargs = mock_call_retry.call_args
    assert call_args[0] == mock_llm.generate_content # Check method called
    assert isinstance(call_args[1], str)
    assert topic in call_args[1]
    assert feedback in call_args[1]
    assert "Original Module" in call_args[1] # Check original content was in prompt


@patch('syllabus.ai.nodes.call_with_retry', new_callable=MagicMock)
def test_update_syllabus_llm_failure(mock_call_retry):
    """Test syllabus update when the LLM call fails."""
    topic = "Update Fail Topic"
    level = "beginner"
    initial_syllabus_content = {"topic": topic, "level": level, "duration": 1, "learning_objectives": [], "modules": []}
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = initial_syllabus_content
    feedback = "Some feedback"

    # Mock LLM and simulate failure
    mock_llm = MagicMock()
    mock_call_retry.side_effect = Exception("LLM Update Error")

    # Call the node function
    result_state_dict = update_syllabus(initial_state, feedback, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions - should return original syllabus and set error
    assert result_state["generated_syllabus"] == initial_syllabus_content
    assert "LLM Update Error" in result_state["error_message"]
    assert result_state["error_generating"] is True

    mock_call_retry.assert_called_once()


def test_update_syllabus_no_llm():
    """Test syllabus update when llm_model is None."""
    topic = "Update No LLM Topic"
    level = "beginner"
    initial_syllabus_content = {"topic": topic, "level": level, "duration": 1, "learning_objectives": [], "modules": []}
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = initial_syllabus_content
    feedback = "Some feedback"

    # Call the node function with llm_model=None
    result_state_dict = update_syllabus(initial_state, feedback, llm_model=None)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions - should return original syllabus and set error
    assert result_state["generated_syllabus"] == initial_syllabus_content
    assert "LLM model not configured" in result_state["error_message"]
    assert result_state["error_generating"] is True


def test_update_syllabus_no_initial_syllabus():
    """Test syllabus update when there's no initial syllabus in state."""
    topic = "Update No Initial Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = None # No syllabus
    feedback = "Some feedback"
    mock_llm = MagicMock()

    # Call the node function
    result_state_dict = update_syllabus(initial_state, feedback, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions - should return empty syllabus and set error
    assert result_state["generated_syllabus"] is None
    assert "No syllabus content found in state to update" in result_state["error_message"]
    assert result_state["error_generating"] is True