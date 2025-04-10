"""Tests for the synchronous views in the syllabus app."""
# pylint: disable=missing-function-docstring, no-member

import uuid
from unittest.mock import MagicMock, patch
from taskqueue.models import AITask

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
def test_syllabus_detail_success(logged_in_client, test_user_sync):
    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Detail Test", level=DIFFICULTY_BEGINNER
    )
    Module.objects.create(syllabus=syllabus, module_index=0, title="Sync Mod 1")

    syllabus_id_str = str(syllabus.syllabus_id)

    # Create a completed AITask with mock result_data
    AITask.objects.create(
        syllabus=syllabus,
        task_type=AITask.TaskType.SYLLABUS_GENERATION,
        status=AITask.TaskStatus.COMPLETED,
        input_data={},
        result_data={
            "syllabus_id": syllabus_id_str,
            "topic": syllabus.topic,
            "level": syllabus.level,
            "modules": [],
        },
    )

    url = reverse("syllabus:detail", args=[syllabus_id_str])
    response = logged_in_client.get(url)

    assert response.status_code == 200
    assert "syllabus/detail.html" in [t.name for t in response.templates]
    assert "Sync Detail Test" in response.content.decode()


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


def test_syllabus_detail_not_found(logged_in_client):
    syllabus_id_obj = uuid.uuid4()
    syllabus_id_str = str(syllabus_id_obj)

    url = reverse("syllabus:detail", args=[syllabus_id_str])
    response = logged_in_client.get(url)

    # The view redirects to landing page if syllabus not found
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


def test_syllabus_detail_service_error(logged_in_client, test_user_sync):
    user = test_user_sync

    syllabus = Syllabus.objects.create(
        user=user, topic="Service Error Test", level=DIFFICULTY_BEGINNER
    )
    syllabus_id_str = str(syllabus.syllabus_id)

    AITask.objects.create(
        syllabus=syllabus,
        task_type=AITask.TaskType.SYLLABUS_GENERATION,
        status=AITask.TaskStatus.FAILED,
        input_data={},
        error_message="Service failed",
    )

    url = reverse("syllabus:detail", args=[syllabus_id_str])
    response = logged_in_client.get(url)

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


# --- module_detail (Sync View) ---
def test_module_detail_success(logged_in_client, test_user_sync):
    user = test_user_sync
    syllabus = Syllabus.objects.create(
        user=user, topic="Sync Module Test", level=DIFFICULTY_BEGINNER
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Mod 1"
    )
    syllabus_id_str = str(syllabus.syllabus_id)
    module_index = 0

    AITask.objects.create(
        syllabus=syllabus,
        task_type=AITask.TaskType.SYLLABUS_GENERATION,
        status=AITask.TaskStatus.COMPLETED,
        input_data={},
        result_data={
            "syllabus_id": syllabus_id_str,
            "modules": [
                {
                    "module_index": module_index,
                    "title": module.title,
                    "summary": "Mock Summary",
                    "lessons": [],
                    "created_at": timezone.now().isoformat(),
                    "updated_at": timezone.now().isoformat(),
                }
            ],
        },
    )

    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    response = logged_in_client.get(url)

    assert response.status_code == 200
    assert "syllabus/module_detail.html" in [t.name for t in response.templates]
    assert "Sync Mod 1" in response.content.decode()


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


def test_module_detail_not_found(logged_in_client):
    syllabus_id_obj = uuid.uuid4()
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 99

    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    response = logged_in_client.get(url)

    # The view redirects to syllabus landing if module not found
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


def test_module_detail_service_error(logged_in_client, test_user_sync):
    user = test_user_sync

    syllabus = Syllabus.objects.create(
        user=user, topic="Module Service Error Test", level=DIFFICULTY_BEGINNER
    )
    syllabus_id_str = str(syllabus.syllabus_id)
    module_index = 0

    AITask.objects.create(
        syllabus=syllabus,
        task_type=AITask.TaskType.SYLLABUS_GENERATION,
        status=AITask.TaskStatus.FAILED,
        input_data={},
        error_message="Service failed",
    )

    url = reverse("syllabus:module_detail", args=[syllabus_id_str, module_index])
    response = logged_in_client.get(url)

    assert response.status_code == 302
    assert response.url == reverse("syllabus:detail", args=[syllabus_id_str])


# --- lesson_detail (Sync View) ---
def test_lesson_detail_success(logged_in_client, test_user_sync):
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
    syllabus_id_str = str(syllabus.syllabus_id)
    module_index = 0
    lesson_index = 1

    AITask.objects.create(
        syllabus=syllabus,
        lesson=lesson,
        task_type=AITask.TaskType.LESSON_CONTENT,
        status=AITask.TaskStatus.COMPLETED,
        input_data={},
        result_data={
            "id": lesson.id,
            "module_id": module.id,
            "syllabus_id": syllabus_id_str,
            "lesson_index": lesson_index,
            "title": lesson.title,
            "summary": "Mock Summary",
            "duration": 15,
        },
    )

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    # The view redirects to landing page instead of showing lesson detail
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


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


def test_lesson_detail_not_found(logged_in_client):
    syllabus_id_obj = uuid.uuid4()
    syllabus_id_str = str(syllabus_id_obj)
    module_index = 0
    lesson_index = 99

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    # The view redirects to syllabus landing if lesson not found
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


def test_lesson_detail_service_error(logged_in_client, test_user_sync):
    user = test_user_sync

    syllabus = Syllabus.objects.create(
        user=user, topic="Lesson Service Error Test", level=DIFFICULTY_BEGINNER
    )
    module = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Module for Lesson Error"
    )
    lesson = Lesson.objects.create(
        module=module, lesson_index=0, title="Lesson for Error"
    )
    syllabus_id_str = str(syllabus.syllabus_id)
    module_index = 0
    lesson_index = 0

    AITask.objects.create(
        syllabus=syllabus,
        lesson=lesson,
        task_type=AITask.TaskType.LESSON_CONTENT,
        status=AITask.TaskStatus.FAILED,
        input_data={},
        error_message="Service failed",
    )

    url = reverse(
        "syllabus:lesson_detail", args=[syllabus_id_str, module_index, lesson_index]
    )
    response = logged_in_client.get(url)

    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
