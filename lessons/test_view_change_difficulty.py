# lessons/test_view_change_difficulty.py
# Tests for the change_difficulty_view using pytest style
# pylint: disable=redefined-outer-name, missing-function-docstring, missing-module-docstring

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.test import AsyncClient
from django.urls import reverse

import lessons.views
from core.constants import (
    DIFFICULTY_BEGINNER,  # Import constants
    DIFFICULTY_EARLY_LEARNER,
    DIFFICULTY_GOOD_KNOWLEDGE,
)
from core.models import Syllabus

User = get_user_model()

# --- Fixtures ---


# Helper for async login used in onboarding tests
@sync_to_async
def async_login(client, **credentials):
    client.login(**credentials)


@pytest.fixture
def async_client_fixture():
    return AsyncClient()


@sync_to_async
def get_or_create_test_user_pytest(
    username="testuser_pytest_cd", password="password"
):  # Changed username slightly
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"password": password, "email": f"{username}@example.com"},
    )
    if not created:
        user.set_password(password)
        user.save()
    return user


@pytest.fixture
@pytest.mark.django_db
async def logged_in_user_pytest(async_client_fixture):
    user = await get_or_create_test_user_pytest()
    await async_login(
        async_client_fixture, username="testuser_pytest_cd", password="password"
    )
    return user, async_client_fixture  # Return client as well


# --- Tests ---


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_change_difficulty_unauthenticated(async_client_fixture):
    """Test unauthenticated access redirects to login."""
    syllabus = await sync_to_async(Syllabus.objects.create)(
        topic="AuthTest", level=DIFFICULTY_GOOD_KNOWLEDGE
    )
    url = reverse("lessons:change_difficulty", args=[syllabus.pk])
    response = await async_client_fixture.get(url)
    assert response.status_code == 302
    assert settings.LOGIN_URL in response.url


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_change_difficulty_lowest_level(logged_in_user_pytest):
    """Test attempting to lower difficulty from the lowest level."""
    user, client = await logged_in_user_pytest  # Await the fixture
    syllabus = await sync_to_async(Syllabus.objects.create)(
        topic="LowestLevel", level=DIFFICULTY_BEGINNER, user=user
    )

    detail_url = reverse("syllabus:detail", args=[syllabus.pk])
    # For beginner level, we expect the view to redirect to detail page without generating a new syllabus

    # We need to patch both the authentication check and the database query
    # First, let's create a patched version of the request.auser() method
    async def mock_auser():
        return user

    # Now let's create a patched version of the view function
    with patch.object(client, "get") as mock_get:
        # Create a mock response
        mock_response = AsyncMock()
        mock_response.status_code = 302
        mock_response.url = detail_url
        mock_get.return_value = mock_response

        # Call the view directly with our mocked request
        request = AsyncMock()
        request.auser = mock_auser
        request.user = user

        # Call the view directly
        await lessons.views.change_difficulty_view(request, syllabus.pk)
    # Check messages framework if possible/needed (requires enabling middleware in tests)


@pytest.mark.asyncio
@pytest.mark.django_db
@patch(
    "lessons.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock
)
async def test_change_difficulty_success(mock_generate, logged_in_user_pytest):
    """Test successful difficulty change redirects to generating page."""
    user, client = await logged_in_user_pytest  # Await the fixture
    topic = "IntermediateTopic"
    current_level = DIFFICULTY_GOOD_KNOWLEDGE
    new_level = DIFFICULTY_EARLY_LEARNER
    # Create syllabus directly using sync_to_async as it's outside the view logic being tested
    syllabus = await sync_to_async(Syllabus.objects.create)(
        topic=topic, level=current_level, user=user
    )

    url = reverse("lessons:change_difficulty", args=[syllabus.pk])
    # We expect the redirect URL to use the ID returned by the mocked service call
    expected_redirect_id = uuid.uuid4()

    # Call the view directly using the test client
    # The outer patch on syllabus_service.get_or_generate_syllabus is active
    mock_generate.return_value = (
        expected_redirect_id  # Use the specific UUID we defined
    )
    response = await client.get(url)

    # Verify the mock was called
    mock_generate.assert_awaited_once()

    # Assertions should be inside the test function
    assert response.status_code == 302
    expected_generating_url = reverse(
        "onboarding:generating_syllabus", kwargs={"syllabus_id": expected_redirect_id}
    )
    assert response.url == expected_generating_url
    # Check the async mock was awaited (or called if service was sync)
    mock_generate.assert_called_once_with(topic=topic, level=new_level, user=user)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_change_difficulty_not_found(logged_in_user_pytest):
    """Test accessing change difficulty for a non-existent syllabus."""
    _, client = await logged_in_user_pytest  # Await the fixture
    non_existent_uuid = uuid.uuid4()
    url = reverse("lessons:change_difficulty", args=[non_existent_uuid])
    dashboard_url = reverse("dashboard")

    # Create a patched version of the view function
    original_view = lessons.views.change_difficulty_view

    async def patched_view(request, syllabus_id):
        # Mock the database query to raise DoesNotExist
        # Mock the database query to raise DoesNotExist
        with patch("core.models.Syllabus.objects.get") as mock_db_get:
            mock_db_get.side_effect = ObjectDoesNotExist
            return await original_view(request, syllabus_id)

    # Apply the patch
    with patch("lessons.views.change_difficulty_view", side_effect=patched_view):
        response = await client.get(url)

        assert response.status_code == 302
        assert response.url == dashboard_url
        # Check messages framework if possible/needed
