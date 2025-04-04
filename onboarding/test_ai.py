# onboarding/test_ai.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, Any
from django.conf import settings # Import settings

from onboarding.ai import TechTreeAI, AgentState, call_with_retry

# Mark only async tests explicitly if needed, or rely on pytest-asyncio auto-detection
# pytestmark = pytest.mark.asyncio # Keep global mark for now

# --- Test call_with_retry ---

# Define flaky func outside test to manage state correctly
class FlakyFuncCounter:
    call_count = 0

@pytest.mark.asyncio # Mark individual async tests
async def mock_successful_async_func(*args, **kwargs):
    """Mock async function that succeeds."""
    return {"success": True}

@pytest.mark.asyncio # Mark individual async tests
async def mock_failing_async_func(*args, **kwargs):
    """Mock async function that always fails."""
    raise ValueError("Test failure")

# Removed mock_flaky_async_func as call_with_retry only retries ResourceExhausted now

@pytest.mark.asyncio # Mark individual async tests
async def test_call_with_retry_success_first_try():
    """Test call_with_retry succeeds on the first attempt."""
    result = await call_with_retry(mock_successful_async_func, "arg1", kwarg1="value1")
    assert result == {"success": True}

# Removed test_call_with_retry_success_after_failure as the retry logic changed

@pytest.mark.asyncio # Mark individual async tests
async def test_call_with_retry_persistent_failure():
    """Test call_with_retry raises exception after exceeding retries."""
    # This test might also need adjustment if the only retryable error is ResourceExhausted
    # For now, keep it assuming other exceptions might still be caught and re-raised
    with pytest.raises(ValueError, match="Test failure"):
        await call_with_retry(mock_failing_async_func, "arg", retries=2, delay=0.1)


# --- Test TechTreeAI ---

@pytest.fixture
def initial_state() -> AgentState:
    """Provides a basic initial state matching AgentState definition."""
    # Initialize with keys defined in AgentState, using appropriate empty/default values
    return {
        "topic": "Test Topic",
        "knowledge_level": "beginner", # Assuming a default or it's set later
        "questions_asked": [],
        "question_difficulties": [],
        "answers": [],
        "answer_evaluations": [], # Use correct key
        "current_question": "", # Default empty
        "current_question_difficulty": 0, # Default
        "current_target_difficulty": 0, # Default
        "consecutive_wrong": 0,
        "wikipedia_content": "",
        "google_results": [], # Use correct key
        "search_completed": False,
        "consecutive_hard_correct_or_partial": 0,
        "is_complete": False,
        "user_id": None, # Optional
        "score": None, # Optional
        "error_message": None, # Added for consistency
        "search_queries": [], # Added for consistency
    }

@pytest.mark.asyncio # Mark individual async tests
@patch('onboarding.ai._get_llm')
@patch('onboarding.ai.TavilySearchResults')
async def test_tech_tree_ai_initialization(MockTavily, MockGetLLM):
    """Test TechTreeAI initializes correctly."""
    mock_llm = MagicMock()
    MockGetLLM.return_value = mock_llm
    mock_tavily_instance = MagicMock()
    MockTavily.return_value = mock_tavily_instance

    ai = TechTreeAI()

    assert ai.llm == mock_llm
    assert ai.search_tool == mock_tavily_instance
    # Removed assertion for ai.graph as it's not an attribute of TechTreeAI
    MockGetLLM.assert_called_once()
    MockTavily.assert_called_once_with(max_results=3)

@pytest.mark.asyncio # Mark individual async tests
@patch('onboarding.ai._get_llm', return_value=None) # Simulate LLM init failure
@patch('onboarding.ai.TavilySearchResults')
async def test_tech_tree_ai_initialization_no_llm(MockTavily, MockGetLLM):
    """Test TechTreeAI handles LLM initialization failure."""
    with pytest.raises(ValueError, match="LLM could not be initialized"):
        TechTreeAI()

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_initialize_state(mock_init):
    """Test state initialization."""
    ai = TechTreeAI() # __init__ is mocked
    topic = "Advanced Python"
    state = ai.initialize_state(topic)
    assert state["topic"] == topic
    assert state["questions_asked"] == []
    # Assert other initial values based on initialize_state logic
    assert state["knowledge_level"] == "beginner"
    assert state["current_target_difficulty"] == settings.ONBOARDING_DEFAULT_DIFFICULTY

@pytest.mark.asyncio # Mark individual async tests
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None) # Mock init
@patch('onboarding.ai.call_with_retry', new_callable=AsyncMock) # Mock retry helper
async def test_perform_internet_search(mock_call_retry, mock_init, initial_state):
    """Test the internet search node."""
    ai = TechTreeAI() # __init__ is mocked
    # Manually assign a mock search tool as __init__ is bypassed
    ai.search_tool = AsyncMock()
    # Mock the return value of call_with_retry to be the actual expected result string
    mock_call_retry.return_value = "Mocked search result"

    initial_state["search_queries"] = ["query1"] # Add a query

    result_state = await ai.perform_internet_search(initial_state)

    # Assert call_with_retry was used, targeting the search tool's invoke
    mock_call_retry.assert_called_once()
    call_args, call_kwargs = mock_call_retry.call_args
    assert call_args[0] == ai.search_tool.invoke # Check it tried to call the tool's invoke
    assert call_args[1] == {"query": "query1"} # Check the argument passed to invoke

    assert "google_results" in result_state # Check correct key
    assert result_state["google_results"] == ["Mocked search result"] # Check correct key
    assert result_state["search_completed"] is True

@pytest.mark.asyncio # Mark individual async tests
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None) # Mock init
@patch('onboarding.ai.call_with_retry', new_callable=AsyncMock) # Mock retry helper
async def test_generate_question(mock_call_retry, mock_init, initial_state):
    """Test the question generation node."""
    ai = TechTreeAI() # __init__ is mocked
    # Manually assign mock LLM as __init__ is bypassed
    ai.llm = MagicMock()

    # Mock the response structure from call_with_retry (which wraps llm.invoke)
    mock_response = MagicMock()
    mock_response.content = '{"question": "What is Python?", "options": ["A", "B"], "correct_answer": "A", "explanation": "...", "difficulty": 3}'
    mock_call_retry.return_value = mock_response

    result_state = await ai.generate_question(initial_state)

    mock_call_retry.assert_called_once() # Check retry helper was called
    # Optionally check the chain passed to call_with_retry if needed

    assert "questions_asked" in result_state
    assert len(result_state["questions_asked"]) == 1
    assert result_state["questions_asked"][0]["question"] == "What is Python?"
    assert result_state["current_question"] == "What is Python?"
    assert result_state["current_question_difficulty"] == 3

@pytest.mark.asyncio # Mark individual async tests
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None) # Mock init
@patch('onboarding.ai.call_with_retry', new_callable=AsyncMock) # Mock retry helper
async def test_evaluate_answer(mock_call_retry, mock_init, initial_state):
    """Test the answer evaluation node."""
    ai = TechTreeAI() # __init__ is mocked
    ai.llm = MagicMock() # Manually assign mock LLM

    # Mock the response structure from call_with_retry
    mock_response = MagicMock()
    mock_response.content = '{"score": 0.8, "feedback": "Good answer!"}'
    mock_call_retry.return_value = mock_response

    # Set up state as if a question was just asked
    initial_state["questions_asked"] = [{"question": "What is Python?", "correct_answer": "A", "difficulty": 3}]
    initial_state["current_question"] = "What is Python?" # Ensure current question is set
    initial_state["current_question_difficulty"] = 3
    user_answer = "It's a programming language."

    result_state = await ai.evaluate_answer(initial_state, user_answer)

    mock_call_retry.assert_called_once() # Check retry helper was called

    assert "answers" in result_state
    assert len(result_state["answers"]) == 1
    assert result_state["answers"][0]["answer"] == user_answer
    assert result_state["answers"][0]["feedback"] == "Good answer!"
    assert "answer_evaluations" in result_state # Check correct key
    assert result_state["answer_evaluations"] == [0.8] # Check correct key

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_should_continue_true(mock_init, initial_state):
    """Test should_continue returns True when conditions met."""
    ai = TechTreeAI() # __init__ is mocked
    initial_state["questions_asked"] = ["q1"] # Less than 10 questions
    assert ai.should_continue(initial_state) is True

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_should_continue_false_max_questions(mock_init, initial_state):
    """Test should_continue returns False when max questions reached."""
    ai = TechTreeAI() # __init__ is mocked
    initial_state["questions_asked"] = ["q1"] * 10 # 10 questions
    assert ai.should_continue(initial_state) is False

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_should_continue_false_error(mock_init, initial_state):
    """Test should_continue returns False when error message exists."""
    ai = TechTreeAI() # __init__ is mocked
    initial_state["error_message"] = "Something went wrong"
    assert ai.should_continue(initial_state) is False

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_calculate_final_assessment(mock_init, initial_state):
    """Test the final assessment calculation."""
    ai = TechTreeAI() # __init__ is mocked
    # Use correct key 'answer_evaluations'
    initial_state["answer_evaluations"] = [0.8, 0.6, 1.0]
    initial_state["questions_asked"] = ["q1", "q2", "q3"]
    initial_state["answers"] = [
        {"answer": "a1", "feedback": "f1"},
        {"answer": "a2", "feedback": "f2"},
        {"answer": "a3", "feedback": "f3"}
    ]

    result_state = ai.calculate_final_assessment(initial_state)

    # Check the structure returned by the method
    assert "final_assessment" in result_state
    final_assessment = result_state["final_assessment"]
    assert isinstance(final_assessment, dict)
    assert final_assessment["score"] == pytest.approx(80.0) # Score is percentage
    assert final_assessment["knowledge_level"] == "advanced" # 80 >= 75
    assert final_assessment["topic"] == "Test Topic"
    assert final_assessment["questions"] == ["q1", "q2", "q3"]
    assert final_assessment["responses"] == initial_state["answers"]
    assert result_state["is_complete"] is True # Check completion flag

# This test is synchronous
@patch('onboarding.ai.TechTreeAI.__init__', return_value=None)
def test_calculate_final_assessment_no_scores(mock_init, initial_state):
    """Test final assessment calculation with no scores."""
    ai = TechTreeAI() # __init__ is mocked
    result_state = ai.calculate_final_assessment(initial_state)

    assert "final_assessment" in result_state
    final_assessment = result_state["final_assessment"]
    assert final_assessment["score"] == 0
    assert final_assessment["knowledge_level"] == "beginner"
    assert result_state["is_complete"] is True