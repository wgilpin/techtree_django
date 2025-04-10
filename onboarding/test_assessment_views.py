""" onboarding/test_assessment_views.py """
# pylint: disable=redefined-outer-name, unused-argument, no-member

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.conf import settings
from django.urls import reverse

# Import helpers from conftest
from .conftest import (
    get_session_value_sync,
    set_session_value_sync,
    session_key_exists_sync,
)

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# --- Test assessment_page_view ---


# This view is synchronous, so the test should not be async
# Remove the pytestmark for this specific test if needed, or run with standard client
@pytest.mark.django_db
def test_assessment_page_view_get(
    client_fixture, logged_in_user # logged_in_user fixture provides the user object but login is async
):  # Use standard client fixture
    """Test GET request for the assessment page."""
    # Need to login the standard client as well for sync view tests
    # The logged_in_user fixture uses async_client, so we log in the sync client separately
    client_fixture.login(username="testonboard", password="password")
    topic = "TestTopic"
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_assessment_page", args=[topic])
    # Use standard client.get for sync view
    response = client_fixture.get(url)
    assert response.status_code == 200
    assert "onboarding/assessment.html" in [t.name for t in response.templates]
    assert response.context["topic"] == topic
    # Check that start_url is in context (using correct key)
    assert "start_url" in response.context
    # Use correct URL names with namespace
    assert response.context["start_url"] == reverse("onboarding:onboarding_start", args=[topic])


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
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_start", args=[topic])

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
    assert response_json["difficulty"] == "Advanced"

    # Check session state asynchronously using helper
    session_data = await get_session_value_sync(
        async_client_fixture, settings.ASSESSMENT_STATE_KEY
    )
    assert session_data is not None
    assert session_data["topic"] == topic

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
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_start", args=[topic])

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
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_submit")
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
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_submit")
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
        "knowledge_level": "advanced", # Correct key
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
    mock_syllabus_id = uuid.uuid4()  # Generate a real UUID object
    mock_get_or_generate_syllabus.return_value = mock_syllabus_id # Return the UUID directly

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
        response_json["knowledge_level"] == "advanced" # Correct key
    )  # From final_assessment_result mock
    assert response_json["score"] == 80.0  # From final_assessment_result mock
    # Check for generating_url instead of syllabus_url
    assert "generating_url" in response_json
    # Check the structure of the generating URL
    expected_generating_url = reverse("onboarding:generating_syllabus", kwargs={'syllabus_id': mock_syllabus_id})
    assert response_json["generating_url"] == expected_generating_url
    assert response_json["feedback"] == "Assessment complete. Preparing your syllabus..." # Updated feedback

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
        topic="CompleteTopic", level="advanced", user=user # Correct key
    )


@pytest.mark.django_db  # Mark test as needing DB access
async def test_submit_answer_view_no_state(async_client_fixture, logged_in_user):
    """Test submitting answer when no assessment state exists in session."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_submit")
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
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_submit")
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
        "Missing 'answer' or 'skip' flag in JSON payload." in response_json["error"]
    )  # Check correct error message


@pytest.mark.django_db  # Mark test as needing DB access
@patch("onboarding.views.get_ai_instance")
async def test_submit_answer_view_evaluate_error(
    mock_get_ai, async_client_fixture, logged_in_user
):
    """Test submitting answer when AI evaluation fails."""
    # Await the fixture if it's async
    await logged_in_user
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_submit")
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
    url = reverse("onboarding:onboarding_submit")
    user_answer = "Final Answer JSON Test"
    topic = "JsonCompleteTopic"
    knowledge_level = "good knowledge" # Correct key
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
    mock_syllabus_id = uuid.uuid4() # Generate a real UUID object
    mock_get_or_generate_syllabus.return_value = mock_syllabus_id # Return the UUID directly

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
    # Check for generating_url instead of syllabus_url
    assert "generating_url" in response_json
    expected_generating_url = reverse("onboarding:generating_syllabus", kwargs={'syllabus_id': mock_syllabus_id})
    assert response_json["generating_url"] == expected_generating_url
    assert (
        response_json["feedback"] == "Assessment complete. Preparing your syllabus..."
    )  # Check updated feedback

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