"""Tests for the SyllabusService class."""

# pylint: disable=missing-function-docstring, no-member

import uuid
import asyncio # Import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from core.exceptions import ApplicationError, NotFoundError
from core.models import Syllabus
from core.constants import DIFFICULTY_BEGINNER # Import constant to use correct level value
from syllabus.ai.state import SyllabusState
from syllabus.ai.syllabus_graph import SyllabusAI

# Mark all tests in this module as needing DB access
pytestmark = [pytest.mark.django_db(transaction=True)]

# Add teardown to ensure all patches are properly cleaned up
@pytest.fixture(autouse=True)
def cleanup_patches():
    """Fixture to clean up any patches that might have leaked."""
    yield
    from unittest.mock import patch
    patch.stopall()  # Stop all patches after each test


@pytest.mark.asyncio
async def test_get_syllabus_by_id_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    result = await syllabus_service.get_syllabus_by_id(syllabus_id)
    assert result is not None
    assert result["syllabus_id"] == syllabus_id


@pytest.mark.asyncio
async def test_get_syllabus_by_id_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_syllabus_by_id(non_existent_id)


@pytest.mark.asyncio
async def test_get_module_details_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    module_index = 0
    result = await syllabus_service.get_module_details(syllabus_id, module_index)
    assert result is not None
    assert result["module_index"] == module_index
    assert result["title"] == "Module 1"


@pytest.mark.asyncio
async def test_get_module_details_syllabus_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_module_details(non_existent_id, 0)


@pytest.mark.asyncio
async def test_get_module_details_module_not_found(
    syllabus_service, existing_syllabus_async
):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_module_details(syllabus_id, non_existent_index)


@pytest.mark.asyncio
async def test_get_lesson_details_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    module_index = 0
    lesson_index = 1
    result = await syllabus_service.get_lesson_details(
        syllabus_id, module_index, lesson_index
    )
    assert result is not None
    assert result["lesson_index"] == lesson_index
    assert result["title"] == "Lesson 1.2"


@pytest.mark.asyncio
async def test_get_lesson_details_syllabus_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(non_existent_id, 0, 0)


@pytest.mark.asyncio
async def test_get_lesson_details_module_not_found(
    syllabus_service, existing_syllabus_async
):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(syllabus_id, non_existent_index, 0)


@pytest.mark.asyncio
async def test_get_lesson_details_lesson_not_found(
    syllabus_service, existing_syllabus_async
):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    module_index = 0
    non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(
            syllabus_id, module_index, non_existent_index
        )


@pytest.mark.asyncio
async def test_get_or_generate_syllabus_existing(
    syllabus_service, existing_syllabus_async
):
    # Await fixture ONCE
    syllabus = await existing_syllabus_async
    # Set status to COMPLETED *before* calling the service
    syllabus.status = Syllabus.StatusChoices.COMPLETED
    await sync_to_async(syllabus.save)(update_fields=['status'])

    # Use sync_to_async to safely access the user in async context
    get_user = sync_to_async(lambda s: s.user)
    user = await get_user(syllabus)

    # Now call the service - use the correct level value (DIFFICULTY_BEGINNER)
    result = await syllabus_service.get_or_generate_syllabus(
        topic="Existing Topic", level=DIFFICULTY_BEGINNER, user=user # Use constant
    )
    assert result is not None
    assert isinstance(result, uuid.UUID) # Check that a UUID was returned
    assert result == syllabus.syllabus_id # Should return the existing COMPLETED ID


@pytest.mark.asyncio
@patch("asyncio.create_task") # Patch asyncio.create_task to check background launch
@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance") # Keep mocking AI
async def test_get_or_generate_syllabus_generate_success(
    mock_get_ai, mock_create_task, syllabus_service, test_user_async
):
    """
    Test that when no syllabus exists, a placeholder is created,
    a background task is launched, and the placeholder ID is returned.
    """
    user = await test_user_async
    topic = f"Unique Gen Topic {uuid.uuid4()}"
    level = "intermediate"

    # Ensure no syllabus exists for this combination initially
    assert not await Syllabus.objects.filter(topic=topic, level=level, user=user).aexists()

    # Call the method under test
    result_uuid = await syllabus_service.get_or_generate_syllabus(
        topic=topic, level=level, user=user
    )

    # Verify a placeholder syllabus was created in the DB
    try:
        placeholder_syllabus = await Syllabus.objects.aget(syllabus_id=result_uuid)
        assert placeholder_syllabus.topic == topic
        assert placeholder_syllabus.level == level
        assert placeholder_syllabus.user == user
        assert placeholder_syllabus.status == Syllabus.StatusChoices.GENERATING
    except Syllabus.DoesNotExist:
        pytest.fail(f"Placeholder syllabus with ID {result_uuid} was not created.")

    # Verify the result is the UUID of the created placeholder
    assert result_uuid == placeholder_syllabus.syllabus_id

    # Verify asyncio.create_task was called once to launch background generation
    mock_create_task.assert_called_once()

    # Optional: Check the arguments passed to the background task if needed
    # background_task_coro = mock_create_task.call_args[0][0]
    # assert background_task_coro.__name__ == '_run_generation_task'
    # # Further inspection of coro args might be complex

# Removed tests that expected synchronous ApplicationError on generation failure,
# as generation now happens in a background task.
