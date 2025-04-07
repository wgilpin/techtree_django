"""Tests for the asynchronous views in the syllabus app."""
# pylint: disable=missing-function-docstring, no-member

import uuid
from unittest.mock import ANY, AsyncMock, patch

import pytest
from django.urls import reverse

from core.exceptions import ApplicationError

# Mark all tests in this module as needing DB access
pytestmark = [pytest.mark.django_db(transaction=True)]

# Add teardown to ensure all patches are properly cleaned up
@pytest.fixture(autouse=True)
def cleanup_patches():
    """Fixture to clean up any patches that might have leaked."""
    yield
    from unittest.mock import patch
    patch.stopall()  # Stop all patches after each test


# --- generate_syllabus_view (Async View) ---
@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_success(mock_generate, logged_in_async_client):
    topic = "Test Gen Topic"
    level = "beginner"
    generated_uuid = uuid.uuid4() # Generate a UUID object
    mock_generate.return_value = generated_uuid # Mock returns the UUID directly
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    # Assert redirect to the generating page in the onboarding app
    assert response.url == reverse("onboarding:generating_syllabus", kwargs={"syllabus_id": generated_uuid})
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY)  # Use ANY for user


@pytest.mark.asyncio
async def test_generate_syllabus_missing_topic(logged_in_async_client):
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.post(url, {"level": "beginner"})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


@pytest.mark.asyncio
async def test_generate_syllabus_get_request(logged_in_async_client):
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")


@pytest.mark.asyncio
async def test_generate_syllabus_unauthenticated(async_client):
    url = reverse("syllabus:generate")
    client = async_client  # No need to await the fixture itself
    response = await client.post(url, {"topic": "Test", "level": "beginner"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_service_app_error(mock_generate, logged_in_async_client):
    topic = "App Error Topic"
    level = "advanced" # Use correct key
    mock_generate.side_effect = ApplicationError("AI Failed")
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY)  # Use ANY for user


@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_service_other_error(mock_generate, logged_in_async_client):
    topic = "Other Error Topic"
    level = "beginner"
    mock_generate.side_effect = Exception("Unexpected")
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY)  # Use ANY for user


@pytest.mark.asyncio
@patch("syllabus.views.syllabus_service.get_or_generate_syllabus", new_callable=AsyncMock)
async def test_generate_syllabus_missing_id_response(mock_generate, logged_in_async_client):
    topic = "Missing ID Topic"
    level = "good knowledge" # Use correct key
    mock_generate.return_value = {"syllabus_id": None}  # Simulate missing ID
    url = reverse("syllabus:generate")
    client = await logged_in_async_client  # Await client
    response = await client.post(url, {"topic": topic, "level": level})
    assert response.status_code == 302
    assert response.url == reverse("syllabus:landing")
    # Assert the mock was called with the correct arguments, including the user
    mock_generate.assert_called_once_with(topic=topic, level=level, user=ANY)  # Use ANY for user