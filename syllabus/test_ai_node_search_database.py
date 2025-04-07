"""Tests for the search_database node function."""

# pylint: disable=redefined-outer-name, no-member

from typing import cast

import pytest
from django.contrib.auth import get_user_model

from core.constants import DIFFICULTY_ADVANCED, DIFFICULTY_GOOD_KNOWLEDGE
from core.models import Lesson, Module, Syllabus
from syllabus.ai.nodes import initialize_state, search_database
from syllabus.ai.state import SyllabusState

User = get_user_model()

# --- Fixtures for DB tests ---


@pytest.fixture
def test_user():
    """Fixture for creating a test user."""
    return User.objects.create_user(username="testnodeuser_db", password="password")


@pytest.fixture
def existing_user_syllabus(test_user):
    """Fixture for a syllabus associated with a specific user."""
    syllabus = Syllabus.objects.create(  # pylint: disable=no-member
        user=test_user,
        topic="User DB Test Topic",
        level=DIFFICULTY_GOOD_KNOWLEDGE,  # Use constant display value
        user_entered_topic="User DB Test Topic",
    )
    # Add a module and lesson for structure formatting test
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="User Mod 1"
    )  # pylint: disable=no-member
    Lesson.objects.create(
        module=module, lesson_index=0, title="User Lsn 1.1", duration=5
    )  # pylint: disable=no-member
    # Refresh to ensure relations are loaded
    return Syllabus.objects.prefetch_related("modules__lessons").get(
        pk=syllabus.pk
    )  # pylint: disable=no-member


@pytest.fixture
def existing_master_syllabus():
    """Fixture for a master syllabus (no user)."""
    syllabus = Syllabus.objects.create(  # pylint: disable=no-member
        user=None,  # Master syllabus
        topic="Master DB Test Topic",
        level=DIFFICULTY_ADVANCED,  # Use constant display value
        user_entered_topic="Master DB Test Topic",
        # is_master=True, # Removed: Determined by user=None
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Master Mod 1"
    )  # pylint: disable=no-member
    Lesson.objects.create(
        module=module, lesson_index=0, title="Master Lsn 1.1", duration=10
    )  # pylint: disable=no-member
    # Refresh to ensure relations are loaded
    return Syllabus.objects.prefetch_related("modules__lessons").get(
        pk=syllabus.pk
    )  # pylint: disable=no-member


# --- Test search_database ---


@pytest.mark.django_db
def test_search_database_finds_user_syllabus(test_user, existing_user_syllabus):
    """Test finding an existing syllabus for a specific user."""
    initial_state_dict = initialize_state(
        None,
        topic="User DB Test Topic",
        knowledge_level="good knowledge",  # Use correct lowercase key
        user_id=str(test_user.pk),
    )
    initial_state = cast(SyllabusState, initial_state_dict)

    result_state_dict = search_database(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    assert result_state["existing_syllabus"] is not None
    assert isinstance(result_state["existing_syllabus"], dict)
    assert result_state["existing_syllabus"]["topic"] == "User DB Test Topic"
    assert (
        result_state["existing_syllabus"]["level"] == DIFFICULTY_GOOD_KNOWLEDGE
    )  # Assert against display value
    assert result_state["existing_syllabus"]["user_id"] == str(test_user.pk)
    assert result_state["uid"] == str(existing_user_syllabus.syllabus_id)
    # Check structure formatting
    assert len(result_state["existing_syllabus"]["modules"]) == 1
    assert result_state["existing_syllabus"]["modules"][0]["title"] == "User Mod 1"
    assert len(result_state["existing_syllabus"]["modules"][0]["lessons"]) == 1
    assert (
        result_state["existing_syllabus"]["modules"][0]["lessons"][0]["title"]
        == "User Lsn 1.1"
    )
    assert result_state["error_message"] is None


@pytest.mark.django_db
def test_search_database_finds_master_syllabus(existing_master_syllabus):
    """Test finding an existing master syllabus (no user)."""
    initial_state_dict = initialize_state(
        None,
        topic="Master DB Test Topic",
        knowledge_level="advanced",  # Use correct lowercase key
        user_id=None,  # No user ID for master
    )
    initial_state = cast(SyllabusState, initial_state_dict)

    result_state_dict = search_database(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    assert result_state["existing_syllabus"] is not None
    assert isinstance(result_state["existing_syllabus"], dict)
    assert result_state["existing_syllabus"]["topic"] == "Master DB Test Topic"
    assert (
        result_state["existing_syllabus"]["level"] == DIFFICULTY_ADVANCED
    )  # Assert against display value
    assert result_state["existing_syllabus"]["user_id"] is None
    assert result_state["uid"] == str(existing_master_syllabus.syllabus_id)
    assert len(result_state["existing_syllabus"]["modules"]) == 1
    assert result_state["error_message"] is None


@pytest.mark.django_db
def test_search_database_not_found(test_user):
    """Test when no matching syllabus is found in the database."""
    initial_state_dict = initialize_state(
        None,
        topic="NonExistent Topic",
        knowledge_level="beginner",  # Keep as beginner key
        user_id=str(test_user.pk),
    )
    initial_state = cast(SyllabusState, initial_state_dict)

    result_state_dict = search_database(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    assert result_state["existing_syllabus"] is None
    assert result_state["uid"] is None
    assert result_state["error_message"] is None  # Should be None when not found


@pytest.mark.django_db
def test_search_database_no_user_id_provided():
    """Test searching when user_id is None in state (should look for master)."""
    initial_state_dict = initialize_state(
        None,
        topic="Another Topic",
        knowledge_level="beginner",
        user_id=None,  # Explicitly None
    )
    initial_state = cast(SyllabusState, initial_state_dict)

    result_state_dict = search_database(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Expecting not to find it unless a master syllabus for 'Another Topic' exists
    assert result_state["existing_syllabus"] is None
    assert result_state["uid"] is None
    assert result_state["error_message"] is None
