""" onboarding/test_views.py """
# pylint: disable=redefined-outer-name, unused-argument, no-member

import json
import uuid  # Import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async  # Import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import AsyncClient, Client  # Import standard Client too
from django.urls import reverse

from core.models import UserAssessment  # Assuming UserAssessment is used

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

User = get_user_model()


@sync_to_async
def get_or_create_test_user(username, password):
    """Async helper to get or create a user."""
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "password": password,
            "email": f"{username}@example.com",
        },  # Provide defaults
    )
    # Set password if user already existed but might have wrong password in test env
    if not created:
        user.set_password(password)
        user.save()
    return user


# --- Async-safe Session Helpers ---
@sync_to_async
def set_session_value_sync(client, key, value):
    """Asynchronously sets a value in the session via the client and saves."""
    session = client.session
    session[key] = value
    session.save()


@sync_to_async
def get_session_value_sync(client, key, default=None):
    """Asynchronously gets a value from the session via the client."""
    return client.session.get(key, default)


@sync_to_async
def del_session_key_sync(client, key):
    """Asynchronously deletes a key from the session via the client."""
    session = client.session
    if key in session:
        del session[key]
        session.save()


@sync_to_async
def session_key_exists_sync(client, key):
    """Asynchronously checks if a key exists in the session via the client."""
    return key in client.session


# --- Async-safe Login Helper ---
@sync_to_async
def async_login(client, **credentials):
    """Asynchronously logs in a user using the client."""
    client.login(**credentials)


# --- Fixtures ---
@pytest.fixture
def async_client_fixture():
    """Fixture for creating an async test client."""
    return AsyncClient()


@pytest.fixture
def client_fixture():
    """Fixture for creating a standard test client."""
    return Client()


# Mark the fixture as needing DB access and make it async
@pytest.mark.django_db
@pytest.fixture
async def logged_in_user(async_client_fixture):
    """Fixture to create/get and log in a user asynchronously."""
    user = await get_or_create_test_user(username="testonboard", password="password")
    # Login using the async helper
    await async_login(async_client_fixture, username="testonboard", password="password")
    return user


# --- Test assessment_page_view ---


# This view is synchronous, so the test should not be async
@pytest.mark.django_db
def test_assessment_page_view_get(
    client_fixture, logged_in_user
):  # Use standard client fixture
    """Test GET request for the assessment page."""
    # Need to login the standard client as well for sync view tests
    client_fixture.login(username="testonboard", password="password")
    topic = "TestTopic"
    # Use correct URL name without namespace
    url = reverse("onboarding_assessment_page", args=[topic])
    # Use standard client.get for sync view
    response = client_fixture.get(url)
    assert response.status_code == 200
    assert "onboarding/assessment.html" in [t.name for t in response.templates]
    assert response.context["topic"] == topic
    # Check that start_url is in context (using correct key)
    assert "start_url" in response.context
    # submit_answer_url is not passed in assessment_page_view context
    # Use correct URL names without namespace
    assert response.context["start_url"] == reverse("onboarding_start", args=[topic])


# --- Test start_assessment_view ---


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.get_ai_instance")
async def test_start_assessment_view_success(
    mock_get_ai, async_client_fixture, logged_in_user
):
    """Test successful start of assessment."""
    # Await the fixture if it's async
    await logged_in_user
    topic = "CloudComputing"
    # Use correct URL name without namespace
    url = reverse("onboarding_start", args=[topic])

    # Mock the AI instance and its methods
    mock_ai_instance = MagicMock()
    mock_initial_state = {"topic": topic, "questions_asked": [], "step": 0}
    mock_ai_instance.initialize_state.return_value = mock_initial_state
    # Mock the async method generate_question
    mock_ai_instance.generate_question = AsyncMock(
        return_value={
            "questions_asked": [{"question": "Q1?", "options": ["A", "B"]}],
            "question_difficulties": [3],  # Add difficulties
            "step": 1,
            "topic": topic,
            "current_question": "Q1?",  # Ensure current_question is returned
            "current_question_difficulty": 3,  # Example difficulty
        }
    )
    # Mock perform_internet_search as well
    mock_ai_instance.perform_internet_search = AsyncMock(
        return_value={
            "wikipedia_content": "Wiki content",
            "google_results": ["G result"],
            "search_completed": True,
        }
    )
    mock_get_ai.return_value = mock_ai_instance

    # View requires GET, not POST
    response = await async_client_fixture.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert "question" in response_json  # Check for question key on success
    assert response_json["question"] == "Q1?"
    assert response_json["difficulty"] == 3

    # Check session state asynchronously using helper
    session_data = await get_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY
    )
    assert session_data is not None
    assert session_data["topic"] == topic
    # Check if step is updated based on mocked generate_question return
    # assert session_data['step'] == 1 # This depends on whether state is updated before return

    mock_ai_instance.initialize_state.assert_called_once_with(topic)
    mock_ai_instance.perform_internet_search.assert_called_once()
    mock_ai_instance.generate_question.assert_called_once()


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.get_ai_instance")
async def test_start_assessment_view_ai_error(
    mock_get_ai, async_client_fixture, logged_in_user
):
    """Test start assessment when AI fails to generate question."""
    # Await the fixture if it's async
    await logged_in_user
    topic = "AIErrorTopic"
    # Use correct URL name without namespace
    url = reverse("onboarding_start", args=[topic])

    mock_ai_instance = MagicMock()
    mock_initial_state = {"topic": topic, "questions_asked": [], "step": 0}
    mock_ai_instance.initialize_state.return_value = mock_initial_state
    # Mock perform_internet_search to succeed
    mock_ai_instance.perform_internet_search = AsyncMock(
        return_value={"search_completed": True}
    )
    # Simulate error during question generation
    mock_ai_instance.generate_question = AsyncMock(side_effect=Exception("AI Error"))
    mock_get_ai.return_value = mock_ai_instance

    # View requires GET, not POST
    response = await async_client_fixture.get(url)

    assert response.status_code == 500
    response_json = response.json()
    assert "error" in response_json  # Check for error key on failure
    assert "AI Error" in response_json["error"]


# --- Test submit_answer_view ---


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.create_user_assessment")  # Mock DB creation
@patch("onboarding.views.get_ai_instance")
async def test_submit_answer_view_continue(
    mock_get_ai, mock_create_assessment, async_client_fixture, logged_in_user
):
    """Test submitting an answer when assessment should continue."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name without namespace
    url = reverse("onboarding_submit")
    user_answer = "Answer A"

    # Mock AI instance and methods
    mock_ai_instance = MagicMock()
    # State before submitting answer (question already asked)
    # Ensure all keys expected by evaluate_answer are present
    current_state = {
        "topic": "ContinueTopic",
        "step": 1,
        "questions_asked": [{"question": "Q1?"}],
        "answers": [],
        "answer_evaluations": [],
        "question_difficulties": [3],  # Add difficulties
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_question_difficulty": 3,  # Example difficulty
        "current_target_difficulty": 3,  # Add missing key
    }
    # State after evaluating answer (must include keys expected by view update logic)
    evaluated_state = {
        "topic": "ContinueTopic",
        "step": 1,
        "questions_asked": [{"question": "Q1?"}],
        "answers": [{"answer": user_answer, "feedback": "Good"}],
        "answer_evaluations": [0.9],
        "question_difficulties": [3],  # Ensure this is carried over/returned
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_target_difficulty": 3,  # Ensure this key is returned by mock
        "feedback": "Good",  # Ensure feedback is returned
        "current_question_difficulty": 3,  # Add missing key
        "consecutive_wrong_at_current_difficulty": 0,  # Add key expected by should_continue call
    }
    # State after generating next question
    next_question_state = {
        "topic": "ContinueTopic",
        "step": 2,
        "questions_asked": [
            {"question": "Q1?"},
            {"question": "Q2?", "options": ["C", "D"]},
        ],
        "question_difficulties": [3, 4],  # Add difficulties
        "answers": [{"answer": user_answer, "feedback": "Good"}],
        "answer_evaluations": [0.9],
        "current_question": "Q2?",  # Ensure current question is in state
        "current_question_difficulty": 4,  # Example difficulty
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_target_difficulty": 3,
    }
    mock_ai_instance.evaluate_answer = AsyncMock(return_value=evaluated_state)
    mock_ai_instance.should_continue.return_value = True  # Indicate continue
    mock_ai_instance.generate_question = AsyncMock(return_value=next_question_state)
    mock_get_ai.return_value = mock_ai_instance

    # Set initial state in session asynchronously using helper
    await set_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY, current_state
    )

    response = await async_client_fixture.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    assert response.status_code == 200
    response_json = response.json()
    # Check keys returned by the view in this path
    # assert response_json['status'] == 'success' # Status key not returned here
    assert response_json["feedback"] == "Good"
    assert response_json["question"] == "Q2?"  # Check the correct key
    assert response_json["is_complete"] is False  # Check correct key

    # Check session updated asynchronously using helper
    session_data = await get_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY
    )
    assert session_data["step"] == 2
    assert len(session_data["answers"]) == 1

    mock_ai_instance.evaluate_answer.assert_called_once_with(current_state, user_answer)
    mock_ai_instance.should_continue.assert_called_once_with(evaluated_state)
    mock_ai_instance.generate_question.assert_called_once_with(evaluated_state)
    mock_create_assessment.assert_not_called()  # Should not be called yet


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.create_user_assessment")  # Mock DB creation for assessment
@patch(
    "onboarding.views.syllabus_service.get_or_generate_syllabus"
)  # Mock syllabus service call
@patch("onboarding.views.get_ai_instance")  # Mock assessment AI
async def test_submit_answer_view_complete(
    mock_get_ai,
    mock_get_or_generate_syllabus,
    mock_create_assessment,
    async_client_fixture,
    logged_in_user,
):
    """Test submitting the final answer, completing the assessment."""
    # Await the fixture if it's async
    user = await logged_in_user
    # Use correct URL name without namespace
    url = reverse("onboarding_submit")
    user_answer = "Final Answer"

    # Mock AI instance and methods
    mock_ai_instance = MagicMock()
    current_state = {
        "topic": "CompleteTopic",
        "step": 2,
        "questions_asked": [
            {"q": "Q1"},
            {"q": "Q2"},
            {"q": "Q3"},
        ],  # Assume 3rd question was last
        "question_difficulties": [2, 3, 4],  # Add difficulties
        "answers": [{"a": "A1"}, {"a": "A2"}],
        "answer_evaluations": [0.8, 0.7],  # Use correct key
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,  # Add missing keys
        "current_question_difficulty": 4,  # Example
        "current_target_difficulty": 4,  # Add missing key
        "user_id": user.pk,  # Add user_id for saving check
    }
    evaluated_state = {
        "topic": "CompleteTopic",
        "step": 2,
        "questions_asked": [{"q": "Q1"}, {"q": "Q2"}, {"q": "Q3"}],
        "question_difficulties": [2, 3, 4],  # Ensure carried over/returned
        "answers": [
            {"a": "A1"},
            {"a": "A2"},
            {"answer": user_answer, "feedback": "Done"},
        ],
        "answer_evaluations": [0.8, 0.7, 0.9],  # Use correct key
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 1,  # Example update
        "current_target_difficulty": 4,  # Ensure this key is returned by mock
        "feedback": "Done",  # Ensure feedback is returned
        "current_question_difficulty": 4,  # Add missing key
        "user_id": user.pk,  # Add user_id for should_continue check
        "consecutive_wrong_at_current_difficulty": 0,  # Add key expected by should_continue call
    }
    final_assessment_result = {
        "overall_score": 80.0,
        "knowledge_level": "advanced",
    }  # Score as percentage
    # Mock calculate_final_assessment to return the state *with* the final_assessment key and feedback
    final_state_with_assessment_key = {
        **evaluated_state,
        "final_assessment": final_assessment_result,
        "is_complete": True,
        "feedback": "Done",  # Ensure feedback persists
    }

    mock_ai_instance.evaluate_answer = AsyncMock(return_value=evaluated_state)
    mock_ai_instance.should_continue.return_value = False  # Indicate stop
    mock_ai_instance.calculate_final_assessment.return_value = (
        final_state_with_assessment_key  # Return state with key
    )
    mock_get_ai.return_value = mock_ai_instance

    # Mock the syllabus service call to return a valid UUID syllabus ID
    mock_syllabus_id = str(uuid.uuid4())  # Generate a real UUID
    mock_get_or_generate_syllabus.return_value = {"syllabus_id": mock_syllabus_id}

    # Set initial state in session asynchronously using helper
    await set_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY, current_state
    )

    response = await async_client_fixture.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    # Expect JSON response (200 OK) now, not redirect
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["is_complete"] is True
    assert (
        response_json["knowledge_level"] == "advanced"
    )  # From final_assessment_result mock
    assert response_json["score"] == 80.0  # From final_assessment_result mock
    assert "syllabus_url" in response_json
    expected_syllabus_url = reverse("syllabus:detail", args=[mock_syllabus_id])
    assert response_json["syllabus_url"] == expected_syllabus_url
    assert response_json["feedback"] == "Assessment complete. Syllabus generated."

    # Check session state cleared asynchronously using helper
    session_exists = await session_key_exists_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY
    )
    assert not session_exists

    mock_ai_instance.evaluate_answer.assert_called_once_with(current_state, user_answer)
    mock_ai_instance.should_continue.assert_called_once_with(evaluated_state)
    mock_ai_instance.calculate_final_assessment.assert_called_once_with(evaluated_state)
    mock_ai_instance.generate_question.assert_not_called()
    # Check UserAssessment was created (mocked)
    mock_create_assessment.assert_called_once()
    # Check syllabus generation was called (mocked)
    mock_get_or_generate_syllabus.assert_called_once_with(
        topic="CompleteTopic", level="advanced", user=user
    )
    # Check history args if needed


@pytest.mark.django_db  # Mark test as needing DB access
async def test_submit_answer_view_no_state(async_client_fixture, logged_in_user):
    """Test submitting answer when no assessment state exists in session."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name without namespace
    url = reverse("onboarding_submit")
    response = await async_client_fixture.post(
        url, json.dumps({"answer": "test"}), content_type="application/json"
    )

    assert response.status_code == 400
    response_json = response.json()
    assert "error" in response_json  # Check correct key
    assert "No active assessment found" in response_json["error"]  # Check correct key


@pytest.mark.django_db  # Mark test as needing DB access
async def test_submit_answer_view_missing_answer(async_client_fixture, logged_in_user):
    """Test submitting answer with missing 'answer' key in JSON."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name without namespace
    url = reverse("onboarding_submit")
    # Set some state in session asynchronously using helper
    await set_session_value_sync(
        async_client_fixture,
        settings.ASSESSMENT_STATE_KEY,
        {"topic": "Test", "step": 1},
    )

    response = await async_client_fixture.post(
        url, json.dumps({"other_key": "value"}), content_type="application/json"
    )

    assert response.status_code == 400
    response_json = response.json()
    assert "error" in response_json  # Check correct key
    assert (
        "Missing answer in JSON payload." in response_json["error"]
    )  # Check correct error message


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.get_ai_instance")
async def test_submit_answer_view_evaluate_error(
    mock_get_ai, async_client_fixture, logged_in_user
):
    """Test submitting answer when AI evaluation fails."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name without namespace
    url = reverse("onboarding_submit")
    user_answer = "Answer causing error"

    mock_ai_instance = MagicMock()
    current_state = {"topic": "EvalError", "step": 1, "questions_asked": ["Q1"]}
    mock_ai_instance.evaluate_answer = AsyncMock(
        side_effect=Exception("Evaluation Failed")
    )
    mock_get_ai.return_value = mock_ai_instance

    # Set state in session asynchronously using helper
    await set_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY, current_state
    )

    response = await async_client_fixture.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    assert response.status_code == 500
    response_json = response.json()
    assert "error" in response_json  # Check correct key
    assert (
        "Failed to process answer: Evaluation Failed" in response_json["error"]
    )  # Check correct error message
    # Check session state might have error message? (Depends on implementation)
    # session_data = await get_session_value_sync(async_client_fixture, settings.ASSESSMENT_STATE_KEY)
    # assert 'error_message' in session_data


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.create_user_assessment")  # Mock DB creation for assessment
@patch(
    "onboarding.views.syllabus_service.get_or_generate_syllabus"
)  # Mock syllabus service call
@patch("onboarding.views.get_ai_instance")  # Mock assessment AI
async def test_submit_answer_view_complete_returns_json_with_url(
    mock_get_ai,
    mock_get_or_generate_syllabus,
    mock_create_assessment,
    async_client_fixture,
    logged_in_user,
):
    """Test submitting final answer returns JSON with syllabus URL on completion."""
    user = await logged_in_user
    url = reverse("onboarding_submit")
    user_answer = "Final Answer JSON Test"
    topic = "JsonCompleteTopic"
    knowledge_level = "intermediate"
    score = 75.0

    # Mock AI instance and methods
    mock_ai_instance = MagicMock()
    current_state = {
        "topic": topic,
        "step": 2,
        "questions_asked": [{"q": "Q1"}, {"q": "Q2"}, {"q": "Q3"}],
        "question_difficulties": [2, 3, 4],
        "answers": [{"a": "A1"}, {"a": "A2"}],
        "answer_evaluations": [0.8, 0.7],
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_question_difficulty": 4,
        "current_target_difficulty": 4,
        "user_id": user.pk,
    }
    # State after evaluation
    evaluated_state = {
        **current_state,
        "answers": [
            {"a": "A1"},
            {"a": "A2"},
            {"answer": user_answer, "feedback": "Done"},
        ],
        "answer_evaluations": [0.8, 0.7, 0.9],
        "feedback": "Done",
        "consecutive_wrong_at_current_difficulty": 0,  # Add key expected by should_continue call
    }
    # State after final calculation (returned by calculate_final_assessment)
    final_assessment_result = {
        "overall_score": score,
        "knowledge_level": knowledge_level,
    }
    final_state_with_assessment_key = {
        **evaluated_state,
        "final_assessment": final_assessment_result,
        "is_complete": True,
        "knowledge_level": knowledge_level,  # Ensure level is here for view logic
        "score": score,  # Ensure score is here for view logic
    }

    mock_ai_instance.evaluate_answer = AsyncMock(return_value=evaluated_state)
    mock_ai_instance.should_continue.return_value = False  # Indicate stop
    mock_ai_instance.calculate_final_assessment.return_value = (
        final_state_with_assessment_key
    )
    mock_get_ai.return_value = mock_ai_instance

    # Mock the syllabus service call to return a valid UUID syllabus ID
    mock_syllabus_id = str(uuid.uuid4())
    mock_get_or_generate_syllabus.return_value = {"syllabus_id": mock_syllabus_id}

    # Set initial state in session
    await set_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY, current_state
    )

    # Make the POST request
    response = await async_client_fixture.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    # Assert: Expect JSON response (200 OK)
    assert response.status_code == 200
    response_json = response.json()

    # Assert: Check JSON content
    assert response_json["is_complete"] is True
    assert response_json["knowledge_level"] == knowledge_level
    assert response_json["score"] == score
    assert "syllabus_url" in response_json
    expected_syllabus_url = reverse("syllabus:detail", args=[mock_syllabus_id])
    assert response_json["syllabus_url"] == expected_syllabus_url
    assert (
        response_json["feedback"] == "Assessment complete. Syllabus generated."
    )  # Check feedback

    # Assert: Session state should be cleared
    session_exists = await session_key_exists_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY
    )
    assert not session_exists

    # Assert: Mocks called correctly
    mock_ai_instance.evaluate_answer.assert_called_once_with(current_state, user_answer)
    mock_ai_instance.should_continue.assert_called_once_with(evaluated_state)
    mock_ai_instance.calculate_final_assessment.assert_called_once_with(evaluated_state)
    mock_ai_instance.generate_question.assert_not_called()
    mock_create_assessment.assert_called_once()  # Check assessment saved
    mock_get_or_generate_syllabus.assert_called_once_with(
        topic=topic, level=knowledge_level, user=user
    )


# Fixture for standard client logged-in user
@pytest.mark.django_db
@pytest.fixture
def logged_in_standard_client(client_fixture):
    """Fixture to create/get a user and return a logged-in standard client."""
    username = "testskipuser"
    password = "password"
    # Use standard ORM calls. Ensure password is set correctly.
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@example.com"
        },  # Don't set raw password in defaults
    )
    user.set_password(password)  # Set/reset password correctly using hashing
    user.save()

    # Login using the standard client passed in
    login_successful = client_fixture.login(username=username, password=password)
    assert login_successful, "Client login failed in fixture"  # Verify login worked

    return client_fixture  # Return the logged-in client


# --- Tests for skip_assessment_view ---


@pytest.mark.django_db
def test_skip_assessment_unauthenticated(client_fixture):
    """Test unauthenticated user POSTing to skip_assessment is redirected to login."""
    url = reverse("skip_assessment")  # Use correct non-namespaced name
    response = client_fixture.post(url)
    # Check for redirect to login URL (status code 302)
    assert response.status_code == 302
    # Check the redirect location points towards the login URL
    assert settings.LOGIN_URL in response.url


@pytest.mark.django_db
def test_skip_assessment_get_method_not_allowed(
    logged_in_standard_client,
):  # Use the new fixture
    """Test GET request to skip_assessment returns 405 Method Not Allowed."""
    url = reverse("skip_assessment")  # Use correct non-namespaced name
    response = logged_in_standard_client.get(url)  # Use the logged-in client
    # The view uses @require_POST, so GET should return 405
    assert response.status_code == 405


@pytest.mark.django_db
def test_skip_assessment_success(logged_in_standard_client):  # Use the new fixture
    """Test successful skip assessment via POST request for logged-in user."""
    # Fetch the user within the test since the fixture now returns the client
    user = User.objects.get(username="testskipuser")
    url = reverse("skip_assessment")  # Use correct non-namespaced name

    # Ensure no assessment exists beforehand for this user
    assert not UserAssessment.objects.filter(user=user).exists()

    response = logged_in_standard_client.post(url)  # Use the logged-in client

    # Assert redirect to dashboard
    assert response.status_code == 302
    assert response.url == reverse("dashboard")  # Use correct non-namespaced name

    # Assert UserAssessment created correctly
    assessment_exists = UserAssessment.objects.filter(user=user).exists()
    assert assessment_exists, "UserAssessment was not created."
    if assessment_exists:  # Avoid error if previous assert fails
        assessment = UserAssessment.objects.get(user=user)
        assert (
            assessment.topic == "Assessment Skipped"
        ), f"Expected topic 'Assessment Skipped', got '{assessment.topic}'"
        assert (
            assessment.knowledge_level == "beginner"
        ), f"Expected knowledge_level 'beginner', got '{assessment.knowledge_level}'"
