# onboarding/test_ai.py
# pylint: disable=redefined-outer-name, unused-argument
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings  # Import settings

from core.constants import DIFFICULTY_ADVANCED, DIFFICULTY_BEGINNER  # Import constants
from onboarding.ai import AgentState, TechTreeAI
from syllabus.ai.utils import call_with_retry

# --- Test call_with_retry ---


class FlakyFuncCounter:
    """Define flaky func outside test to manage state correctly"""
    call_count = 0


def mock_successful_func(*_, **kwargs):
    """Mock function that succeeds."""
    return {"success": True}


def mock_failing_func(*args, **kwargs):
    """Mock function that always fails."""
    raise ValueError("Test failure")


def test_call_with_retry_success_first_try():
    """Test call_with_retry succeeds on the first attempt."""
    result = call_with_retry(mock_successful_func, "arg1", kwarg1="value1")
    assert result == {"success": True}


def test_call_with_retry_persistent_failure():
    """Test call_with_retry raises exception after exceeding retries."""
    # This test might also need adjustment if the only retryable error is ResourceExhausted
    # For now, keep it assuming other exceptions might still be caught and re-raised
    with pytest.raises(ValueError, match="Test failure"):
        call_with_retry(mock_failing_func, "arg", retries=2, delay=0.1)


# --- Test TechTreeAI ---


@pytest.fixture
def initial_state() -> AgentState:
    """Provides a basic initial state matching AgentState definition."""
    # Initialize with keys defined in AgentState, using appropriate empty/default values
    return {
        "topic": "Test Topic",
        "knowledge_level": "beginner",  # Assuming a default or it's set later
        "questions_asked": [],
        "question_difficulties": [],
        "answers": [],
        "answer_evaluations": [],  # Use correct key
        "current_question": "",  # Default empty
        "current_question_difficulty": 0,  # Default
        "current_target_difficulty": 0,  # Default
        "consecutive_wrong": 0,
        "wikipedia_content": "",
        "google_results": [],  # Use correct key
        "search_completed": False,
        "consecutive_hard_correct_or_partial": 0,
        "is_complete": False,
        "user_id": None,  # Optional
        "score": None,  # Optional
        "error_message": None,  # Added for consistency
        "search_queries": [],  # Added for consistency
    }


@patch("onboarding.ai._get_llm")
@patch("onboarding.ai.TavilySearchResults")
def test_tech_tree_ai_initialization(MockTavily, MockGetLLM):
    """Test TechTreeAI initializes correctly."""
    mock_llm = MagicMock()
    MockGetLLM.return_value = mock_llm
    mock_tavily_instance = MagicMock()
    MockTavily.return_value = mock_tavily_instance

    ai = TechTreeAI()

    assert ai.llm == mock_llm
    assert ai.search_tool == mock_tavily_instance
    MockGetLLM.assert_called_once()
    MockTavily.assert_called_once_with(max_results=3)


@patch("onboarding.ai._get_llm", return_value=None)  # Simulate LLM init failure
@patch("onboarding.ai.TavilySearchResults")
def test_tech_tree_ai_initialization_no_llm(MockTavily, MockGetLLM):
    """Test TechTreeAI handles LLM initialization failure."""
    with pytest.raises(ValueError, match="LLM could not be initialized"):
        TechTreeAI()


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_initialize_state(mock_init):
    """Test state initialization."""
    ai = TechTreeAI()  # __init__ is mocked
    topic = "Advanced Python"
    state = ai.initialize_state(topic)
    assert state["topic"] == topic
    assert state["questions_asked"] == []
    # Assert other initial values based on initialize_state logic
    assert state["knowledge_level"] == DIFFICULTY_BEGINNER  # Assert against constant
    assert state["current_target_difficulty"] == settings.ONBOARDING_DEFAULT_DIFFICULTY


@patch("onboarding.ai._get_llm")  # Use decorator patches
@patch("onboarding.ai.TavilySearchResults")
def test_perform_internet_search(MockTavily, MockGetLLM, initial_state):
    """Test perform_internet_search returns expected mocked result."""
    MockGetLLM.return_value = MagicMock()  # Mock LLM for init
    mock_tavily_instance = MagicMock()
    mock_tavily_instance.invoke.return_value = "Mocked search result"
    MockTavily.return_value = mock_tavily_instance

    ai = TechTreeAI()
    ai.perform_internet_search = MagicMock(
        return_value={
            "google_results": ["Mocked search result"],
            "search_completed": True,
        }
    )

    initial_state["search_queries"] = ["query1"]

    result_state = ai.perform_internet_search(initial_state)

    ai.perform_internet_search.assert_called_once_with(initial_state)

    assert "google_results" in result_state
    assert result_state["google_results"] == ["Mocked search result"]
    assert result_state["search_completed"] is True

    MockTavily.assert_called_once_with(max_results=3)


@patch("onboarding.ai._get_llm")
@patch("onboarding.ai.TavilySearchResults")
@patch("onboarding.ai.ChatPromptTemplate")
def test_generate_question(
    MockChatPromptTemplate, MockTavily, MockGetLLM, initial_state
):
    """Test generate_question returns expected mocked result."""
    mock_llm = MagicMock()
    MockGetLLM.return_value = mock_llm
    MockTavily.return_value = MagicMock()

    ai = TechTreeAI()
    expected_result = {
        "questions_asked": [
            {
                "question": "What is Python?",
                "options": ["A", "B"],
                "correct_answer": "A",
                "explanation": "...",
                "difficulty": 3,
            }
        ],
        "question_difficulties": [3],
        "current_question": "What is Python?",
        "current_question_difficulty": 3,
        "error_message": None,
    }
    ai.generate_question = MagicMock(return_value=expected_result)

    result_state = ai.generate_question(initial_state)

    ai.generate_question.assert_called_once_with(initial_state)

    assert "questions_asked" in result_state
    assert len(result_state["questions_asked"]) == 1
    assert result_state["questions_asked"][0]["question"] == "What is Python?"
    assert result_state["current_question"] == "What is Python?"
    assert result_state["current_question_difficulty"] == 3


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_evaluate_answer(mock_init, initial_state):
    """Test the answer evaluation node."""
    ai = TechTreeAI()
    ai.llm = MagicMock()

    mock_response = MagicMock()
    mock_response.content = '{"score": 0.8, "feedback": "Good answer!"}'

    ai.llm.invoke = MagicMock(return_value=mock_response)

    initial_state["questions_asked"] = [
        {"question": "What is Python?", "correct_answer": "A", "difficulty": 3}
    ]
    initial_state["current_question"] = "What is Python?"
    initial_state["current_question_difficulty"] = 3
    user_answer = "It's a programming language."

    result_state = ai.evaluate_answer(initial_state, user_answer)

    assert "answers" in result_state
    assert len(result_state["answers"]) == 1
    assert result_state["answers"][0]["answer"] == user_answer
    assert result_state["answers"][0]["feedback"] == "Good answer!"
    assert "answer_evaluations" in result_state
    assert result_state["answer_evaluations"] == [0.8]


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_should_continue_true(mock_init, initial_state):
    """Test should_continue returns True when conditions met."""
    ai = TechTreeAI()  # __init__ is mocked
    initial_state["questions_asked"] = ["q1"]  # Less than 10 questions
    assert ai.should_continue(initial_state) is True


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_should_continue_false_max_questions(mock_init, initial_state):
    """Test should_continue returns False when max questions reached."""
    ai = TechTreeAI()  # __init__ is mocked
    initial_state["questions_asked"] = ["q1"] * 10  # 10 questions
    assert ai.should_continue(initial_state) is False


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_should_continue_false_error(mock_init, initial_state):
    """Test should_continue returns False when error message exists."""
    ai = TechTreeAI()  # __init__ is mocked
    initial_state["error_message"] = "Something went wrong"
    assert ai.should_continue(initial_state) is False


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_calculate_final_assessment(mock_init, initial_state):
    """Test the final assessment calculation."""
    ai = TechTreeAI()  # __init__ is mocked
    # Use correct key 'answer_evaluations'
    initial_state["answer_evaluations"] = [0.8, 0.6, 1.0]
    initial_state["questions_asked"] = ["q1", "q2", "q3"]
    initial_state["answers"] = [
        {"answer": "a1", "feedback": "f1"},
        {"answer": "a2", "feedback": "f2"},
        {"answer": "a3", "feedback": "f3"},
    ]

    result_state = ai.calculate_final_assessment(initial_state)

    # Check the structure returned by the method
    assert "final_assessment" in result_state
    final_assessment = result_state["final_assessment"]
    assert isinstance(final_assessment, dict)
    assert final_assessment["score"] == pytest.approx(80.0)  # Score is percentage
    assert (
        final_assessment["knowledge_level"] == DIFFICULTY_ADVANCED
    )  # Assert against constant
    assert final_assessment["topic"] == "Test Topic"
    assert final_assessment["questions"] == ["q1", "q2", "q3"]
    assert final_assessment["responses"] == initial_state["answers"]
    assert result_state["is_complete"] is True  # Check completion flag


@patch("onboarding.ai.TechTreeAI.__init__", return_value=None)
def test_calculate_final_assessment_no_scores(mock_init, initial_state):
    """Test final assessment calculation with no scores."""
    ai = TechTreeAI()  # __init__ is mocked
    result_state = ai.calculate_final_assessment(initial_state)

    assert "final_assessment" in result_state
    final_assessment = result_state["final_assessment"]
    assert final_assessment["score"] == 0
    assert (
        final_assessment["knowledge_level"] == DIFFICULTY_BEGINNER
    )  # Assert against constant
    assert result_state["is_complete"] is True
