""" onboarding/test_skip_assessment_view.py """
# pylint: disable=redefined-outer-name, unused-argument, no-member

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.constants import DIFFICULTY_BEGINNER
from core.models import UserAssessment

User = get_user_model()

# Note: These tests are synchronous as skip_assessment_view is synchronous


@pytest.mark.django_db
def test_skip_assessment_unauthenticated(client_fixture):
    """Test unauthenticated user POSTing to skip_assessment is redirected to login."""
    url = reverse("onboarding:skip_assessment")
    response = client_fixture.post(url)
    # Check for redirect to login URL (status code 302)
    assert response.status_code == 302
    # Check the redirect location points towards the login URL
    assert settings.LOGIN_URL in response.url


@pytest.mark.django_db
def test_skip_assessment_get_method_not_allowed(
    logged_in_standard_client,  # Uses fixture from conftest.py
):
    """Test GET request to skip_assessment returns 405 Method Not Allowed."""
    url = reverse("onboarding:skip_assessment")
    response = logged_in_standard_client.get(url)  # Use the logged-in client
    # The view uses @require_POST, so GET should return 405
    assert response.status_code == 405


@pytest.mark.django_db
def test_skip_assessment_success(logged_in_standard_client):  # Uses fixture from conftest.py
    """Test successful skip assessment via POST request for logged-in user."""
    # Fetch the user within the test since the fixture now returns the client
    user = User.objects.get(username="testskipuser")
    url = reverse("onboarding:skip_assessment")

    # Ensure no assessment exists beforehand for this user with this specific topic
    assert not UserAssessment.objects.filter(user=user, topic="Assessment Skipped").exists()

    response = logged_in_standard_client.post(url)  # Use the logged-in client

    # Assert redirect to dashboard
    assert response.status_code == 302
    assert response.url == reverse("dashboard")  # Use correct non-namespaced name

    # Assert UserAssessment created correctly
    assessment_exists = UserAssessment.objects.filter(user=user, topic="Assessment Skipped").exists()
    assert assessment_exists, "UserAssessment was not created."
    if assessment_exists:  # Avoid error if previous assert fails
        assessment = UserAssessment.objects.get(user=user, topic="Assessment Skipped")
        assert (
            assessment.topic == "Assessment Skipped"
        ), f"Expected topic 'Assessment Skipped', got '{assessment.topic}'"
        assert (
            assessment.knowledge_level == DIFFICULTY_BEGINNER
        ), f"Expected knowledge_level '{DIFFICULTY_BEGINNER}', got '{assessment.knowledge_level}'"
        assert assessment.score is None # Score should be None for skipped