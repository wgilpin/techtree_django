"""Tests for the syllabus app."""

# pylint: skip-file

import uuid
from unittest.mock import patch, MagicMock, call, AsyncMock, ANY # Keep AsyncMock for async tests

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.test import AsyncClient, Client # Import both clients
from asgiref.sync import sync_to_async

from core.models import Syllabus, Module, Lesson
from core.exceptions import NotFoundError, ApplicationError
from syllabus.services import SyllabusService
from syllabus.ai.state import SyllabusState
from syllabus.ai.syllabus_graph import SyllabusAI

User = get_user_model()

# Mark all tests in this module as needing DB access
# Remove module-level asyncio mark, apply individually
pytestmark = [pytest.mark.django_db(transaction=True)]


# --- Async Helpers (Keep for async tests like generate_syllabus_view) ---
async def get_or_create_test_user(username, password):
    """Asynchronously gets or creates a test user."""
    try:
        user = await User.objects.aget(username=username)
        # User exists, ensure password is set (sync operation, needs wrapper)
        set_password_sync = sync_to_async(user.set_password)
        await set_password_sync(password)
        save_user_sync = sync_to_async(user.save)
        await save_user_sync(update_fields=['password'])
    except User.DoesNotExist:
        # User does not exist, create asynchronously
        user = await User.objects.acreate(
            username=username,
            password=password, # acreate handles hashing
            email=f'{username}@example.com'
        )
    return user

@sync_to_async
def async_client_login(client, **credentials):
    client.login(**credentials)

async def create_syllabus_async(user):
    """Asynchronously creates a test syllabus with modules and lessons."""
    syllabus = await Syllabus.objects.acreate(
        user=user, topic="Existing Topic", level="beginner", user_entered_topic="Existing Topic"
    )
    module1 = await Module.objects.acreate(
        syllabus=syllabus, module_index=0, title="Module 1", summary="Summary 1"
    )
    await Lesson.objects.acreate(
        module=module1, lesson_index=0, title="Lesson 1.1", summary="Summary 1.1", duration=10
    )
    await Lesson.objects.acreate(
        module=module1, lesson_index=1, title="Lesson 1.2", summary="Summary 1.2", duration=15
    )
    module2 = await Module.objects.acreate(
        syllabus=syllabus, module_index=1, title="Module 2", summary="Summary 2"
    )
    await Lesson.objects.acreate(
        module=module2, lesson_index=0, title="Lesson 2.1", summary="Summary 2.1", duration=20
    )
    # Use async prefetch here
    return await Syllabus.objects.prefetch_related("modules__lessons").aget(pk=syllabus.pk)

# --- Fixtures ---
@pytest.fixture(scope="function")
@pytest.mark.asyncio # Mark specific async fixture
async def test_user_async():
    """Provides an asynchronously created test user."""
    # Note: Password needs to be set correctly for login/force_login later
    return await get_or_create_test_user(username="testuser_async", password="password")

@pytest.fixture(scope="function")
def test_user_sync():
    user, created = User.objects.get_or_create(username="testsyllabususer_sync")
    if created:
        user.set_password("password")
        user.save()
    return user

@pytest.fixture
def syllabus_service():
    return SyllabusService()

@pytest.fixture
@pytest.mark.asyncio # Mark specific async fixture
async def existing_syllabus_async(test_user_sync): # Use the SYNC user fixture
    """Provides an asynchronously created syllabus linked to a sync user."""
    # Pass the sync user to the async creator helper
    return await create_syllabus_async(test_user_sync)

# Synchronous version of the syllabus fixture
@pytest.fixture
def existing_syllabus_sync(test_user_sync):
    """Provides a synchronously created syllabus linked to a sync user."""
    syllabus = Syllabus.objects.create(
        user=test_user_sync, topic="Existing Sync Topic", level="beginner", user_entered_topic="Existing Sync Topic"
    )
    module1 = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Module 1", summary="Summary 1"
    )
    Lesson.objects.create(
        module=module1, lesson_index=0, title="Sync Lesson 1.1", summary="Summary 1.1", duration=10
    )
    Lesson.objects.create(
        module=module1, lesson_index=1, title="Sync Lesson 1.2", summary="Summary 1.2", duration=15
    )
    module2 = Module.objects.create(
        syllabus=syllabus, module_index=1, title="Sync Module 2", summary="Summary 2"
    )
    Lesson.objects.create(
        module=module2, lesson_index=0, title="Sync Lesson 2.1", summary="Summary 2.1", duration=20
    )
    # Return the prefetched object
    return Syllabus.objects.prefetch_related("modules__lessons").get(pk=syllabus.pk)


@pytest.fixture
def async_client():
    return AsyncClient()

@pytest.fixture
def client():
    return Client()

@pytest.fixture
@pytest.mark.asyncio # Mark specific async fixture
async def logged_in_async_client(async_client, test_user_sync): # Use sync user fixture
    """Logs in a user for the AsyncClient by setting the session cookie manually."""
    user = test_user_sync # Get the sync user
    sync_client = Client() # Use standard sync client to login and get cookie

    # Perform login synchronously
    logged_in = sync_client.login(username=user.username, password="password")

    # Get session cookie from sync client and set it on async client
    cookie = sync_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie:
        async_client.cookies[settings.SESSION_COOKIE_NAME] = cookie.value

    return async_client

@pytest.fixture
def logged_in_client(client, test_user_sync):
    client.login(username=test_user_sync.username, password="password")
    return client


# --- Tests for SyllabusService (Keep async tests for async service methods) ---

@pytest.mark.asyncio
async def test_get_syllabus_by_id_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id)
    result = await syllabus_service.get_syllabus_by_id(syllabus_id)
    assert result is not None; assert result["syllabus_id"] == syllabus_id

@pytest.mark.asyncio
async def test_get_syllabus_by_id_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_syllabus_by_id(non_existent_id)

@pytest.mark.asyncio
async def test_get_module_details_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id); module_index = 0
    result = await syllabus_service.get_module_details(syllabus_id, module_index)
    assert result is not None; assert result["module_index"] == module_index; assert result["title"] == "Module 1"

@pytest.mark.asyncio
async def test_get_module_details_syllabus_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_module_details(non_existent_id, 0)

@pytest.mark.asyncio
async def test_get_module_details_module_not_found(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id); non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_module_details(syllabus_id, non_existent_index)

@pytest.mark.asyncio
async def test_get_lesson_details_success(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id); module_index = 0; lesson_index = 1
    result = await syllabus_service.get_lesson_details(syllabus_id, module_index, lesson_index)
    assert result is not None; assert result["lesson_index"] == lesson_index; assert result["title"] == "Lesson 1.2"

@pytest.mark.asyncio
async def test_get_lesson_details_syllabus_not_found(syllabus_service):
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(non_existent_id, 0, 0)

@pytest.mark.asyncio
async def test_get_lesson_details_module_not_found(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id); non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(syllabus_id, non_existent_index, 0)

@pytest.mark.asyncio
async def test_get_lesson_details_lesson_not_found(syllabus_service, existing_syllabus_async):
    syllabus = await existing_syllabus_async
    syllabus_id = str(syllabus.syllabus_id); module_index = 0; non_existent_index = 99
    with pytest.raises(NotFoundError):
        await syllabus_service.get_lesson_details(syllabus_id, module_index, non_existent_index)

@pytest.mark.asyncio
async def test_get_or_generate_syllabus_existing(syllabus_service, existing_syllabus_async):
    # Await fixture ONCE
    syllabus = await existing_syllabus_async

    # Use sync_to_async to safely access the user in async context
    from asgiref.sync import sync_to_async
    get_user = sync_to_async(lambda s: s.user)
    user = await get_user(syllabus)

    result = await syllabus_service.get_or_generate_syllabus(topic="Existing Topic", level="beginner", user=user)
    assert result is not None; assert result["syllabus_id"] == str(syllabus.syllabus_id)

@pytest.mark.asyncio
@patch("syllabus.services.SyllabusService._format_syllabus_dict", new_callable=AsyncMock)
@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
async def test_get_or_generate_syllabus_generate_success(mock_get_ai, mock_format_dict, syllabus_service, test_user_async):
    user = await test_user_async
    topic = f"Unique Gen Topic {uuid.uuid4()}"; level = "intermediate"; user_id_str = str(user.pk); generated_uid = str(uuid.uuid4())

    # Mock the AI instance
    mock_ai_instance = MagicMock(spec=SyllabusAI)
    mock_get_ai.return_value = mock_ai_instance

    # Create mock syllabus content and state
    generated_syllabus_content = {"topic": topic, "level": level, "modules": [{"title": "Gen Mod"}]}
    mock_final_state = SyllabusState(
        topic=topic, knowledge_level=level, user_id=user_id_str, generated_syllabus=generated_syllabus_content,
        existing_syllabus=None, uid=generated_uid, error_message=None, search_results=[], user_feedback=None,
        syllabus_accepted=False, iteration_count=1, user_entered_topic=topic, is_master=False,
        parent_uid=None, created_at=None, updated_at=None, search_queries=[], error_generating=False
    )

    # Mock the get_or_create_syllabus method
    mock_ai_instance.get_or_create_syllabus = AsyncMock(return_value=mock_final_state)

    # Mock the format_syllabus_dict method to return a formatted result
    formatted_result = {
        "syllabus_id": generated_uid,
        "topic": topic,
        "level": level,
        "user_id": user_id_str,
        "modules": [{"title": "Generated Module 1", "lessons": []}]
    }
    mock_format_dict.return_value = formatted_result

    # Create a patch for the Syllabus.objects.aget method
    with patch("syllabus.services.Syllabus.objects.prefetch_related") as mock_prefetch:
        # Mock the select_related and aget methods in the chain
        mock_select = MagicMock()
        mock_prefetch.return_value = mock_select

        # Create a mock syllabus object
        mock_saved_syllabus = MagicMock(spec=Syllabus)
        mock_saved_syllabus.syllabus_id = generated_uid

        # Set up the aget method to raise DoesNotExist for the first call and return the mock syllabus for the second call
        mock_aget = AsyncMock()
        mock_select.select_related.return_value = mock_aget
        mock_aget.aget.side_effect = [Syllabus.DoesNotExist, mock_saved_syllabus]

        # Call the method under test
        result = await syllabus_service.get_or_generate_syllabus(topic=topic, level=level, user=user)

    # Verify the result
    assert result is not None
    assert result["topic"] == topic
    assert result["user_id"] == user_id_str
    assert result["syllabus_id"] == generated_uid

    # Verify the AI instance was initialized and called correctly
    mock_ai_instance.initialize.assert_called_once_with(topic=topic, knowledge_level=level, user_id=user_id_str)
    mock_ai_instance.get_or_create_syllabus.assert_called_once()

    # Verify the format_syllabus_dict method was called
    mock_format_dict.assert_called_once()

@pytest.mark.asyncio
@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
async def test_get_or_generate_syllabus_generate_fail_no_content(mock_get_ai, syllabus_service, test_user_async):
    user = await test_user_async
    topic = "Fail Topic Content"
    level = "advanced"
    user_id_str = str(user.pk)

    # Mock the AI instance
    mock_ai_instance = MagicMock(spec=SyllabusAI)
    mock_get_ai.return_value = mock_ai_instance

    # Create mock state with no generated syllabus
    mock_final_state = SyllabusState(
        topic=topic, knowledge_level=level, user_id=user_id_str, generated_syllabus=None, existing_syllabus=None,
        uid=None, error_message="AI failed", search_results=[], user_feedback=None, syllabus_accepted=False,
        iteration_count=1, user_entered_topic=topic, is_master=False, parent_uid=None, created_at=None,
        updated_at=None, search_queries=[], error_generating=True
    )
    mock_ai_instance.get_or_create_syllabus = AsyncMock(return_value=mock_final_state)

    # Create a patch for the Syllabus.objects.prefetch_related method
    with patch("syllabus.services.Syllabus.objects.prefetch_related") as mock_prefetch:
        # Set up the chain of mocks
        mock_select = MagicMock()
        mock_prefetch.return_value = mock_select
        mock_select.select_related = MagicMock()
        mock_select.select_related.return_value = MagicMock()

        # Set up the aget method to raise DoesNotExist
        mock_select.select_related.return_value.aget = AsyncMock(side_effect=Syllabus.DoesNotExist)

        # Test that the correct exception is raised
        with pytest.raises(ApplicationError, match="Failed to generate syllabus content"):
            await syllabus_service.get_or_generate_syllabus(topic=topic, level=level, user=user)

        # Verify the aget method was called with the correct arguments
        mock_select.select_related.return_value.aget.assert_called_once_with(topic=topic, level=level, user=user)

@pytest.mark.asyncio
@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
async def test_get_or_generate_syllabus_generate_fail_no_uid(mock_get_ai, syllabus_service, test_user_async):
    user = await test_user_async
    topic = "Fail Topic UID"
    level = "beginner"
    user_id_str = str(user.pk)

    # Mock the AI instance
    mock_ai_instance = MagicMock(spec=SyllabusAI)
    mock_get_ai.return_value = mock_ai_instance

    # Create mock state with generated syllabus but no UID
    generated_syllabus_content = {"topic": topic, "level": level, "modules": []}
    mock_final_state = SyllabusState(
        topic=topic, knowledge_level=level, user_id=user_id_str, generated_syllabus=generated_syllabus_content,
        existing_syllabus=None, uid=None, error_message=None, search_results=[], user_feedback=None,
        syllabus_accepted=False, iteration_count=1, user_entered_topic=topic, is_master=False, parent_uid=None,
        created_at=None, updated_at=None, search_queries=[], error_generating=False
    )
    mock_ai_instance.get_or_create_syllabus = AsyncMock(return_value=mock_final_state)

    # Create a patch for the Syllabus.objects.prefetch_related method
    with patch("syllabus.services.Syllabus.objects.prefetch_related") as mock_prefetch:
        # Set up the chain of mocks
        mock_select = MagicMock()
        mock_prefetch.return_value = mock_select
        mock_select.select_related = MagicMock()
        mock_select.select_related.return_value = MagicMock()

        # Set up the aget method to raise DoesNotExist
        mock_select.select_related.return_value.aget = AsyncMock(side_effect=Syllabus.DoesNotExist)

        # Test that the correct exception is raised
        with pytest.raises(ApplicationError, match="Failed to get ID of generated syllabus"):
            await syllabus_service.get_or_generate_syllabus(topic=topic, level=level, user=user)

        # Verify the aget method was called with the correct arguments
        mock_select.select_related.return_value.aget.assert_called_once_with(topic=topic, level=level, user=user)

@pytest.mark.asyncio
@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
async def test_get_or_generate_syllabus_ai_exception(mock_get_ai, syllabus_service, test_user_async):
    user = await test_user_async
    topic = "AI Exception Topic"
    level = "intermediate"

    # Mock the AI instance
    mock_ai_instance = MagicMock(spec=SyllabusAI)
    mock_get_ai.return_value = mock_ai_instance

    # Set up the AI instance to raise an exception
    mock_ai_instance.get_or_create_syllabus = AsyncMock(side_effect=Exception("AI Network Error"))

    # Create a patch for the Syllabus.objects.prefetch_related method
    with patch("syllabus.services.Syllabus.objects.prefetch_related") as mock_prefetch:
        # Set up the chain of mocks
        mock_select = MagicMock()
        mock_prefetch.return_value = mock_select
        mock_select.select_related = MagicMock()
        mock_select.select_related.return_value = MagicMock()

        # Set up the aget method to raise DoesNotExist
        mock_select.select_related.return_value.aget = AsyncMock(side_effect=Syllabus.DoesNotExist)

        # Test that the correct exception is raised
        with pytest.raises(ApplicationError, match="Failed to generate syllabus: AI Network Error"):
            await syllabus_service.get_or_generate_syllabus(topic=topic, level=level, user=user)

        # Verify the aget method was called with the correct arguments
        mock_select.select_related.return_value.aget.assert_called_once_with(topic=topic, level=level, user=user)


# --- Tests for Views ---

# --- syllabus_landing (Sync View) ---
def test_syllabus_landing_unauthenticated(client):
    url = reverse("syllabus:landing")
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url

def test_syllabus_landing_authenticated(logged_in_client): # Use standard logged_in_client
    url = reverse("syllabus:landing")
    response = logged_in_client.get(url)
    assert response.status_code == 200
    assert "syllabus/landing.html" in [t.name for t in response.templates]
    # Update assertion to match actual content
    assert "Syllabus Generation" in response.content.decode()


# --- syllabus_detail (Sync View) ---
@patch("syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock) # Patch sync method
def test_syllabus_detail_success(mock_get_syllabus_sync, logged_in_client, test_user_sync): # Use sync client and user fixture
    client = logged_in_client # Use sync client fixture
    # Create syllabus synchronously for the test
    user = test_user_sync # Use the sync user fixture directly
    syllabus = Syllabus.objects.create(user=user, topic="Sync Detail Test", level="beginner")
    Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")

    syllabus_id_obj = syllabus.syllabus_id # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)

    # Mock the service call to return formatted data
    formatted_data = {
        "syllabus_id": syllabus_id_str,
        "topic": syllabus.topic,
        "level": syllabus.level,
        "modules": [] # Keep mock simple
    }
    mock_get_syllabus_sync.return_value = formatted_data # Mock the sync method

    url = reverse("syllabus:detail", args=[syllabus_id_str])
    response = client.get(url) # Sync client call

    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)
    assert response.status_code == 200
    assert "syllabus/detail.html" in [t.name for t in response.templates]
    assert formatted_data["topic"] in response.content.decode() # Check mock data in response

# Test unauthenticated access for sync view
def test_syllabus_detail_unauthenticated(client, test_user_sync): # Use sync client and user fixture
    # Create syllabus synchronously
    user = test_user_sync
    syllabus = Syllabus.objects.create(user=user, topic="Sync Detail Unauth Test", level="beginner")
    url = reverse("syllabus:detail", args=[str(syllabus.syllabus_id)])
    response = client.get(url) # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url

@patch("syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock) # Patch sync method
def test_syllabus_detail_not_found(mock_get_syllabus_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    mock_get_syllabus_sync.side_effect = NotFoundError("Not found") # Mock sync method
    url = reverse("syllabus:detail", args=[syllabus_id_str])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 404
    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)

@patch("syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock) # Patch sync method
def test_syllabus_detail_service_error(mock_get_syllabus_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    mock_get_syllabus_sync.side_effect = ApplicationError("Service failed") # Mock sync method
    url = reverse("syllabus:detail", args=[syllabus_id_str])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)


# --- generate_syllabus_view (Async View - Keep async tests) ---
@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_success(mock_generate, logged_in_async_client): # Removed test_user_async
    # user = await test_user_async # Not needed for mock assertion
    topic = "Test Gen Topic"; level = "beginner"; generated_id = str(uuid.uuid4())
    mock_generate.return_value = {"syllabus_id": generated_id}
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:detail", args=[generated_id])
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY) # Use ANY for user

@pytest.mark.asyncio
async def test_generate_syllabus_missing_topic(logged_in_async_client):
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.post(url, {"level": "beginner"})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")

@pytest.mark.asyncio
async def test_generate_syllabus_get_request(logged_in_async_client):
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")

@pytest.mark.asyncio
async def test_generate_syllabus_unauthenticated(async_client):
    url = reverse("syllabus:generate")
    client = async_client # No need to await the fixture itself
    response = await client.post(url, {"topic": "Test", "level": "beginner"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url

@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_service_app_error(mock_generate, logged_in_async_client): # Removed test_user_async
    # user = await test_user_async # Not needed for mock assertion
    topic = "App Error Topic"; level = "expert"
    mock_generate.side_effect = ApplicationError("AI Failed")
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Ensure the awaited user object is passed to the mock
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY) # Use ANY for user

@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_service_other_error(mock_generate, logged_in_async_client): # Removed test_user_async
    # user = await test_user_async # Not needed for mock assertion
    topic = "Other Error Topic"; level = "beginner"
    mock_generate.side_effect = Exception("Unexpected")
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY) # Use ANY for user

@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_missing_id_response(mock_generate, logged_in_async_client): # Removed test_user_async
    # user = await test_user_async # Not needed for mock assertion
    topic = "Missing ID Topic"; level = "intermediate"
    mock_generate.return_value = {"syllabus_id": None} # Simulate missing ID
    url = reverse("syllabus:generate")
    client = await logged_in_async_client # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY) # Use ANY for user


# --- module_detail (Sync View) ---
@patch("syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock) # Patch sync method
def test_module_detail_success(mock_get_module_sync, logged_in_client, test_user_sync): # Use sync client and user fixture
    # Create syllabus and module synchronously
    user = test_user_sync
    syllabus = Syllabus.objects.create(user=user, topic="Sync Module Test", level="beginner")
    module = Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")
    syllabus_id_obj = syllabus.syllabus_id # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0

    # Mock the service call
    mock_module_data = {
        "id": module.id, "syllabus_id": syllabus_id_str, "module_index": module_index,
        "title": module.title, "summary": "Mock Summary", "lessons": [],
        "created_at": timezone.now().isoformat(),
        "updated_at": timezone.now().isoformat()
    }
    mock_get_module_sync.return_value = mock_module_data
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url) # Sync client call

    assert response.status_code == 200
    assert "syllabus/module_detail.html" in [t.name for t in response.templates]
    assert mock_module_data["title"] in response.content.decode() # Check mock data in response
    # Assert sync method called with UUID object
    mock_get_module_sync.assert_called_once_with(syllabus_id_obj, module_index)

def test_module_detail_unauthenticated(client, test_user_sync): # Use sync client and user fixture
    # Create syllabus and module synchronously
    user = test_user_sync
    syllabus = Syllabus.objects.create(user=user, topic="Sync Module Unauth Test", level="beginner")
    module = Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")
    syllabus_id = str(syllabus.syllabus_id); module_index = 0
    url = reverse("syllabus:module_detail", args=[syllabus_id, module_index])
    response = client.get(url) # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url

@patch("syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock) # Patch sync method
def test_module_detail_not_found(mock_get_module_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 99
    mock_get_module_sync.side_effect = NotFoundError("Not found") # Mock sync method
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 404
    # Assert sync method called with UUID object
    mock_get_module_sync.assert_called_once_with(syllabus_id_obj, module_index)

@patch("syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock) # Patch sync method
def test_module_detail_service_error(mock_get_module_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    mock_get_module_sync.side_effect = ApplicationError("Service failed") # Mock sync method
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 302 # Expect redirect to syllabus detail on error
    assert response.url == reverse("syllabus:detail", args=[syllabus_id_str]) # Check redirect URL
    mock_get_module_sync.assert_called_once_with(syllabus_id_obj, module_index) # Assert sync method called


# --- lesson_detail (Sync View) ---
@patch("syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock) # Patch sync method
def test_lesson_detail_success(mock_get_lesson_sync, logged_in_client, test_user_sync): # Use sync client and user fixture
    # Create syllabus, module, and lesson synchronously
    user = test_user_sync
    syllabus = Syllabus.objects.create(user=user, topic="Sync Lesson Test", level="beginner")
    module = Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")
    lesson = Lesson.objects.create(module=module, lesson_index=1, title="Sync Lesson 1.2")
    syllabus_id_obj = syllabus.syllabus_id # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0; lesson_index = 1

    # Mock the service call
    mock_lesson_data = {
        "id": lesson.id, "module_id": module.id, "syllabus_id": syllabus_id_str,
        "lesson_index": lesson_index, "title": lesson.title, "summary": "Mock Summary",
        "duration": 15
    }
    mock_get_lesson_sync.return_value = mock_lesson_data
    url = reverse("syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index])
    client = logged_in_client
    response = client.get(url) # Sync client call

    assert response.status_code == 200
    assert "syllabus/lesson_detail.html" in [t.name for t in response.templates]
    assert mock_lesson_data["title"] in response.content.decode() # Check mock data in response
    # Assert sync method called with UUID object
    mock_get_lesson_sync.assert_called_once_with(syllabus_id_obj, module_index, lesson_index)

def test_lesson_detail_unauthenticated(client, test_user_sync): # Use sync client and user fixture
    # Create syllabus, module, and lesson synchronously
    user = test_user_sync
    syllabus = Syllabus.objects.create(user=user, topic="Sync Lesson Unauth Test", level="beginner")
    module = Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")
    lesson = Lesson.objects.create(module=module, lesson_index=0, title="Sync Lesson 1.1")
    syllabus_id = str(syllabus.syllabus_id); module_index = 0; lesson_index = 0
    url = reverse("syllabus:lesson_detail", args=[syllabus_id, module_index, lesson_index])
    response = client.get(url) # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url

@patch("syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock) # Patch sync method
def test_lesson_detail_not_found(mock_get_lesson_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0; lesson_index = 99
    mock_get_lesson_sync.side_effect = NotFoundError("Not found") # Mock sync method
    url = reverse("syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 404
    mock_get_lesson_sync.assert_called_once_with(syllabus_id_obj, module_index, lesson_index) # Assert sync method called with UUID object

@patch("syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock) # Patch sync method
def test_lesson_detail_service_error(mock_get_lesson_sync, logged_in_client): # Sync test
    syllabus_id_obj = uuid.uuid4() # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0; lesson_index = 0
    mock_get_lesson_sync.side_effect = ApplicationError("Service failed") # Mock sync method
    url = reverse("syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index])
    client = logged_in_client
    response = client.get(url) # Sync client call
    assert response.status_code == 302 # Expect redirect to module detail on error
    assert response.url == reverse("syllabus:module_detail", args=[syllabus_id_str, module_index]) # Check redirect URL
    mock_get_lesson_sync.assert_called_once_with(syllabus_id_obj, module_index, lesson_index) # Assert sync method called with UUID object
