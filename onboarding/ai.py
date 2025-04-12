# onboarding/ai.py
"""
AI logic for the onboarding assessment using LangChain.
Manages the flow of asking questions, evaluating answers, and determining user level.
"""
# pylint: disable=too-many-arguments, too-many-locals

import json
import logging
import time
from typing import Any, Dict, List, Optional, TypedDict

from django.conf import settings
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from core.constants import DIFFICULTY_GOOD_KNOWLEDGE  # Changed from intermediate
from core.constants import DIFFICULTY_ADVANCED, DIFFICULTY_BEGINNER

from .prompts import (
    ASSESSMENT_SYSTEM_PROMPT,
    EVALUATE_ANSWER_PROMPT,
    GENERATE_QUESTION_PROMPT,
)

logger = logging.getLogger(__name__)


# --- State Definition ---
# This represents the state managed by the Django view/session
class AgentState(
    TypedDict, total=False
):  # Use total=False to allow optional keys easily
    """LangGraph-style state dictionary for onboarding assessment."""

    # Required keys (or set during initialization)
    topic: str
    knowledge_level: str
    step: int  # Track current step/question number
    questions_asked: List[str]
    question_difficulties: List[int]
    answers: List[str]
    answer_evaluations: List[float]
    current_question: str
    current_question_difficulty: int
    current_target_difficulty: int
    consecutive_wrong: int
    wikipedia_content: str
    consecutive_wrong_at_current_difficulty: (
        int  # New: Track wrongs at the *current* difficulty
    )

    google_results: List[str]
    search_completed: bool
    consecutive_hard_correct_or_partial: int
    is_complete: bool
    # Optional keys
    user_id: Optional[int]  # Added
    score: Optional[float]  # Added
    # Added for consistency with tests and potential error handling
    error_message: Optional[str]
    search_queries: Optional[List[str]]  # Added based on test usage
    final_assessment: Optional[Dict[str, Any]]  # Added for final results
    feedback: Optional[str]  # Added for view usage


# --- Helper Functions ---

# Remove local definition, use imported version from syllabus.ai.utils


def _get_llm(
    model_key="FAST_MODEL", temperature=0.2
) -> Optional[ChatGoogleGenerativeAI]:
    """Gets the LLM instance based on settings."""
    api_key = settings.GEMINI_API_KEY
    model_name = getattr(settings, model_key, None)

    if not api_key:
        logger.error("GEMINI_API_KEY not found in settings.")
        return None
    if not model_name:
        logger.error("%s not found in settings.", model_key)
        return None

    try:
        logger.info("TechTreeAI: Using %s '%s' for onboarding.", model_key, model_name)
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            convert_system_message_to_human=True,
        )  # type: ignore[call-arg]
    except Exception as e:
        logger.error(
            "Failed to initialize ChatGoogleGenerativeAI: %s", e, exc_info=True
        )
        return None


# --- TechTreeAI Class ---


class TechTreeAI:
    """Encapsulates the AI logic for the onboarding assessment."""

    def __init__(self) -> None:
        """Initializes the AI components."""
        self.llm = _get_llm()
        if not self.llm:
            raise ValueError("LLM could not be initialized.")

        try:
            self.search_tool = TavilySearchResults(max_results=3)
            logger.info("TechTreeAI: Tavily client configured.")
        except Exception as e:
            logger.error(
                "Failed to initialize TavilySearchResults: %s", e, exc_info=True
            )
            raise ValueError("Search tool could not be initialized.") from e

    def initialize_state(self, topic: str) -> AgentState:
        """Creates the initial state for a new assessment."""
        logger.info("Initializing assessment state for topic: %s", topic)
        # Ensure all keys defined in AgentState are present
        return AgentState(
            topic=topic,
            knowledge_level=DIFFICULTY_BEGINNER,  # Use constant display value
            questions_asked=[],
            question_difficulties=[],
            answers=[],
            answer_evaluations=[],
            current_question="",
            current_question_difficulty=settings.ONBOARDING_DEFAULT_DIFFICULTY,  # Use setting
            current_target_difficulty=settings.ONBOARDING_DEFAULT_DIFFICULTY,  # Use setting
            consecutive_wrong_at_current_difficulty=0,
            consecutive_wrong=0,
            wikipedia_content="",
            google_results=[],
            search_completed=False,
            consecutive_hard_correct_or_partial=0,
            is_complete=False,
            error_message=None,
            search_queries=[],  # Initialize explicitly
            user_id=None,
            score=None,
        )

    def perform_internet_search(self, state: AgentState) -> Dict[str, Any]:
        """Node: Performs internet search based on the topic."""
        logger.info("Performing internet search for topic: %s", state["topic"])
        search_queries = state.get("search_queries", [])
        if not search_queries:
            # Generate search query if none provided (optional based on design)
            logger.warning(
                "No search queries found in state for topic: %s", state["topic"]
            )
            query = state["topic"]  # Fallback to topic itself
        else:
            query = search_queries[-1]  # Use the latest query

        try:
            search_results = self.search_tool.invoke({"query": query})
            logger.info("Search successful for query: %s", query)
            # Append results, don't overwrite
            existing_results = state.get("google_results", [])
            # Ensure search_results is treated as a list before concatenation
            if not isinstance(search_results, list):
                # Wrap non-list in list, handle None/empty string etc.
                search_results_list = [search_results] if search_results else []
            else:
                search_results_list = search_results

            updated_results = existing_results + search_results_list
            return {"google_results": updated_results, "search_completed": True}
        except Exception as e:
            logger.error(
                "Internet search failed for query '%s': %s", query, e, exc_info=True
            )
            return {
                "error_message": f"Search failed: {e}",
                "search_completed": True,
            }  # Mark search as completed even on error

    def generate_question(self, state: AgentState) -> Dict[str, Any]:
        """Node: Generates the next assessment question."""
        logger.info("Generating assessment question for topic: %s", state["topic"])
        if not self.llm:
            return {"error_message": "LLM not available"}

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ASSESSMENT_SYSTEM_PROMPT),
                ("human", GENERATE_QUESTION_PROMPT),
            ]
        )
        chain = prompt | self.llm

        # Prepare input, ensuring all keys expected by the prompt are present
        target_difficulty = state.get(
            "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
        )
        # Map numeric difficulty (assuming 1=Easy, 2=Medium, 3=Hard from settings) to display names
        difficulty_map = {
            1: DIFFICULTY_BEGINNER,
            2: DIFFICULTY_GOOD_KNOWLEDGE,
            3: DIFFICULTY_ADVANCED,
        }
        difficulty_name = difficulty_map.get(
            target_difficulty,
            DIFFICULTY_GOOD_KNOWLEDGE,  # Default if somehow invalid (use constant)
        )

        # Format search results for the prompt context
        search_results_list = state.get("google_results", [])
        search_context = "No search results available."
        if search_results_list:
            search_context = "\n\n".join(map(str, search_results_list))

        prompt_input = {
            "topic": state.get("topic", "Unknown Topic"),
            "knowledge_level": state.get(
                "knowledge_level", DIFFICULTY_BEGINNER
            ),  # Use constant
            "target_difficulty": target_difficulty,
            "difficulty_name": difficulty_name,
            "questions_asked_str": json.dumps(state.get("questions_asked", [])),
            "search_context": search_context,
        }

        try:
            response = chain.invoke(prompt_input)
            content = str(response.content).strip()
            logger.debug("Raw question generation response: %s", content)

            # Clean potential markdown fences
            if content.startswith("```json"):
                content = content.removeprefix("```json").removesuffix("```").strip()
            elif content.startswith("```"):
                content = content.removeprefix("```").removesuffix("```").strip()

            question_data = json.loads(content)

            if not isinstance(question_data, dict) or not question_data.get("question"):
                raise ValueError(
                    "LLM response did not contain a valid question structure."
                )

            logger.info("Successfully generated question for topic: %s", state["topic"])

            # Update state
            new_questions = state.get("questions_asked", []) + [question_data]
            # Ensure difficulty from LLM is treated as int
            # Always use the intended target difficulty from state, not the LLM's suggestion
            current_difficulty_int = int(state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY))
            # Validate range (0-3 based on constants)
            if not 0 <= current_difficulty_int <= 3:
                logger.warning(
                    f"Target difficulty '{current_difficulty_int}' out of range, defaulting "
                    f"to {settings.ONBOARDING_DEFAULT_DIFFICULTY}."
                )
                current_difficulty_int = settings.ONBOARDING_DEFAULT_DIFFICULTY

            new_difficulties = state.get("question_difficulties", []) + [
                current_difficulty_int
            ]

            return {
                "questions_asked": new_questions,
                "question_difficulties": new_difficulties,
                "current_question": question_data["question"],
                "current_question_difficulty": current_difficulty_int,  # Use the validated integer
                "error_message": None,  # Clear previous errors
            }
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON from question generation response: %s\nContent: %s",
                e,
                content,
                exc_info=True,
            )
            return {"error_message": f"AI response parsing error: {e}"}
        except Exception as e:
            logger.error("Failed to generate question: %s", e, exc_info=True)
            return {"error_message": f"AI question generation failed: {e}"}

    def evaluate_answer(self, state: AgentState, answer: str) -> Dict[str, Any]:
        """Node: Evaluates the user's answer."""
        logger.info("Evaluating answer for topic: %s", state["topic"])
        if not self.llm:
            return {"error_message": "LLM not available"}

        # --- Manually Format Prompt to bypass potential template parsing issues ---
        current_question_data = (
            state.get("questions_asked", [])[-1]
            if state.get("questions_asked")
            else None
        )
        if not current_question_data or not isinstance(current_question_data, dict):
            logger.error(
                "Cannot evaluate answer: No valid current question found in state."
            )
            return {
                "error_message": "Internal error: Could not find the question to evaluate."
            }

        search_results_list = state.get("google_results", [])
        search_context = "No search results available."
        if search_results_list:
            search_context = "\n\n".join(map(str, search_results_list))

        topic = state.get("topic", "Unknown Topic")
        current_question_str = current_question_data.get(
            "question", "Error retrieving question"
        )

        # Use a local copy of the imported prompt string to isolate formatting
        prompt_string_copy = str(EVALUATE_ANSWER_PROMPT)  # Create a copy

        formatted_human_prompt = prompt_string_copy.format(
            topic=topic,
            current_question=current_question_str,
            answer=answer,
            search_context=search_context,
        )
        # Create messages manually using message objects
        messages = [
            SystemMessage(content=ASSESSMENT_SYSTEM_PROMPT.format(topic=topic)),
            HumanMessage(content=formatted_human_prompt),
        ]

        # Create a new chain instance with the manually created messages (or just invoke LLM directly)
        # Note: Recreating the chain/prompt might be less efficient if done repeatedly
        # prompt_obj = ChatPromptTemplate.from_messages(messages) # Option 1: Use formatted messages
        # chain = prompt_obj | self.llm

        try:
            max_attempts = 3
            last_exception = None
            content = "NOT GENERATED"
            for attempt in range(1, max_attempts + 1):
                try:
                    response = self.llm.invoke(messages)
                    content = str(response.content).strip()
                    break
                except Exception as e:
                    logger.warning(f"Attempt {attempt} failed during LLM call: {e}")
                    last_exception = e
                    if attempt < max_attempts:

                        time.sleep(1 * attempt)  # simple backoff
                    else:
                        raise last_exception

            logger.debug("Raw answer evaluation response: %s", content)

            # Clean potential markdown fences
            if content.startswith("```json"):
                content = content.removeprefix("```json").removesuffix("```").strip()
            elif content.startswith("```"):
                content = content.removeprefix("```").removesuffix("```").strip()

            evaluation_data = json.loads(content)

            if (
                not isinstance(evaluation_data, dict)
                or "score" not in evaluation_data
                or "feedback" not in evaluation_data
            ):
                raise ValueError(
                    "LLM response did not contain valid evaluation structure (score, feedback)."
                )

            logger.info("Successfully evaluated answer for topic: %s", state["topic"])

            # Update state
            new_answers = state.get("answers", []) + [
                {"answer": answer, "feedback": evaluation_data["feedback"]}
            ]
            new_evaluations = state.get("answer_evaluations", []) + [
                evaluation_data["score"]
            ]

            # --- DEBUG LOGGING: Before difficulty adjustment ---
            logger.info(
                f"[DEBUG] Evaluating answer: '{answer[:50]}...' | Score: {evaluation_data.get('score')} | "
                f"Feedback: '{evaluation_data.get('feedback', '')[:50]}...'"
            )
            logger.info(
                f"[DEBUG] State before adjustment: Target Difficulty={state.get('current_target_difficulty')}, "
                f"Consecutive Wrong @ Difficulty={state.get('consecutive_wrong_at_current_difficulty')}"
            )
            # --- END DEBUG LOGGING ---

            # --- New Difficulty Adjustment Logic ---
            score = evaluation_data["score"]
            # Get current state values or defaults
            target_difficulty = state.get(
                "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
            )
            consecutive_wrong_at_difficulty = state.get(
                "consecutive_wrong_at_current_difficulty", 0
            )
            consecutive_hard_correct = state.get(
                "consecutive_hard_correct_or_partial", 0
            )
            min_difficulty = 0  # Match constants.py (Beginner=0)
            max_difficulty = 3  # Match constants.py (Advanced=3)

            original_difficulty = target_difficulty  # Store original for comparison

            if score < 0.5:  # Incorrect answer
                consecutive_wrong_at_difficulty += 1
                consecutive_hard_correct = 0  # Reset correct counter

                if (
                    consecutive_wrong_at_difficulty >= 2
                    and target_difficulty > min_difficulty
                ):
                    target_difficulty -= 1
                    logger.info(
                        f"Difficulty decreased to {target_difficulty} due to 2 consecutive wrongs."
                    )
                    consecutive_wrong_at_difficulty = (
                        0  # Reset counter after difficulty change
                    )
            else:  # Correct or partially correct answer
                consecutive_wrong_at_difficulty = 0  # Reset wrong counter

                # Check for increasing difficulty (only if correct/partial)
                if score > 0.8 and target_difficulty < max_difficulty:
                    target_difficulty += 1
                    logger.info(
                        f"Difficulty increased to {target_difficulty} due to high score."
                    )
                # Check for consecutive hard correct (existing logic)
                current_question_difficulty = state.get(
                    "current_question_difficulty",
                    settings.ONBOARDING_DEFAULT_DIFFICULTY,
                )
                if (
                    current_question_difficulty
                    >= settings.ONBOARDING_HARD_DIFFICULTY_THRESHOLD
                    and score >= 0.7
                ):
                    consecutive_hard_correct += 1
                else:
                    consecutive_hard_correct = (
                        0  # Reset if not hard or not mostly correct
                    )

            # Resetting the counter is handled within the if/else block above
            # when difficulty decreases or answer is correct.
            # Removing the general reset based on any difficulty change.

            logger.info(
                f"[DEBUG] Difficulty Adjustment: Score={score:.2f}, "
                f"Original Difficulty={original_difficulty}, New Difficulty={target_difficulty}, "
                f"Consecutive Wrong @ Difficulty={consecutive_wrong_at_difficulty}, "
                f"Consecutive Hard Correct={consecutive_hard_correct}"
            )
            return {
                "answers": new_answers,
                "answer_evaluations": new_evaluations,
                # Return the new state variables
                "consecutive_wrong_at_current_difficulty": consecutive_wrong_at_difficulty,
                "consecutive_hard_correct_or_partial": consecutive_hard_correct,
                "current_target_difficulty": target_difficulty,
                "error_message": None,  # Clear previous errors
            }
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON from evaluation response: %s\nContent: %s",
                e,
                content,
                exc_info=True,
            )
            return {"error_message": f"AI response parsing error: {e}"}
        except Exception as e:
            logger.error("Failed to evaluate answer: %s", e, exc_info=True)
            return {"error_message": f"AI evaluation failed: {e}"}

    def should_continue(self, state: AgentState) -> bool:
        """Determines if the assessment should continue based on state."""
        # Check for error first
        if state.get("error_message"):
            logger.info("Ending assessment due to error state.")
            return False
        # --- New Termination Logic ---
        min_difficulty = 0  # Match constants.py (Beginner=0)
        consecutive_wrong_at_difficulty = state.get(
            "consecutive_wrong_at_current_difficulty", 0
        )
        current_difficulty = state.get(
            "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
        )

        # Stop if 2 wrong at the easiest difficulty level
        if (
            consecutive_wrong_at_difficulty >= 2
            and current_difficulty == min_difficulty
        ):
            logger.info(
                f"Ending assessment: {consecutive_wrong_at_difficulty} consecutive wrong "
                f"answers at easiest difficulty ({min_difficulty})."
            )
            # Optionally add a flag to state here if calculate_final_assessment needs it
            # state['stopped_at_easiest'] = True
            return False

        # Keep other conditions
        if state.get("consecutive_hard_correct_or_partial", 0) >= 3:
            logger.info(
                "Ending assessment: 3 consecutive hard correct/partial answers."
            )
            return False
        if len(state.get("questions_asked", [])) >= 10:  # Max 10 questions
            logger.info("Ending assessment: Maximum questions reached.")
            return False
        logger.info("Continuing assessment.")
        return True

    def calculate_final_assessment(self, state: AgentState) -> Dict[str, Any]:
        """Calculates the final assessment results based on the completed state."""
        logger.info("Calculating final assessment results.")
        evaluations = state.get("answer_evaluations", [])
        total_score = sum(evaluations)
        max_possible_score = len(state.get("questions_asked", []))
        score_percentage = (
            (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0
        )

        # Determine final level
        min_difficulty = 0  # Match constants.py (Beginner=0)
        consecutive_wrong_at_difficulty = state.get(
            "consecutive_wrong_at_current_difficulty", 0
        )
        current_difficulty = state.get(
            "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
        )

        # Check if assessment stopped due to 2 wrong at easiest level
        if (
            consecutive_wrong_at_difficulty >= 2
            and current_difficulty == min_difficulty
        ):
            final_level = DIFFICULTY_BEGINNER  # Use constant
            logger.info(
                f"Assigning '{DIFFICULTY_BEGINNER}' level due to stopping at easiest difficulty."
            )
        else:
            # Original score-based logic
            if score_percentage >= 75:
                final_level = DIFFICULTY_ADVANCED  # Use constant
            elif score_percentage >= 40:
                final_level = DIFFICULTY_GOOD_KNOWLEDGE  # Use constant
            else:
                final_level = DIFFICULTY_BEGINNER  # Use constant

        # --- DEBUG LOGGING: Final Assessment Path ---
        if (
            consecutive_wrong_at_difficulty >= 2
            and current_difficulty == min_difficulty
        ):
            logger.info(
                "[DEBUG] Final level determined by: Early termination at easiest difficulty."
            )
        else:
            logger.info(
                f"[DEBUG] Final level determined by: Score percentage ({score_percentage:.2f}%)."
            )
        # --- END DEBUG LOGGING ---
        logger.info(
            f"Final Assessment - Level: {final_level}, Score: {score_percentage:.2f}%"
        )
        # Return results nested under 'final_assessment' key
        final_assessment_data = {
            "knowledge_level": final_level,
            "score": score_percentage,
            "topic": state.get("topic"),
            "questions": state.get("questions_asked"),
            "responses": state.get(
                "answers"
            ),  # Assuming 'answers' holds response dicts
        }
        # Return the updated state including the nested final assessment
        return {**state, "final_assessment": final_assessment_data, "is_complete": True}
