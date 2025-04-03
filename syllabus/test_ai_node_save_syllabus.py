"""Tests for the save_syllabus node function."""

import pytest
from typing import cast
import uuid

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Syllabus, Module, Lesson
from syllabus.ai.nodes import initialize_state, save_syllabus
from syllabus.ai.state import SyllabusState

User = get_user_model()

# --- Fixtures (copied from test_ai_node_search_database.py for convenience) ---

@pytest.fixture
def test_user():
    """Fixture for creating a test user."""
    # Use a different username to avoid conflicts if tests run concurrently
    return User.objects.create_user(username='testnodesaveuser', password='password')


@pytest.fixture
def existing_user_syllabus(test_user):
    """Fixture for a syllabus associated with a specific user."""
    syllabus = Syllabus.objects.create( # pylint: disable=no-member
        user=test_user,
        topic="Existing Save Topic",
        level="intermediate",
        user_entered_topic="Existing Save Topic",
    )
    # Add a module and lesson for structure formatting test
    module = Module.objects.create(syllabus=syllabus, module_index=0, title="Existing Save Mod 1") # pylint: disable=no-member
    Lesson.objects.create(module=module, lesson_index=0, title="Existing Save Lsn 1.1", duration=5) # pylint: disable=no-member
    # Refresh to ensure relations are loaded
    return Syllabus.objects.prefetch_related("modules__lessons").get(pk=syllabus.pk) # pylint: disable=no-member


# --- Test save_syllabus ---

@pytest.mark.django_db
def test_save_syllabus_create_new(test_user):
    """Test saving a newly generated syllabus for a user."""
    topic = "Save New Topic"
    level = "beginner"
    user_id = str(test_user.pk)
    generated_syllabus_content = {
        "topic": topic,
        "level": level,
        "duration": 30, # Include keys expected by validation
        "learning_objectives": ["Learn saving"],
        "modules": [
            {
                "title": "Save Module 1",
                "summary": "Saving basics",
                "lessons": [
                    {"title": "Save Lesson 1.1", "summary": "First save", "duration": 10},
                    {"title": "Save Lesson 1.2", "summary": "Second save", "duration": 20}
                ]
            }
        ]
    }
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level, user_id=user_id)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = generated_syllabus_content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions on the returned state
    assert result_state["syllabus_saved"] is True
    assert result_state["saved_uid"] is not None
    saved_uid = result_state["saved_uid"]
    assert result_state["uid"] == saved_uid # UID in state should be updated
    assert result_state["error_message"] is None

    # Verify DB records
    assert Syllabus.objects.filter(pk=saved_uid).exists() # pylint: disable=no-member
    saved_syllabus = Syllabus.objects.get(pk=saved_uid) # pylint: disable=no-member
    assert saved_syllabus.topic == topic
    assert saved_syllabus.level == level
    assert saved_syllabus.user == test_user
    # assert saved_syllabus.is_master is False # is_master is not a model field
    assert saved_syllabus.modules.count() == 1
    saved_module = saved_syllabus.modules.first()
    assert saved_module.title == "Save Module 1"
    assert saved_module.module_index == 0
    assert saved_module.lessons.count() == 2
    saved_lesson1 = saved_module.lessons.get(lesson_index=0)
    saved_lesson2 = saved_module.lessons.get(lesson_index=1)
    assert saved_lesson1.title == "Save Lesson 1.1"
    assert saved_lesson1.duration == 10
    assert saved_lesson2.title == "Save Lesson 1.2"
    assert saved_lesson2.duration == 20


@pytest.mark.django_db
def test_save_syllabus_create_master():
    """Test saving a newly generated master syllabus (no user)."""
    topic = "Save Master Topic"
    level = "expert"
    generated_syllabus_content = {
        "topic": topic,
        "level": level,
        "duration": 45, # Include keys expected by validation
        "learning_objectives": ["Master saving"],
        "modules": [
            {"title": "Master Save Mod 1", "summary": "M Save Sum 1", "lessons": []}
        ]
    }
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level, user_id=None)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = generated_syllabus_content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions on the returned state
    assert result_state["syllabus_saved"] is True
    assert result_state["saved_uid"] is not None
    saved_uid = result_state["saved_uid"]
    assert result_state["uid"] == saved_uid
    assert result_state["error_message"] is None

    # Verify DB records
    assert Syllabus.objects.filter(pk=saved_uid).exists() # pylint: disable=no-member
    saved_syllabus = Syllabus.objects.get(pk=saved_uid) # pylint: disable=no-member
    assert saved_syllabus.topic == topic
    assert saved_syllabus.level == level
    assert saved_syllabus.user is None
    # assert saved_syllabus.is_master is True # is_master is not a model field
    assert saved_syllabus.modules.count() == 1
    assert saved_syllabus.modules.first().title == "Master Save Mod 1"


@pytest.mark.django_db
def test_save_syllabus_update_existing(existing_user_syllabus):
    """Test updating an existing syllabus (identified by UID in state)."""
    existing_uid = str(existing_user_syllabus.syllabus_id)
    user_id = str(existing_user_syllabus.user_id)
    topic = "Updated Topic"
    level = "advanced"
    # Simulate generated content that should update the existing record
    generated_syllabus_content = {
        "topic": topic, # Updated topic
        "level": level, # Updated level
        "duration": 99, # Include keys expected by validation
        "learning_objectives": ["Learn updating"],
        "modules": [
            {"title": "Updated Module 1", "summary": "Update Sum 1", "lessons": []} # New module structure
        ]
    }
    # Initialize state as if we found the existing one, then generated an update
    initial_state_dict = initialize_state(None, topic="Existing Save Topic", knowledge_level="intermediate", user_id=user_id)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["uid"] = existing_uid # Set the UID of the existing syllabus
    initial_state["existing_syllabus"] = None # Assume DB search didn't populate this fully
    initial_state["generated_syllabus"] = generated_syllabus_content # Provide the new content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions on the returned state
    assert result_state["syllabus_saved"] is True
    assert result_state["saved_uid"] == existing_uid # Should return the same UID
    assert result_state["uid"] == existing_uid
    assert result_state["error_message"] is None

    # Verify DB records were updated
    updated_syllabus = Syllabus.objects.get(pk=existing_uid) # pylint: disable=no-member
    assert updated_syllabus.topic == topic # Check updated field
    assert updated_syllabus.level == level # Check updated field
    assert updated_syllabus.user_id == existing_user_syllabus.user_id # User shouldn't change
    # Check modules were replaced
    assert updated_syllabus.modules.count() == 1
    updated_module = updated_syllabus.modules.first()
    assert updated_module.title == "Updated Module 1"
    assert updated_module.lessons.count() == 0


def test_save_syllabus_no_content():
    """Test saving when there is no generated_syllabus in state."""
    initial_state_dict = initialize_state(None, topic="No Content Topic", knowledge_level="beginner")
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = None # Explicitly no content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["syllabus_saved"] is False
    assert result_state["saved_uid"] is None
    assert "No generated syllabus content found in state" in result_state["error_message"]


def test_save_syllabus_invalid_content_format():
    """Test saving when generated_syllabus is not a dictionary."""
    initial_state_dict = initialize_state(None, topic="Bad Format Topic", knowledge_level="beginner")
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = "just a string" # Invalid format

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["syllabus_saved"] is False
    assert result_state["saved_uid"] is None
    assert "Invalid format for syllabus_to_save: Expected dict, got <class 'str'>" in result_state["error_message"] # Match exact error


@pytest.mark.django_db
def test_save_syllabus_missing_required_keys():
    """Test saving when generated_syllabus dict is missing required keys."""
    topic = "Missing Keys Topic"
    level = "beginner"
    # Missing 'modules', 'duration', 'learning_objectives'
    generated_syllabus_content = {
        "topic": topic,
        "level": level,
    }
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level)
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = generated_syllabus_content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["syllabus_saved"] is False
    assert result_state["saved_uid"] is None
    # Check the exact error message format (order might vary)
    assert "Syllabus data missing required keys" in result_state["error_message"]
    assert "duration" in result_state["error_message"]
    assert "learning_objectives" in result_state["error_message"]
    assert "modules" in result_state["error_message"]


@pytest.mark.django_db
def test_save_syllabus_invalid_user_id(test_user):
    """Test saving with an invalid user_id in state."""
    topic = "Invalid User Topic"
    level = "beginner"
    generated_syllabus_content = {
        "topic": topic,
        "level": level,
        "duration": 10, # Add required keys
        "learning_objectives": [],
        "modules": []
    }
    initial_state_dict = initialize_state(None, topic=topic, knowledge_level=level, user_id="nonexistent-user-pk")
    initial_state = cast(SyllabusState, initial_state_dict)
    initial_state["generated_syllabus"] = generated_syllabus_content

    # Call the node function
    result_state_dict = save_syllabus(initial_state)
    result_state = cast(SyllabusState, result_state_dict)

    # Assertions
    assert result_state["syllabus_saved"] is False
    assert result_state["saved_uid"] is None
    # Check the specific error message returned by the node for invalid PK format
    assert "Invalid User ID format 'nonexistent-user-pk'" in result_state["error_message"]