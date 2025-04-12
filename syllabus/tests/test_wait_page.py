import pytest
from django.urls import reverse
from django.test import Client
from core.models import Syllabus
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
def test_wait_page_renders_for_pending_syllabus(client: Client):
    user = User.objects.create_user(username="waituser", password="pw")
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Test Topic",
        level="beginner",
        status=Syllabus.StatusChoices.PENDING,
    )
    client.force_login(user)
    url = reverse("syllabus:wait_for_generation", args=[syllabus.syllabus_id])
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Please wait while your syllabus is being prepared" in resp.content
    assert str(syllabus.syllabus_id).encode() in resp.content

@pytest.mark.django_db
def test_wait_page_polls_correct_endpoint(client: Client):
    user = User.objects.create_user(username="waituser2", password="pw")
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Test Topic 2",
        level="beginner",
        status=Syllabus.StatusChoices.PENDING,
    )
    client.force_login(user)
    url = reverse("syllabus:wait_for_generation", args=[syllabus.syllabus_id])
    resp = client.get(url)
    assert resp.status_code == 200
    # The polling URL should be present in a data attribute for testability
    html = resp.content.decode()
    expected_url = f"/onboarding/poll-syllabus-status/{syllabus.syllabus_id}/"
    assert f'data-poll-url="{expected_url}"' in html

@pytest.mark.django_db
def test_wait_page_redirects_when_completed(client: Client):
    user = User.objects.create_user(username="waituser3", password="pw")
    syllabus = Syllabus.objects.create(
        user=user,
        topic="Test Topic 3",
        level="beginner",
        status=Syllabus.StatusChoices.COMPLETED,
    )
    client.force_login(user)
    # Simulate user going to wait page for a completed syllabus
    url = reverse("syllabus:wait_for_generation", args=[syllabus.syllabus_id])
    resp = client.get(url)
    # Should still render the wait page, but frontend JS will redirect
    assert resp.status_code == 200
    assert b"Please wait while your syllabus is being prepared" in resp.content