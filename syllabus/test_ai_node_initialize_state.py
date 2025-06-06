"""Tests for the initialize_state node function."""

from typing import cast

from core.constants import DIFFICULTY_ADVANCED, DIFFICULTY_GOOD_KNOWLEDGE
from syllabus.ai.nodes import initialize_state
from syllabus.ai.state import SyllabusState

# --- Test initialize_state ---


# pylint: disable=use-implicit-booleaness-not-comparison
def test_initialize_state_with_user():
    """Test initializing state with a user ID."""
    topic = "Test Topic"
    level = DIFFICULTY_GOOD_KNOWLEDGE  # Use correct constant
    user_id = "user123"

    initial_state_dict = initialize_state(
        None, topic=topic, knowledge_level=level, user_id=user_id
    )
    state = cast(SyllabusState, initial_state_dict)  # Cast for type checking

    assert state["topic"] == topic
    assert state["user_knowledge_level"] == level  # Check against the constant
    assert state["user_id"] == user_id
    assert state["user_entered_topic"] == topic  # Should default to topic
    assert state["existing_syllabus"] is None
    assert state["generated_syllabus"] is None
    assert state["search_queries"] == []
    assert state["search_results"] == []
    assert state["error_message"] is None
    assert state["uid"] is None
    assert state["parent_uid"] is None
    assert (
        state["is_master"] is False
    )  # Should default to False when user_id is present
    assert state["created_at"] is None  # Not set at initialization
    assert state["updated_at"] is None  # Not set at initialization


def test_initialize_state_without_user():
    """Test initializing state without a user ID (master syllabus)."""
    topic = "Master Topic"
    level = DIFFICULTY_ADVANCED  # Use correct constant

    initial_state_dict = initialize_state(
        None, topic=topic, knowledge_level=level, user_id=None
    )
    state = cast(SyllabusState, initial_state_dict)  # Cast for type checking

    assert state["topic"] == topic
    assert state["user_knowledge_level"] == level  # Check against the constant
    assert state["user_id"] is None
    assert state["user_entered_topic"] == topic
    assert state["is_master"] is True  # Should default to True when no user_id
    assert state["existing_syllabus"] is None
    assert state["generated_syllabus"] is None
