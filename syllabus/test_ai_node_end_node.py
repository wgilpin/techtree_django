"""Tests for the end_node node function."""

from typing import cast

from syllabus.ai.nodes import end_node, initialize_state
from syllabus.ai.state import SyllabusState

# --- Test end_node ---


def test_end_node():
    """Test that the end node simply returns the state it receives."""
    topic = "End Topic"
    level = "beginner"
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["some_final_value"] = "test"

    # Call the node function
    result_state_dict = end_node(initial_state)
    # The end_node now returns the full state, so cast it
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions - should be identical to the input state
    assert result_state == initial_state
    assert result_state["topic"] == topic
    assert result_state["some_final_value"] == "test"
