"""Tests for onboarding syllabus generation and polling views"""

# pylint: disable=redefined-outer-name, unused-argument, no-member

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Syllabus

User = get_user_model()


@pytest.fixture(autouse=True)
def cleanup_patches():
    """Fixture to clean up any patches that might have leaked."""
    yield
    patch.stopall()


@pytest.mark.django_db
def test_generating_syllabus_view_owner_access(logged_in_standard_client):
    """Test that the owner can access the generating syllabus page."""
    user = User.objects.get(username="testskipuser")
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Test Gen Topic",
        level="Beginner",
        status=Syllabus.StatusChoices.GENERATING,
    )

    url = reverse(
        "onboarding:generating_syllabus", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 200
    assert "onboarding/generating_syllabus.html" in [t.name for t in response.templates]
    assert response.context["syllabus"] == syllabus
    assert "poll_url" in response.context


@pytest.mark.django_db
def test_generating_syllabus_view_non_owner_redirects(logged_in_standard_client):
    """Test that a non-owner is redirected from the generating page."""
    owner_user = User.objects.create_user(username="owner", password="pw")
    syllabus = Syllabus.objects.create(
        user=owner_user,
        topic="Owner Topic",
        level="Beginner",
        status=Syllabus.StatusChoices.GENERATING,
    )

    url = reverse(
        "onboarding:generating_syllabus", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 302
    assert response.url == reverse("dashboard")


@pytest.mark.django_db
def test_poll_syllabus_status_view_success(logged_in_standard_client):
    """Test successful polling of syllabus status by the owner."""
    user = User.objects.get(username="testskipuser")
    syllabus_status = Syllabus.StatusChoices.GENERATING
    syllabus = Syllabus.objects.create(
        user=user, topic="Test Poll Topic", level="Beginner", status=syllabus_status
    )

    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status


@pytest.mark.django_db
def test_poll_syllabus_status_view_completed(logged_in_standard_client):
    """Test polling returns syllabus URL when status is COMPLETED."""
    user = User.objects.get(username="testskipuser")
    syllabus_status = Syllabus.StatusChoices.COMPLETED
    syllabus = Syllabus.objects.create(
        user=user, topic="Test Complete Poll", level="Expert", status=syllabus_status
    )

    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status
    assert "syllabus_url" in response_json
    expected_syllabus_url = reverse("syllabus:detail", args=[syllabus.pk])
    assert response_json["syllabus_url"] == expected_syllabus_url


@pytest.mark.django_db
def test_poll_syllabus_status_view_failed(logged_in_standard_client):
    """Test polling returns message when status is FAILED."""
    user = User.objects.get(username="testskipuser")
    syllabus_status = Syllabus.StatusChoices.FAILED
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Test Failed Poll",
        level="Intermediate",
        status=syllabus_status,
    )

    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status
    assert "message" in response_json
    assert "Syllabus generation failed" in response_json["message"]


@pytest.mark.django_db
def test_poll_syllabus_status_view_non_owner_permission_denied(
    logged_in_standard_client,
):
    """Test polling status for a syllabus owned by another user returns 403."""
    owner_user = User.objects.create_user(username="poll_owner", password="pw")
    syllabus = Syllabus.objects.create(
        user=owner_user,
        topic="Poll Owner Topic",
        level="Beginner",
        status=Syllabus.StatusChoices.GENERATING,
    )

    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = logged_in_standard_client.get(url)

    assert response.status_code == 403
    response_json = response.json()
    assert response_json["status"] == "error"
    assert "Permission denied" in response_json["message"]


@pytest.mark.django_db
def test_poll_syllabus_status_view_unauthenticated():
    """Test polling status when unauthenticated returns 401."""
    unauth_client = __import__("django.test").test.Client()
    user = User.objects.create_user(username="unauth_user", password="pw")
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Unauth Topic",
        level="Beginner",
        status=Syllabus.StatusChoices.GENERATING,
    )

    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id}
    )
    response = unauth_client.get(url)

    assert response.status_code == 401
    response_json = response.json()
    assert response_json["status"] == "error"
    assert "Authentication required" in response_json["message"]


@pytest.mark.django_db
def test_poll_syllabus_status_view_not_found(logged_in_standard_client):
    """Test polling status for a non-existent syllabus_id returns 404."""
    non_existent_uuid = uuid.uuid4()
    url = reverse(
        "onboarding:poll_syllabus_status", kwargs={"syllabus_id": non_existent_uuid}
    )

    response = logged_in_standard_client.get(url)
    assert response.status_code == 404
