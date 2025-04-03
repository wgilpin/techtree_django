"""Tests for the search_internet node function."""

import pytest
from unittest.mock import MagicMock, AsyncMock  # Changed patch to AsyncMock
from typing import cast
from requests import RequestException

from tavily import AsyncTavilyClient # Import the actual client for type hinting if needed

from syllabus.ai.nodes import initialize_state, search_internet
from syllabus.ai.state import SyllabusState


# --- Test search_internet ---

@pytest.mark.asyncio
async def test_search_internet_success(): # Removed mock_call_retry, added async
    """Test successful internet search."""
    topic = "Web Search Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the AsyncTavilyClient and its search method
    mock_tavily = MagicMock(spec=AsyncTavilyClient)
    # search needs to be an async function/mock
    mock_tavily.search = AsyncMock()

    # Define responses for the three concurrent calls
    mock_response_1 = {"results": [{"content": "Overview result."}]}
    mock_response_2 = {"results": [{"content": "Syllabus objectives result."}]}
    mock_response_3 = {"results": [{"content": f"Course for {level} result."}]}
    mock_tavily.search.side_effect = [mock_response_1, mock_response_2, mock_response_3]

    # Call the node function
    result_state_dict = await search_internet(initial_state, tavily_client=mock_tavily) # Added await
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    # Assertions - check against the new queries defined in the async function
    expected_queries = [
        f"{topic} overview",
        f"{topic} syllabus curriculum outline learning objectives",
        f"{topic} course syllabus curriculum for {level} students",
    ]
    assert result_state["search_queries"] == expected_queries
    # Check combined results from the side_effect list
    expected_results = [
        "Overview result.",
        "Syllabus objectives result.",
        f"Course for {level} result."
    ]
    assert result_state["search_results"] == expected_results
    assert result_state["error_message"] is None

    # Check that the mock search method was called correctly for each query
    assert mock_tavily.search.call_count == len(expected_queries)
    # Check calls (order might vary with gather, but args should match)
    calls = mock_tavily.search.call_args_list
    # Extract keyword args from each call to check query and params
    called_queries = {call.kwargs['query'] for call in calls}
    expected_query_set = set(expected_queries)
    assert called_queries == expected_query_set

    # Optionally check specific params for one call if needed, e.g.:
    # first_call_kwargs = calls[0].kwargs
    # assert first_call_kwargs['query'] == expected_queries[0]
    # assert first_call_kwargs['include_domains'] == ["en.wikipedia.org"]
    # assert first_call_kwargs['max_results'] == 2
    # assert first_call_kwargs['search_depth'] == 'advanced'


@pytest.mark.asyncio
async def test_search_internet_failure(): # Removed mock_call_retry, added async
    """Test internet search when the API call fails."""
    topic = "API Fail Topic"
    level = "intermediate"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Mock the AsyncTavilyClient and simulate failure in its search method
    mock_tavily = MagicMock(spec=AsyncTavilyClient)
    mock_tavily.search = AsyncMock(side_effect=RequestException("Simulated Tavily API Error"))

    # Call the node function
    result_state_dict = await search_internet(initial_state, tavily_client=mock_tavily) # Added await
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    # Assertions - All queries are attempted by gather, but exceptions are caught
    expected_queries = [
        f"{topic} overview",
        f"{topic} syllabus curriculum outline learning objectives",
        f"{topic} course syllabus curriculum for {level} students",
    ]
    assert result_state["search_queries"] == expected_queries
    # Since all calls fail with the side_effect, results should be empty
    assert result_state["search_results"] == []
    # Check that the error message reflects the failures
    assert "Search failed for" in result_state["error_message"]
    assert "Simulated Tavily API Error" in result_state["error_message"]

    # Check that the mock search method was called for all queries
    assert mock_tavily.search.call_count == len(expected_queries)


@pytest.mark.asyncio
async def test_search_internet_no_client(): # Added async
    """Test internet search when tavily_client is None."""
    topic = "No Client Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)

    # Call the node function with tavily_client=None
    result_state_dict = await search_internet(initial_state, tavily_client=None) # Added await
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["search_queries"] == [] # No query attempted
    assert result_state["search_results"] == []
    assert "Tavily client not configured" in result_state["error_message"]