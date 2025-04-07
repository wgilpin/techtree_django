"""Tests for the generate_syllabus node function."""

import json
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from core.constants import  DIFFICULTY_KEY_TO_DISPLAY
from syllabus.ai.nodes import generate_syllabus, initialize_state
from syllabus.ai.state import SyllabusState

# Add teardown to ensure all patches are properly cleaned up
@pytest.fixture(autouse=True)
def cleanup_patches():
    """Fixture to clean up any patches that might have leaked."""
    yield
    patch.stopall()  # Stop all patches after each test

# --- Test generate_syllabus ---


@patch("syllabus.ai.nodes.call_with_retry", new_callable=MagicMock)
def test_generate_syllabus_success(mock_call_retry):
    """Test successful syllabus generation with valid JSON response."""
    topic = "Gen Success Topic"
    level = "good knowledge"  # Use correct key
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["search_results"] = ["Relevant search result 1"]

    # Mock the LLM model and the response from call_with_retry
    mock_llm = MagicMock()
    # Use a Python dict and json.dumps
    mock_response_content = {
        "topic": topic,
        "level": level,
        "duration": 60,
        "learning_objectives": ["Objective 1"],
        "modules": [
            {
                "title": "Generated Module 1",
                "summary": "Summary 1",
                "lessons": [{"title": "Lesson 1.1", "summary": "S1", "duration": 10}],
            }
        ],
    }
    # Mock the response object returned by llm.generate_content
    mock_llm_response_obj = MagicMock()
    # Use .text attribute and ensure it's exactly the JSON string via dumps
    mock_llm_response_obj.text = json.dumps(mock_response_content)
    mock_call_retry.return_value = mock_llm_response_obj

    # Call the node function
    result_state_dict = generate_syllabus(initial_state, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["generated_syllabus"] is not None
    assert isinstance(result_state["generated_syllabus"], dict)
    assert result_state["generated_syllabus"]["topic"] == topic
    # Check the actual content matches the mock
    assert (
        result_state["generated_syllabus"]["modules"]
        == mock_response_content["modules"]
    )
    assert (
        len(result_state["generated_syllabus"]["modules"]) == 1
    )  # Re-assert length for clarity
    assert (
        result_state["generated_syllabus"]["modules"][0]["title"]
        == "Generated Module 1"
    )
    assert result_state["error_message"] is None
    assert result_state["error_generating"] is False

    # Check that call_with_retry was called correctly, targeting llm.generate_content
    mock_call_retry.assert_called_once()
    call_args, _ = mock_call_retry.call_args
    assert (
        call_args[0] == mock_llm.generate_content
    )  # Check it targeted the generate_content method
    # Check that the prompt string was passed as the second argument
    assert isinstance(call_args[1], str)
    assert topic in call_args[1]
    assert level in call_args[1]
    assert "Relevant search result 1" in call_args[1]


@patch("syllabus.ai.nodes.call_with_retry", new_callable=MagicMock)
def test_generate_syllabus_invalid_json(mock_call_retry):
    """Test syllabus generation with invalid JSON response (fallback)."""
    topic = "Invalid JSON Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the LLM model and response
    mock_llm = MagicMock()
    mock_invalid_json_string = "This is not valid JSON { maybe"  # Invalid JSON
    mock_llm_response_obj = MagicMock()
    mock_llm_response_obj.text = mock_invalid_json_string  # Use .text
    mock_call_retry.return_value = mock_llm_response_obj

    # Call the node function
    result_state_dict = generate_syllabus(initial_state, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions for fallback behavior
    assert result_state["generated_syllabus"] is not None
    assert isinstance(result_state["generated_syllabus"], dict)
    assert (
        result_state["generated_syllabus"]["topic"] == topic
    )  # Fallback uses initial topic
    assert (
        result_state["generated_syllabus"]["level"] == DIFFICULTY_KEY_TO_DISPLAY[level]
    )  # Fallback uses display value
    # Assert fallback structure (has 2 default modules)
    assert len(result_state["generated_syllabus"]["modules"]) == 2
    assert (
        result_state["generated_syllabus"]["modules"][0]["title"]
        == f"Introduction to {topic}"
    )
    assert (
        "LLM call failed or returned empty/invalid JSON"
        in result_state["error_message"]
    )
    assert result_state["error_generating"] is True

    mock_call_retry.assert_called_once()


@patch("syllabus.ai.nodes.call_with_retry", new_callable=MagicMock)
def test_generate_syllabus_llm_failure(mock_call_retry):
    """Test syllabus generation when the LLM call fails."""
    topic = "LLM Fail Topic"
    level = "advanced"  # Use correct key from constants
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the LLM model and simulate failure in call_with_retry
    mock_llm = MagicMock()
    mock_call_retry.side_effect = Exception("LLM API Error")

    # Call the node function
    result_state_dict = generate_syllabus(initial_state, llm_model=mock_llm)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions for fallback behavior due to LLM error
    assert result_state["generated_syllabus"] is not None
    assert isinstance(result_state["generated_syllabus"], dict)
    assert result_state["generated_syllabus"]["topic"] == topic
    assert (
        result_state["generated_syllabus"]["level"] == DIFFICULTY_KEY_TO_DISPLAY[level]
    )  # Fallback uses display value
    # Assert fallback structure (has 2 default modules)
    assert len(result_state["generated_syllabus"]["modules"]) == 2
    assert (
        result_state["generated_syllabus"]["modules"][0]["title"]
        == f"Introduction to {topic}"
    )
    assert "LLM API Error" in result_state["error_message"]
    assert result_state["error_generating"] is True

    mock_call_retry.assert_called_once()


def test_generate_syllabus_no_llm():
    """Test syllabus generation when llm_model is None."""
    topic = "No LLM Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Call the node function with llm_model=None
    result_state_dict = generate_syllabus(initial_state, llm_model=None)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions for fallback behavior due to missing LLM
    assert result_state["generated_syllabus"] is not None
    assert isinstance(result_state["generated_syllabus"], dict)
    assert result_state["generated_syllabus"]["topic"] == topic
    assert (
        result_state["generated_syllabus"]["level"] == DIFFICULTY_KEY_TO_DISPLAY[level]
    )  # Fallback uses display value
    # Assert specific fallback structure for no LLM
    assert result_state["generated_syllabus"]["modules"] == [
        {
            "title": "Generation Failed",
            "summary": "Fallback due to error.",
            "lessons": [],
        }
    ]
    assert "LLM model not configured" in result_state["error_message"]
    assert result_state["error_generating"] is True
