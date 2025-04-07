"""Tests for the synchronous views in the syllabus app."""
# pylint: disable=missing-function-docstring, no-member

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone

from core.constants import DIFFICULTY_BEGINNER  # Import constant
from core.exceptions import ApplicationError, NotFoundError
from core.models import Module, Syllabus, Lesson


# Mark all tests in this module as needing DB access
pytestmark = [pytest.mark.django_db(transaction=True)]


# --- syllabus_landing (Sync View) ---
def test_syllabus_landing_unauthenticated(client):
    url = reverse("syllabus:landing")
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_syllabus_landing_authenticated(
    logged_in_client,
):  # Use standard logged_in_client
    url = reverse("syllabus:landing")
    response = logged_in_client.get(url)
    assert response.status_code == 200
    assert "syllabus/landing.html" in [t.name for t in response.templates]
    # Update assertion to match actual content
    assert "Syllabus Generation" in response.content.decode()


# --- syllabus_detail (Sync View) ---
@patch(
    "syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock
)  # Patch sync method
def test_syllabus_detail_success(
    mock_get_syllabus_sync, logged_in_client, test_user_sync
):  # Use sync client and user fixture
    client = logged_in_client  # Use sync client fixture
    # Create syllabus synchronously for the test
    user = test_user_sync  # Use the sync user fixture directly

    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Detail Test", level=DIFFICULTY_BEGINNER
    )
    Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")

    syllabus_id_obj = syllabus.syllabus_id  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)

    # Mock the service call to return formatted data
    formatted_data = {
        "syllabus_id": syllabus_id_str,
        "topic": syllabus.topic,
        "level": syllabus.level,
        "modules": [],  # Keep mock simple
    }
    mock_get_syllabus_sync.return_value = formatted_data  # Mock the sync method

    url = reverse("syllabus:detail", args=[syllabus_id_str])
    response = client.get(url)  # Sync client call

    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)
    assert response.status_code == 200
    assert "syllabus/detail.html" in [t.name for t in response.templates]
    assert (
        formatted_data["topic"] in response.content.decode()
    )  # Check mock data in response


# Test unauthenticated access for sync view
def test_syllabus_detail_unauthenticated(
    client, test_user_sync
):  # Use sync client and user fixture
    # Create syllabus synchronously

    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Detail Unauth Test", level=DIFFICULTY_BEGINNER
    )
    url = reverse("syllabus:detail", args=[str(syllabus.syllabus_id)])
    response = client.get(url)  # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch(
    "syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock
)  # Patch sync method
def test_syllabus_detail_not_found(
    mock_get_syllabus_sync, logged_in_client
):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    mock_get_syllabus_sync.side_effect = NotFoundError("Not found")  # Mock sync method
    url = reverse("syllabus:detail", args=[syllabus_id_str])
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 404
    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)


@patch(
    "syllabus.views.syllabus_service.get_syllabus_by_id_sync", new_callable=MagicMock
)  # Patch sync method
def test_syllabus_detail_service_error(
    mock_get_syllabus_sync, logged_in_client
):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    mock_get_syllabus_sync.side_effect = ApplicationError(
        "Service failed"
    )  # Mock sync method
    url = reverse("syllabus:detail", args=[syllabus_id_str])
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert sync method called with UUID object
    mock_get_syllabus_sync.assert_called_once_with(syllabus_id_obj)


# --- module_detail (Sync View) ---
@patch(
    "syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_module_detail_success(
    mock_get_module_sync, logged_in_client, test_user_sync
):  # Use sync client and user fixture
    # Create syllabus and module synchronously

    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Module Test", level=DIFFICULTY_BEGINNER
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Mod 1"
    )
    syllabus_id_obj = syllabus.syllabus_id  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0

    # Mock the service call
    mock_module_data = {
        "id": module.id,
        "syllabus_id": syllabus_id_str,
        "module_index": module_index,
        "title": module.title,
        "summary": "Mock Summary",
        "lessons": [],
        "created_at": timezone.now().isoformat(),
        "updated_at": timezone.now().isoformat(),
    }
    mock_get_module_sync.return_value = mock_module_data
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url)  # Sync client call

    assert response.status_code == 200
    assert "syllabus/module_detail.html" in [t.name for t in response.templates]
    assert (
        mock_module_data["title"] in response.content.decode()
    )  # Check mock data in response
    # Assert sync method called with UUID object
    mock_get_module_sync.assert_called_once_with(syllabus_id_obj, module_index)


def test_module_detail_unauthenticated(
    client, test_user_sync
):  # Use sync client and user fixture
    # Create syllabus and module synchronously

    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Module Unauth Test", level=DIFFICULTY_BEGINNER
    )
    Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Mod 1"
    )
    syllabus_id = str(syllabus.syllabus_id)
    module_index = 0
    url = reverse("syllabus:module_detail", args=[syllabus_id, module_index])
    response = client.get(url)  # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch(
    "syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_module_detail_not_found(mock_get_module_sync, logged_in_client):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 99
    mock_get_module_sync.side_effect = NotFoundError("Not found")  # Mock sync method
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 404
    # Assert sync method called with UUID object
    mock_get_module_sync.assert_called_once_with(syllabus_id_obj, module_index)


@patch(
    "syllabus.views.syllabus_service.get_module_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_module_detail_service_error(
    mock_get_module_sync, logged_in_client
):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    mock_get_module_sync.side_effect = ApplicationError(
        "Service failed"
    )  # Mock sync method
    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 302  # Expect redirect to syllabus detail on error
    assert response.url == reverse(
        "syllabus:detail", args=[syllabus_id_str]
    )  # Check redirect URL
    mock_get_module_sync.assert_called_once_with(
        syllabus_id_obj, module_index
    )  # Assert sync method called


# --- lesson_detail (Sync View) ---
@patch(
    "syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_lesson_detail_success(
    mock_get_lesson_sync, logged_in_client, test_user_sync
):  # Use sync client and user fixture
    # Create syllabus, module, and lesson synchronously

    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Lesson Test", level=DIFFICULTY_BEGINNER
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Mod 1"
    )
    lesson = Lesson.objects.create(
        module=module, lesson_index=1, title="Sync Lesson 1.2"
    )
    syllabus_id_obj = syllabus.syllabus_id  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    lesson_index = 1

    # Mock the service call
    mock_lesson_data = {
        "id": lesson.id,
        "module_id": module.id,
        "syllabus_id": syllabus_id_str,
        "lesson_index": lesson_index,
        "title": lesson.title,
        "summary": "Mock Summary",
        "duration": 15,
    }
    mock_get_lesson_sync.return_value = mock_lesson_data
    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    client = logged_in_client
    response = client.get(url)  # Sync client call

    assert response.status_code == 200
    assert "syllabus/lesson_detail.html" in [t.name for t in response.templates]
    assert (
        mock_lesson_data["title"] in response.content.decode()
    )  # Check mock data in response
    # Assert sync method called with UUID object
    mock_get_lesson_sync.assert_called_once_with(
        syllabus_id_obj, module_index, lesson_index
    )


def test_lesson_detail_unauthenticated(
    client, test_user_sync
):  # Use sync client and user fixture
    # Create syllabus, module, and lesson synchronously

    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Lesson Unauth Test", level=DIFFICULTY_BEGINNER
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Mod 1"
    )
    Lesson.objects.create(
        module=module, lesson_index=0, title="Sync Lesson 1.1"
    )
    syllabus_id = str(syllabus.syllabus_id)
    module_index = 0
    lesson_index = 0
    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id, module_index, lesson_index]
    )
    response = client.get(url)  # Sync client call
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@patch(
    "syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_lesson_detail_not_found(mock_get_lesson_sync, logged_in_client):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    lesson_index = 99
    mock_get_lesson_sync.side_effect = NotFoundError("Not found")  # Mock sync method
    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 404
    mock_get_lesson_sync.assert_called_once_with(
        syllabus_id_obj, module_index, lesson_index
    )  # Assert sync method called with UUID object


@patch(
    "syllabus.views.syllabus_service.get_lesson_details_sync", new_callable=MagicMock
)  # Patch sync method
def test_lesson_detail_service_error(
    mock_get_lesson_sync, logged_in_client
):  # Sync test
    syllabus_id_obj = uuid.uuid4()  # Keep as UUID object
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    lesson_index = 0
    mock_get_lesson_sync.side_effect = ApplicationError(
        "Service failed"
    )  # Mock sync method
    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    client = logged_in_client
    response = client.get(url)  # Sync client call
    assert response.status_code == 302  # Expect redirect to module detail on error
    assert response.url == reverse(
        "syllabus:module_detail", args=[syllabus_id_str, module_index]
    )  # Check redirect URL
    mock_get_lesson_sync.assert_called_once_with(
        syllabus_id_obj, module_index, lesson_index
    )  # Assert sync method called with UUID object
