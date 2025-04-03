"""Tests for the search_internet node function."""

import pytest
from unittest.mock import patch, MagicMock
from typing import cast
from requests import RequestException

from syllabus.ai.nodes import initialize_state, search_internet
from syllabus.ai.state import SyllabusState


# --- Test search_internet ---

@patch('syllabus.ai.nodes.call_with_retry', new_callable=MagicMock)
def test_search_internet_success(mock_call_retry):
    """Test successful internet search."""
    topic = "Web Search Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the tavily client and the return value of call_with_retry
    mock_tavily = MagicMock()
    # Simulate Tavily returning a dict with 'results' key for each call
    mock_tavily_response_1 = {"results": [{"content": "Mocked Tavily search result 1."}]}
    mock_tavily_response_2 = {"results": [{"content": "Mocked Tavily search result 2."}]}
    mock_call_retry.side_effect = [mock_tavily_response_1, mock_tavily_response_2] # Return different results per call

    # Call the node function
    result_state_dict = search_internet(initial_state, tavily_client=mock_tavily)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    expected_queries = [
        f"{topic} syllabus curriculum outline learning objectives",
        f"{topic} course syllabus curriculum for {level} students"
    ]
    assert result_state["search_queries"] == expected_queries
    assert result_state["search_results"] == ["Mocked Tavily search result 1.", "Mocked Tavily search result 2."] # Check combined results
    assert result_state["error_message"] is None

    # Check that call_with_retry was called for each query
    assert mock_call_retry.call_count == len(expected_queries)
    # Check the first call
    call_args_1, call_kwargs_1 = mock_call_retry.call_args_list[0]
    assert call_args_1[0] == mock_tavily.search # Check it targeted the search method
    assert call_kwargs_1['query'] == expected_queries[0] # Check the query keyword argument
    assert call_kwargs_1['search_depth'] == 'advanced'
    # Check the second call
    call_args_2, call_kwargs_2 = mock_call_retry.call_args_list[1]
    assert call_args_2[0] == mock_tavily.search
    assert call_kwargs_2['query'] == expected_queries[1] # Check the query keyword argument
    assert call_kwargs_2['search_depth'] == 'advanced'


@patch('syllabus.ai.nodes.call_with_retry', new_callable=MagicMock)
def test_search_internet_failure(mock_call_retry):
    """Test internet search when the API call fails."""
    topic = "API Fail Topic"
    level = "intermediate"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the tavily client and simulate failure in call_with_retry on the first call
    mock_tavily = MagicMock()
    mock_call_retry.side_effect = RequestException("Tavily API Error")

    # Call the node function
    result_state_dict = search_internet(initial_state, tavily_client=mock_tavily)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    expected_queries = [
        f"{topic} syllabus curriculum outline learning objectives",
        # Only the first query is attempted before failure
    ]
    assert result_state["search_queries"] == expected_queries
    # Error message is added to results
    assert result_state["search_results"] == [f"Error during web search for query '{expected_queries[0]}': Tavily API Error"]
    assert "Tavily API Error" in result_state["error_message"]

    # Check that call_with_retry was called once
    mock_call_retry.assert_called_once()


def test_search_internet_no_client():
    """Test internet search when tavily_client is None."""
    topic = "No Client Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Call the node function with tavily_client=None
    result_state_dict = search_internet(initial_state, tavily_client=None)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["search_queries"] == [] # No query attempted
    assert result_state["search_results"] == []
    assert "Tavily client not configured" in result_state["error_message"]