""" onboarding/test_generating_polling_views.py """
# pylint: disable=redefined-outer-name, unused-argument, no-member

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.urls import reverse
from django.contrib.auth import get_user_model # Correct import for User
from django.http import Http404 # Import Http404 for explicit handling

from core.models import Syllabus # Import only Syllabus from core.models

# Import helpers from conftest
from .conftest import get_or_create_test_user

User = get_user_model() # Get the User model

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

# Add teardown to ensure all patches are properly cleaned up
@pytest.fixture(autouse=True)
def cleanup_patches():
    """Fixture to clean up any patches that might have leaked."""
    yield
    from unittest.mock import patch
    patch.stopall()  # Stop all patches after each test


@pytest.mark.django_db
async def test_generating_syllabus_view_owner_access(
    async_client_fixture, logged_in_user
):
    """Test that the owner can access the generating syllabus page."""
    user = await logged_in_user
    # Create a syllabus owned by the user asynchronously
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus = await create_syllabus_async(
        user=user, topic="Test Gen Topic", level="Beginner", status=Syllabus.StatusChoices.GENERATING # Use GENERATING
    )

    url = reverse("onboarding:generating_syllabus", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 200
    assert "onboarding/generating_syllabus.html" in [t.name for t in response.templates]
    assert response.context["syllabus"] == syllabus
    assert "poll_url" in response.context


@pytest.mark.django_db
async def test_generating_syllabus_view_non_owner_redirects(
    async_client_fixture, logged_in_user
):
    """Test that a non-owner is redirected from the generating page."""
    owner_user = await get_or_create_test_user(username="owner", password="pw")
    # Create syllabus owned by 'owner'
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus = await create_syllabus_async(
        user=owner_user, topic="Owner Topic", level="Beginner", status=Syllabus.StatusChoices.GENERATING # Use GENERATING
    )

    # Log in as 'testonboard' (logged_in_user fixture)
    await logged_in_user

    url = reverse("onboarding:generating_syllabus", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    # Expect redirect to dashboard
    assert response.status_code == 302
    assert response.url == reverse("dashboard")


@pytest.mark.django_db
async def test_poll_syllabus_status_view_success(
    async_client_fixture, logged_in_user
):
    """Test successful polling of syllabus status by the owner."""
    user = await logged_in_user
    # Create a syllabus owned by the user asynchronously
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus_status = Syllabus.StatusChoices.GENERATING # Use GENERATING
    syllabus = await create_syllabus_async(
        user=user, topic="Test Poll Topic", level="Beginner", status=syllabus_status
    )

    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status
    # Implicitly checks that no SynchronousOnlyOperation occurred


@pytest.mark.django_db
async def test_poll_syllabus_status_view_completed(
    async_client_fixture, logged_in_user
):
    """Test polling returns syllabus URL when status is COMPLETED."""
    user = await logged_in_user
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus_status = Syllabus.StatusChoices.COMPLETED
    syllabus = await create_syllabus_async(
        user=user, topic="Test Complete Poll", level="Expert", status=syllabus_status
    )

    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status
    assert "syllabus_url" in response_json
    # Check the URL points to the correct syllabus detail view
    # Need sync_to_async to access syllabus.pk in async context if not already loaded
    get_syllabus_pk = sync_to_async(lambda s: s.pk)
    syllabus_pk = await get_syllabus_pk(syllabus)
    expected_syllabus_url = reverse("syllabus:detail", args=[syllabus_pk])
    assert response_json["syllabus_url"] == expected_syllabus_url


@pytest.mark.django_db
async def test_poll_syllabus_status_view_failed(
    async_client_fixture, logged_in_user
):
    """Test polling returns message when status is FAILED."""
    user = await logged_in_user
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus_status = Syllabus.StatusChoices.FAILED
    syllabus = await create_syllabus_async(
        user=user, topic="Test Failed Poll", level="Intermediate", status=syllabus_status
    )

    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == syllabus_status
    assert "message" in response_json
    assert "Syllabus generation failed" in response_json["message"]


@pytest.mark.django_db
async def test_poll_syllabus_status_view_non_owner_permission_denied(
    async_client_fixture, logged_in_user
):
    """Test polling status for a syllabus owned by another user returns 403."""
    owner_user = await get_or_create_test_user(username="poll_owner", password="pw")
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus = await create_syllabus_async(
        user=owner_user, topic="Poll Owner Topic", level="Beginner", status=Syllabus.StatusChoices.GENERATING # Use GENERATING
    )

    # Log in as 'testonboard'
    await logged_in_user

    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 403
    response_json = response.json()
    assert response_json["status"] == "error"
    assert "Permission denied" in response_json["message"]


@pytest.mark.django_db
async def test_poll_syllabus_status_view_unauthenticated(
    async_client_fixture, # No logged_in_user
):
    """Test polling status when unauthenticated returns 401."""
    # Create a user and syllabus, but don't log in
    user = await get_or_create_test_user(username="unauth_user", password="pw")
    create_syllabus_async = sync_to_async(Syllabus.objects.create)
    syllabus = await create_syllabus_async(
        user=user, topic="Unauth Topic", level="Beginner", status=Syllabus.StatusChoices.GENERATING # Use GENERATING
    )

    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus.syllabus_id})
    response = await async_client_fixture.get(url)

    assert response.status_code == 401
    response_json = response.json()
    assert response_json["status"] == "error"
    assert "Authentication required" in response_json["message"]


@pytest.mark.django_db
async def test_poll_syllabus_status_view_not_found(
    async_client_fixture, logged_in_user
):
    """Test polling status for a non-existent syllabus_id returns 404."""
    await logged_in_user
    non_existent_uuid = uuid.uuid4()
    url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": non_existent_uuid})

    # Django's test client automatically handles the Http404 raised by get_object_or_404
    # and converts it into a 404 response.
    response = await async_client_fixture.get(url)
    assert response.status_code == 404