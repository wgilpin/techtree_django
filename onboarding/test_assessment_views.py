""" onboarding/test_assessment_views.py """
# pylint: disable=redefined-outer-name, unused-argument, no-member

import json
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.urls import reverse

# --- Test assessment_page_view ---


# Remove the pytestmark for this specific test if needed, or run with standard client
@pytest.mark.django_db
def test_assessment_page_view_get(
    logged_in_standard_client
):
    """Test GET request for the assessment page."""
    # Need to login the standard client as well for  view tests
    topic = "TestTopic"
    # Use correct URL name with namespace
    url = reverse("onboarding:onboarding_assessment_page", args=[topic])
    response = logged_in_standard_client.get(url)
    assert response.status_code == 200
    assert "onboarding/assessment.html" in [t.name for t in response.templates]
    assert response.context["topic"] == topic
    # Check that start_url is in context (using correct key)
    assert "start_url" in response.context
    # Use correct URL names with namespace
    assert response.context["start_url"] == reverse("onboarding:onboarding_start", args=[topic])


# --- Test start_assessment_view ---


@pytest.mark.django_db
@patch("onboarding.views.get_ai_instance")
def test_start_assessment_view_success(
    mock_get_ai, logged_in_standard_client
):
    """Test successful start of assessment."""
    # Already logged in by fixture
    topic = "CloudComputing"
    url = reverse("onboarding:onboarding_start", args=[topic])

    mock_ai_instance = MagicMock()
    mock_initial_state = {"topic": topic, "questions_asked": [], "step": 0}
    mock_ai_instance.initialize_state.return_value = mock_initial_state
    mock_ai_instance.generate_question.return_value = {
        "questions_asked": [{"question": "Q1?", "options": ["A", "B"]}],
        "question_difficulties": [3],
        "step": 1,
        "topic": topic,
        "current_question": "Q1?",
        "current_question_difficulty": 3,
    }
    mock_ai_instance.perform_internet_search.return_value = {
        "wikipedia_content": "Wiki content",
        "google_results": ["G result"],
        "search_completed": True,
    }
    mock_get_ai.return_value = mock_ai_instance

    response = logged_in_standard_client.get(url)

    assert response.status_code == 200
    response_json = response.json()
    assert "question" in response_json
    assert response_json["question"] == "Q1?"
    assert response_json["difficulty"] == "Advanced"

    session_data = logged_in_standard_client.session.get(settings.ASSESSMENT_STATE_KEY)
    assert session_data is not None
    assert session_data["topic"] == topic

    mock_ai_instance.initialize_state.assert_called_once_with(topic)
    mock_ai_instance.perform_internet_search.assert_called_once()
    mock_ai_instance.generate_question.assert_called_once()


@pytest.mark.django_db
@patch("onboarding.views.get_ai_instance")
def test_start_assessment_view_ai_error(
    mock_get_ai, logged_in_standard_client
):
    """Test start assessment when AI fails to generate question."""
    # Already logged in by fixture
    topic = "AIErrorTopic"
    url = reverse("onboarding:onboarding_start", args=[topic])

    mock_ai_instance = MagicMock()
    mock_initial_state = {"topic": topic, "questions_asked": [], "step": 0}
    mock_ai_instance.initialize_state.return_value = mock_initial_state
    mock_ai_instance.perform_internet_search.return_value = {"search_completed": True}
    mock_ai_instance.generate_question.side_effect = Exception("AI Error")
    mock_get_ai.return_value = mock_ai_instance

    response = logged_in_standard_client.get(url)

    assert response.status_code == 500
    response_json = response.json()
    assert "error" in response_json
    assert "AI Error" in response_json["error"]


# --- Test submit_answer_view ---


@pytest.mark.django_db
@patch("onboarding.views.create_user_assessment")
@patch("onboarding.views.get_ai_instance")
def test_submit_answer_view_continue(
    mock_get_ai, mock_create_assessment, logged_in_standard_client
):
    """Test submitting an answer when assessment should continue."""
    # Already logged in by fixture
    url = reverse("onboarding:onboarding_submit")
    user_answer = "Answer A"

    mock_ai_instance = MagicMock()
    current_state = {
        "topic": "ContinueTopic",
        "step": 1,
        "questions_asked": [{"question": "Q1?"}],
        "answers": [],
        "answer_evaluations": [],
        "question_difficulties": [3],
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_question_difficulty": 3,
        "current_target_difficulty": 3,
    }
    evaluated_state = {
        "topic": "ContinueTopic",
        "step": 1,
        "questions_asked": [{"question": "Q1?"}],
        "answers": [{"answer": user_answer, "feedback": "Good"}],
        "answer_evaluations": [0.9],
        "question_difficulties": [3],
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_target_difficulty": 3,
        "feedback": "Good",
        "current_question_difficulty": 3,
        "consecutive_wrong_at_current_difficulty": 0,
    }
    next_question_state = {
        "topic": "ContinueTopic",
        "step": 2,
        "questions_asked": [
            {"question": "Q1?"},
            {"question": "Q2?", "options": ["C", "D"]},
        ],
        "question_difficulties": [3, 4],
        "answers": [{"answer": user_answer, "feedback": "Good"}],
        "answer_evaluations": [0.9],
        "current_question": "Q2?",
        "current_question_difficulty": 4,
        "consecutive_wrong": 0,
        "consecutive_hard_correct_or_partial": 0,
        "current_target_difficulty": 3,
    }
    mock_ai_instance.evaluate_answer.return_value = evaluated_state
    mock_ai_instance.should_continue.return_value = True
    mock_ai_instance.generate_question.return_value = next_question_state
    mock_get_ai.return_value = mock_ai_instance

    session = logged_in_standard_client.session
    session[settings.ASSESSMENT_STATE_KEY] = current_state
    session.save()

    response = logged_in_standard_client.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "processing"
    assert "task_id" in response_json

    session_data = logged_in_standard_client.session.get(settings.ASSESSMENT_STATE_KEY)
    assert session_data["step"] == 1  # No update yet,  processing
    assert len(session_data["answers"]) == 0  # No update yet, processing
    mock_create_assessment.assert_not_called()




@pytest.mark.django_db
def test_submit_answer_view_no_state(logged_in_standard_client):
    """Test submitting answer when no assessment state exists in session."""
    # Already logged in by fixture
    url = reverse("onboarding:onboarding_submit")
    response = logged_in_standard_client.post(
        url, json.dumps({"answer": "test"}), content_type="application/json"
    )

    assert response.status_code == 400
    response_json = response.json()
    assert "error" in response_json
    assert "No active assessment found" in response_json["error"]


@pytest.mark.django_db
def test_submit_answer_view_missing_answer(logged_in_standard_client):
    """Test submitting answer with missing 'answer' key in JSON."""
    # Already logged in by fixture
    url = reverse("onboarding:onboarding_submit")

    session = logged_in_standard_client.session
    session[settings.ASSESSMENT_STATE_KEY] = {"topic": "Test", "step": 1}
    session.save()

    response = logged_in_standard_client.post(
        url, json.dumps({"other_key": "value"}), content_type="application/json"
    )

    assert response.status_code == 400
    response_json = response.json()
    assert "error" in response_json
    assert (
        "Missing 'answer' or 'skip' flag in JSON payload." in response_json["error"]
    )


@pytest.mark.django_db
@patch("onboarding.views.get_ai_instance")
def test_submit_answer_view_evaluate_error(
    mock_get_ai, logged_in_standard_client
):
    """Test submitting answer when AI evaluation fails."""
    # Already logged in by fixture
    url = reverse("onboarding:onboarding_submit")
    user_answer = "Answer causing error"

    mock_ai_instance = MagicMock()
    current_state = {"topic": "EvalError", "step": 1, "questions_asked": ["Q1"]}
    mock_ai_instance.evaluate_answer.side_effect = Exception("Evaluation Failed")
    mock_get_ai.return_value = mock_ai_instance

    session = logged_in_standard_client.session
    session[settings.ASSESSMENT_STATE_KEY] = current_state
    session.save()
    response = logged_in_standard_client.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )

    response = logged_in_standard_client.post(
        url, json.dumps({"answer": user_answer}), content_type="application/json"
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "processing"
    assert "task_id" in response_json

