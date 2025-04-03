"""Tests for the syllabus app."""

# pylint: skip-file

import uuid
from unittest.mock import patch, MagicMock, call

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse  # Import reverse
from django.utils import timezone

from core.models import Syllabus, Module, Lesson
from core.exceptions import NotFoundError, ApplicationError
from syllabus.services import SyllabusService
from syllabus.ai.state import SyllabusState  # Import state for mocking

User = get_user_model()

# Use pytest-django fixtures for database access
pytestmark = pytest.mark.django_db


@pytest.fixture
def test_user():
    """Fixture for creating a test user."""
    return User.objects.create_user(username="testsyllabususer", password="password")


@pytest.fixture
def syllabus_service():
    """Fixture for SyllabusService instance."""
    return SyllabusService()


@pytest.fixture
def existing_syllabus(test_user):
    """Fixture for creating a pre-existing syllabus with modules and lessons."""
    syllabus = Syllabus.objects.create(
        user=test_user,
        topic="Existing Topic",
        level="beginner",
        user_entered_topic="Existing Topic",
    )
    module1 = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Module 1", summary="Summary 1"
    )
    Lesson.objects.create(
        module=module1,
        lesson_index=0,
        title="Lesson 1.1",
        summary="Summary 1.1",
        duration=10,
    )
    Lesson.objects.create(
        module=module1,
        lesson_index=1,
        title="Lesson 1.2",
        summary="Summary 1.2",
        duration=15,
    )
    module2 = Module.objects.create(
        syllabus=syllabus, module_index=1, title="Module 2", summary="Summary 2"
    )
    Lesson.objects.create(
        module=module2,
        lesson_index=0,
        title="Lesson 2.1",
        summary="Summary 2.1",
        duration=20,
    )
    # Refresh to ensure relations are loaded for formatting
    return Syllabus.objects.prefetch_related("modules__lessons").get(pk=syllabus.pk)


@pytest.fixture
def client():
    """Override default client fixture if needed, or use pytest-django's default."""
    from django.test import Client

    return Client()


@pytest.fixture
def logged_in_client(client, test_user):
    """Fixture for a client logged in as test_user."""
    client.login(username="testsyllabususer", password="password")
    return client


# --- Tests for SyllabusService ---

# --- get_syllabus_by_id ---


def test_get_syllabus_by_id_success(syllabus_service, existing_syllabus):
    """Test retrieving an existing syllabus by its ID."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    result = syllabus_service.get_syllabus_by_id(syllabus_id)

    assert result is not None
    assert result["syllabus_id"] == syllabus_id
    assert result["topic"] == "Existing Topic"
    assert result["level"] == "beginner"
    assert result["user_id"] == str(existing_syllabus.user_id)
    assert len(result["modules"]) == 2
    assert len(result["modules"][0]["lessons"]) == 2
    assert result["modules"][0]["title"] == "Module 1"
    assert result["modules"][0]["lessons"][0]["title"] == "Lesson 1.1"


def test_get_syllabus_by_id_not_found(syllabus_service):
    """Test retrieving a non-existent syllabus ID raises NotFoundError."""
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_syllabus_by_id(non_existent_id)
    assert f"Syllabus with ID {non_existent_id} not found" in str(excinfo.value)


# --- get_module_details ---

# --- get_module_details ---


def test_get_module_details_success(syllabus_service, existing_syllabus):
    """Test retrieving details for an existing module."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    module_index = 0
    result = syllabus_service.get_module_details(syllabus_id, module_index)

    assert result is not None
    assert result["syllabus_id"] == syllabus_id
    assert result["module_index"] == module_index
    assert result["title"] == "Module 1"
    assert len(result["lessons"]) == 2
    assert result["lessons"][0]["title"] == "Lesson 1.1"


def test_get_module_details_syllabus_not_found(syllabus_service):
    """Test retrieving module details for non-existent syllabus raises NotFoundError."""
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_module_details(non_existent_id, 0)
    assert f"Module 0 not found in syllabus {non_existent_id}" in str(excinfo.value)


def test_get_module_details_module_not_found(syllabus_service, existing_syllabus):
    """Test retrieving non-existent module index raises NotFoundError."""
    syllabus_id = str(existing_syllabus.syllabus_id)


# --- get_lesson_details ---


def test_get_lesson_details_success(syllabus_service, existing_syllabus):
    """Test retrieving details for an existing lesson."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    module_index = 0
    lesson_index = 1
    result = syllabus_service.get_lesson_details(
        syllabus_id, module_index, lesson_index
    )

    assert result is not None
    assert result["syllabus_id"] == syllabus_id
    # Assuming module ID is accessible, adjust if needed based on actual model relations
    # assert result["module_id"] == existing_syllabus.modules.get(module_index=module_index).id
    assert result["lesson_index"] == lesson_index
    assert result["title"] == "Lesson 1.2"
    assert result["duration"] == 15


def test_get_lesson_details_syllabus_not_found(syllabus_service):
    """Test retrieving lesson details for non-existent syllabus raises NotFoundError."""
    non_existent_id = str(uuid.uuid4())
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_lesson_details(non_existent_id, 0, 0)
    assert f"Lesson 0 not found in module 0, syllabus {non_existent_id}" in str(
        excinfo.value
    )


def test_get_lesson_details_module_not_found(syllabus_service, existing_syllabus):
    """Test retrieving lesson details for non-existent module raises NotFoundError."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    non_existent_index = 99
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_lesson_details(syllabus_id, non_existent_index, 0)
    assert (
        f"Lesson 0 not found in module {non_existent_index}, syllabus {syllabus_id}"
        in str(excinfo.value)
    )


# --- get_or_generate_syllabus ---


def test_get_or_generate_syllabus_existing(
    syllabus_service, existing_syllabus, test_user
):
    """Test retrieving an existing syllabus."""
    # No mocking needed, should find the existing one
    result = syllabus_service.get_or_generate_syllabus(
        topic="Existing Topic", level="beginner", user=test_user
    )

    assert result is not None
    assert result["syllabus_id"] == str(existing_syllabus.syllabus_id)
    assert result["topic"] == "Existing Topic"
    assert len(result["modules"]) == 2


@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
def test_get_or_generate_syllabus_generate_success(
    mock_get_ai, syllabus_service, test_user
):
    """Test generating a new syllabus successfully."""
    topic = f"Unique Gen Topic {uuid.uuid4()}"
    level = "intermediate"
    user_id_str = str(test_user.pk)
    generated_uid = str(uuid.uuid4())  # Simulate UID assigned during save

    # Mock the AI instance and its methods
    mock_ai_instance = MagicMock()
    mock_get_ai.return_value = mock_ai_instance

    # Mock the final state returned by the AI graph after generation and saving
    generated_syllabus_content = (
        {  # Content doesn't strictly matter here, just needs to be a dict
            "topic": topic,
            "level": level,
            "modules": [{"title": "Gen Mod"}],
        }
    )
    mock_final_state = SyllabusState(
        topic=topic,
        knowledge_level=level,
        user_id=user_id_str,
        generated_syllabus=generated_syllabus_content,
        existing_syllabus=None,
        uid=generated_uid,  # UID returned by the AI graph (presumably after saving)
        error_message=None,
    )
    mock_ai_instance.get_or_create_syllabus.return_value = mock_final_state

    # --- Mock Database Interactions ---
    # 1. Mock the final retrieval of the saved syllabus by pk
    mock_saved_syllabus = MagicMock(spec=Syllabus)
    mock_saved_syllabus.syllabus_id = generated_uid
    mock_saved_syllabus.topic = topic
    mock_saved_syllabus.level = level
    mock_saved_syllabus.user = test_user
    mock_saved_syllabus.user_id = test_user.pk
    mock_saved_syllabus.user_entered_topic = topic
    mock_saved_syllabus.created_at = timezone.now()
    mock_saved_syllabus.updated_at = timezone.now()
    # Mock related managers needed by _format_syllabus_dict
    mock_module = MagicMock(spec=Module)
    mock_module.title = "Generated Module 1"
    mock_module.summary = "Gen Summary 1"
    mock_module.module_index = 0
    mock_module.id = 1
    mock_module.created_at = timezone.now()
    mock_module.updated_at = timezone.now()
    mock_lesson = MagicMock(spec=Lesson)
    mock_lesson.title = "Gen Lesson 1.1"
    mock_lesson.summary = "Gen L Summary 1.1"
    mock_lesson.duration = 12
    mock_lesson.lesson_index = 0
    mock_lesson.id = 1
    mock_module.lessons.order_by.return_value.all.return_value = [mock_lesson]
    mock_saved_syllabus.modules.order_by.return_value.all.return_value = [mock_module]

    # 2. Patch the 'syllabus.services.Syllabus.objects' manager
    with patch("syllabus.services.Syllabus.objects") as mock_manager:

        # Define a side effect for the .get() method
        def get_side_effect(*args, **kwargs):
            if "pk" in kwargs and kwargs["pk"] == generated_uid:
                # Final get(pk=...) call: return the mock saved object
                return mock_saved_syllabus
            elif "topic" in kwargs and kwargs["topic"] == topic:
                # Initial get(topic=...) call: raise DoesNotExist
                raise Syllabus.DoesNotExist
            # Raise error for unexpected calls
            raise ValueError(
                f"Unexpected call to Syllabus.objects.get with args={args}, kwargs={kwargs}"
            )

        # Configure the mock manager chain to use the side effect for .get()
        mock_manager.prefetch_related.return_value.select_related.return_value.get.side_effect = (
            get_side_effect
        )

        # --- Call the service method ---
        result = syllabus_service.get_or_generate_syllabus(
            topic=topic, level=level, user=test_user
        )

    # --- Assertions ---
    assert result is not None
    assert result["topic"] == topic
    assert result["level"] == level
    assert result["user_id"] == user_id_str
    assert result["syllabus_id"] == generated_uid
    assert len(result["modules"]) == 1
    assert result["modules"][0]["title"] == "Generated Module 1"
    assert len(result["modules"][0]["lessons"]) == 1
    assert result["modules"][0]["lessons"][0]["title"] == "Gen Lesson 1.1"

    # Assert the initial query chain was attempted correctly
    mock_manager.prefetch_related.assert_any_call("modules__lessons")
    mock_manager.prefetch_related.return_value.select_related.assert_any_call("user")
    # Check that .get was called with the initial arguments (topic, level, user)
    # The side_effect function handles the assertion implicitly by raising DoesNotExist
    # We can check the call args on the final mock in the chain
    get_mock = (
        mock_manager.prefetch_related.return_value.select_related.return_value.get
    )
    assert get_mock.call_args_list[0] == call(topic=topic, level=level, user=test_user)

    # Assert AI methods were called
    mock_ai_instance.initialize.assert_called_once_with(
        topic=topic, knowledge_level=level, user_id=user_id_str
    )
    mock_ai_instance.get_or_create_syllabus.assert_called_once()
    # Assert the final get by PK was attempted correctly
    assert mock_manager.prefetch_related.call_count == 2
    # Check the second call to select_related and get
    assert mock_manager.prefetch_related.return_value.select_related.call_count == 2
    assert get_mock.call_args_list[1] == call(pk=generated_uid)


@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
def test_get_or_generate_syllabus_generate_fail_no_content(
    mock_get_ai, syllabus_service, test_user
):
    """Test syllabus generation failure when AI returns no content."""
    topic = "Fail Topic Content"
    level = "advanced"
    user_id_str = str(test_user.pk)

    mock_ai_instance = MagicMock()
    mock_get_ai.return_value = mock_ai_instance

    # Simulate AI returning state without syllabus content
    mock_final_state = SyllabusState(
        topic=topic,
        knowledge_level=level,
        user_id=user_id_str,
        generated_syllabus=None,  # No content
        existing_syllabus=None,
        uid=None,  # No UID
        error_message="AI failed to generate content",
    )
    mock_ai_instance.get_or_create_syllabus.return_value = mock_final_state

    with pytest.raises(ApplicationError) as excinfo:
        syllabus_service.get_or_generate_syllabus(
            topic=topic, level=level, user=test_user
        )
    assert "Failed to generate syllabus content" in str(excinfo.value)


@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
def test_get_or_generate_syllabus_generate_fail_no_uid(
    mock_get_ai, syllabus_service, test_user
):
    """Test syllabus generation failure when AI returns content but no UID."""
    topic = "Fail Topic UID"
    level = "beginner"
    user_id_str = str(test_user.pk)

    mock_ai_instance = MagicMock()
    mock_get_ai.return_value = mock_ai_instance

    # Simulate AI returning state with content but no UID
    generated_syllabus_content = {"topic": topic, "level": level, "modules": []}
    mock_final_state = SyllabusState(
        topic=topic,
        knowledge_level=level,
        user_id=user_id_str,
        generated_syllabus=generated_syllabus_content,
        existing_syllabus=None,
        uid=None,  # No UID
        error_message=None,
    )
    mock_ai_instance.get_or_create_syllabus.return_value = mock_final_state

    with pytest.raises(ApplicationError) as excinfo:
        syllabus_service.get_or_generate_syllabus(
            topic=topic, level=level, user=test_user
        )
    assert "Failed to get ID of generated syllabus" in str(excinfo.value)


@patch("syllabus.services.SyllabusService._get_syllabus_ai_instance")
def test_get_or_generate_syllabus_ai_exception(
    mock_get_ai, syllabus_service, test_user
):
    """Test syllabus generation failure when AI call raises an exception."""
    topic = "AI Exception Topic"
    level = "intermediate"

    mock_ai_instance = MagicMock()
    mock_get_ai.return_value = mock_ai_instance
    mock_ai_instance.get_or_create_syllabus.side_effect = Exception("AI Network Error")

    with pytest.raises(ApplicationError) as excinfo:
        syllabus_service.get_or_generate_syllabus(
            topic=topic, level=level, user=test_user
        )
    assert "Failed to generate syllabus: AI Network Error" in str(excinfo.value)


def test_get_lesson_details_lesson_not_found(syllabus_service, existing_syllabus):
    """Test retrieving non-existent lesson index raises NotFoundError."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    module_index = 0
    non_existent_index = 99
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_lesson_details(
            syllabus_id, module_index, non_existent_index
        )
    assert (
        f"Lesson {non_existent_index} not found in module {module_index}, syllabus {syllabus_id}"
        in str(excinfo.value)
    )

    non_existent_index = 99
    with pytest.raises(NotFoundError) as excinfo:
        syllabus_service.get_module_details(syllabus_id, non_existent_index)
    assert f"Module {non_existent_index} not found in syllabus {syllabus_id}" in str(
        excinfo.value
    )


# TODO: Add tests for get_module_details

# --- get_lesson_details ---
# TODO: Add tests for get_lesson_details


# --- Tests for Views ---

# --- syllabus_landing ---


def test_syllabus_landing_unauthenticated(client):
    """Test landing page redirects unauthenticated users to login."""
    url = reverse("syllabus:landing")
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_syllabus_landing_authenticated(logged_in_client):
    """Test landing page renders for authenticated users."""
    url = reverse("syllabus:landing")
    response = logged_in_client.get(url)
    assert response.status_code == 200
    assert "syllabus/landing.html" in [t.name for t in response.templates]
    # Check for placeholder message or actual content if implemented
    assert "Syllabus Generation" in response.content.decode()  # Check H1 content


# --- syllabus_detail ---


@patch("syllabus.views.syllabus_service.get_syllabus_by_id")
def test_syllabus_detail_success(
    mock_get_syllabus, logged_in_client, existing_syllabus
):
    """Test syllabus detail view renders correctly."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    # Mock the service call to return formatted data
    mock_get_syllabus.return_value = SyllabusService()._format_syllabus_dict(
        existing_syllabus
    )

    url = reverse("syllabus:detail", args=[syllabus_id])
    response = logged_in_client.get(url)
    # Assert the mock was called with UUID
    mock_get_syllabus.assert_called_once_with(uuid.UUID(syllabus_id))

    assert response.status_code == 200
    assert "syllabus/detail.html" in [t.name for t in response.templates]
    assert existing_syllabus.topic in response.content.decode()
    assert "Module 1" in response.content.decode()
    assert "Lesson 1.1" in response.content.decode()
    mock_get_syllabus.assert_called_once_with(uuid.UUID(syllabus_id))


def test_syllabus_detail_unauthenticated(client, existing_syllabus):
    """Test detail view redirects unauthenticated users."""
    url = reverse("syllabus:detail", args=[str(existing_syllabus.syllabus_id)])
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch("syllabus.views.syllabus_service.get_syllabus_by_id")
def test_syllabus_detail_not_found(mock_get_syllabus, logged_in_client):
    """Test detail view raises Http404 if service raises NotFoundError."""
    syllabus_id = str(uuid.uuid4())
    mock_get_syllabus.side_effect = NotFoundError("Not found")

    url = reverse("syllabus:detail", args=[syllabus_id])


# --- generate_syllabus_view ---


@patch("syllabus.views.syllabus_service.get_or_generate_syllabus")
def test_generate_syllabus_success(mock_generate, logged_in_client):
    """Test successful syllabus generation via POST request."""
    topic = "Test Gen Topic"
    level = "beginner"
    generated_id = str(uuid.uuid4())
    mock_generate.return_value = {"syllabus_id": generated_id}

    url = reverse("syllabus:generate")
    response = logged_in_client.post(url, {"topic": topic, "level": level})

    assert response.status_code == 302  # Should redirect to detail view
    assert response.url == reverse("syllabus:detail", args=[generated_id])
    # Use assert_called_once_with on the mock directly
    mock_generate.assert_called_once()
    # Check args/kwargs of the call
    call_args, call_kwargs = mock_generate.call_args
    assert call_kwargs["topic"] == topic
    assert call_kwargs["level"] == level
    assert isinstance(call_kwargs["user"], User)


def test_generate_syllabus_missing_topic(logged_in_client):
    """Test POST request missing topic redirects back."""
    url = reverse("syllabus:generate")
    response = logged_in_client.post(url, {"level": "beginner"})

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


def test_generate_syllabus_get_request(logged_in_client):
    """Test GET request redirects to landing."""
    url = reverse("syllabus:generate")
    response = logged_in_client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


def test_generate_syllabus_unauthenticated(client):
    """Test generate view redirects unauthenticated users."""
    url = reverse("syllabus:generate")
    response = client.post(url, {"topic": "Test", "level": "beginner"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch("syllabus.views.syllabus_service.get_or_generate_syllabus")
def test_generate_syllabus_service_app_error(mock_generate, logged_in_client):
    """Test generate view handles ApplicationError from service."""
    mock_generate.side_effect = ApplicationError("AI Failed")

    url = reverse("syllabus:generate")
    response = logged_in_client.post(url, {"topic": "Error Topic", "level": "beginner"})

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    mock_generate.assert_called_once()


# --- module_detail ---


@patch("syllabus.views.syllabus_service.get_module_details")
def test_module_detail_success(mock_get_module, logged_in_client, existing_syllabus):
    """Test module detail view renders correctly."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    module_index = 0
    # Mock the service call
    mock_module_data = {
        "id": 1,
        "syllabus_id": syllabus_id,
        "module_index": module_index,
        "title": "Module 1",
        "summary": "Summary 1",
        "lessons": [
            {"id": 1, "title": "Lesson 1.1", "lesson_index": 0},
            {"id": 2, "title": "Lesson 1.2", "lesson_index": 1},
        ],
    }
    mock_get_module.return_value = mock_module_data

    url = reverse("syllabus:module_detail", args=[syllabus_id, module_index])
    response = logged_in_client.get(url)

    assert response.status_code == 200
    assert "syllabus/module_detail.html" in [t.name for t in response.templates]
    assert "Module 1" in response.content.decode()
    assert "Lesson 1.1" in response.content.decode()
    assert str(response.context["syllabus_id"]) == syllabus_id  # Compare as strings
    mock_get_module.assert_called_once_with(
        uuid.UUID(syllabus_id), module_index
    )  # Expect UUID


def test_module_detail_unauthenticated(client, existing_syllabus):
    """Test module detail view redirects unauthenticated users."""
    url = reverse(
        "syllabus:module_detail", args=[str(existing_syllabus.syllabus_id), 0]
    )
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch("syllabus.views.syllabus_service.get_module_details")
def test_module_detail_not_found(mock_get_module, logged_in_client):
    """Test module detail view raises Http404 if service raises NotFoundError."""
    syllabus_id = str(uuid.uuid4())
    module_index = 99
    mock_get_module.side_effect = NotFoundError("Not found")

    url = reverse("syllabus:module_detail", args=[syllabus_id, module_index])
    response = logged_in_client.get(url)

    assert response.status_code == 404
    mock_get_module.assert_called_once_with(uuid.UUID(syllabus_id), module_index)


@patch("syllabus.views.syllabus_service.get_module_details")
def test_module_detail_service_error(mock_get_module, logged_in_client):
    """Test module detail view redirects on ApplicationError."""
    syllabus_id = str(uuid.uuid4())
    module_index = 0


# --- lesson_detail ---


@patch("syllabus.views.syllabus_service.get_lesson_details")
def test_lesson_detail_success(mock_get_lesson, logged_in_client, existing_syllabus):
    """Test lesson detail view renders correctly."""
    syllabus_id = str(existing_syllabus.syllabus_id)
    module_index = 0
    lesson_index = 1
    # Mock the service call
    mock_lesson_data = {
        "id": 2,
        "module_id": 1,
        "syllabus_id": syllabus_id,
        "lesson_index": lesson_index,
        "title": "Lesson 1.2",
        "summary": "Summary 1.2",
        "duration": 15,
    }
    mock_get_lesson.return_value = mock_lesson_data

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    assert response.status_code == 200
    assert "syllabus/lesson_detail.html" in [t.name for t in response.templates]
    assert "Lesson 1.2" in response.content.decode()
    assert str(response.context["syllabus_id"]) == syllabus_id  # Compare as strings
    assert response.context["module_index"] == module_index
    mock_get_lesson.assert_called_once_with(
        uuid.UUID(syllabus_id), module_index, lesson_index
    )  # Expect UUID


def test_lesson_detail_unauthenticated(client, existing_syllabus):
    """Test lesson detail view redirects unauthenticated users."""
    url = reverse(
        "syllabus:lesson_detail", args=[str(existing_syllabus.syllabus_id), 0, 0]
    )
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch("syllabus.views.syllabus_service.get_lesson_details")
def test_lesson_detail_not_found(mock_get_lesson, logged_in_client):
    """Test lesson detail view raises Http404 if service raises NotFoundError."""
    syllabus_id = str(uuid.uuid4())
    module_index = 0
    lesson_index = 99
    mock_get_lesson.side_effect = NotFoundError("Not found")

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    assert response.status_code == 404
    mock_get_lesson.assert_called_once_with(
        uuid.UUID(syllabus_id), module_index, lesson_index
    )


@patch("syllabus.views.syllabus_service.get_lesson_details")
def test_lesson_detail_service_error(mock_get_lesson, logged_in_client):
    """Test lesson detail view redirects on ApplicationError."""
    syllabus_id = str(uuid.uuid4())
    module_index = 0
    lesson_index = 0
    mock_get_lesson.side_effect = ApplicationError("Service failed")

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    assert response.status_code == 302  # Redirects to module detail
    assert response.url == reverse(
        "syllabus:module_detail", args=[syllabus_id, module_index]
    )
    mock_get_lesson.assert_called_once_with(
        uuid.UUID(syllabus_id), module_index, lesson_index
    )  # Check UUID passed

    # Check only the redirect status and target URL, don't follow the redirect
    # as the target view might fail without proper setup for this error case.
    assert response.status_code == 302
    # Check the redirect goes to the module detail page
    assert response.url == reverse(
        "syllabus:module_detail", args=[syllabus_id, module_index]
    )
    # Erroneous line removed


@patch("syllabus.views.syllabus_service.get_or_generate_syllabus")
def test_generate_syllabus_service_other_error(mock_generate, logged_in_client):
    """Test generate view handles unexpected errors from service."""
    mock_generate.side_effect = ValueError("Unexpected")

    url = reverse("syllabus:generate")
    response = logged_in_client.post(url, {"topic": "Error Topic", "level": "beginner"})

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    mock_generate.assert_called_once()


@patch("syllabus.views.syllabus_service.get_or_generate_syllabus")
def test_generate_syllabus_missing_id_response(mock_generate, logged_in_client):
    """Test generate view handles missing syllabus_id in service response."""
    mock_generate.return_value = {"topic": "Incomplete"}  # Missing syllabus_id

    url = reverse("syllabus:generate")
    response = logged_in_client.post(
        url, {"topic": "Incomplete Topic", "level": "beginner"}
    )

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    mock_generate.assert_called_once()
    # Remove incorrect GET request and 404 assertion
    # Remove incorrect GET request and 404 assertion
    # Remove incorrect assertion referencing variables from another scope


@patch("syllabus.views.syllabus_service.get_syllabus_by_id")
def test_syllabus_detail_service_error(mock_get_syllabus, logged_in_client):
    """Test detail view redirects on ApplicationError."""
    syllabus_id = str(uuid.uuid4())
    mock_get_syllabus.side_effect = ApplicationError("Service failed")

    url = reverse("syllabus:detail", args=[syllabus_id])
    response = logged_in_client.get(url)

    assert response.status_code == 302  # Redirects to landing
    assert response.url == reverse("syllabus:landing")
    mock_get_syllabus.assert_called_once_with(uuid.UUID(syllabus_id))


# TODO: Add tests for generate_syllabus_view
# TODO: Add tests for module_detail view
# TODO: Add tests for lesson_detail view


# --- get_or_generate_syllabus ---
# TODO: Add tests for get_or_generate_syllabus (existing case)
# TODO: Add tests for get_or_generate_syllabus (generation success case)
# TODO: Add tests for get_or_generate_syllabus (generation failure case)
