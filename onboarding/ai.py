# onboarding/ai.py
"""
AI logic for the onboarding assessment using LangGraph.
Manages the flow of asking questions, evaluating answers, and determining user level.
"""
# pylint: disable=too-many-arguments, too-many-locals

import logging
import json
from typing import TypedDict, List, Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph
from django.conf import settings

from syllabus.ai.utils import call_with_retry  # Re-use retry logic
from .prompts import (
    ASSESSMENT_SYSTEM_PROMPT,
    GENERATE_QUESTION_PROMPT,
    EVALUATE_ANSWER_PROMPT,
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
        ) # type: ignore[call-arg]
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
            knowledge_level="beginner",  # Start assuming beginner
            questions_asked=[],
            question_difficulties=[],
            answers=[],
            answer_evaluations=[],
            current_question="",
            current_question_difficulty=settings.ONBOARDING_DEFAULT_DIFFICULTY,  # Use setting
            current_target_difficulty=settings.ONBOARDING_DEFAULT_DIFFICULTY,  # Use setting
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

    async def perform_internet_search(self, state: AgentState) -> Dict[str, Any]:
        """Node: Performs internet search based on the topic."""
        logger.info("Performing internet search for topic: %s", state["topic"])
        search_queries = state.get("search_queries", [])
        if not search_queries:
            # Generate search query if none provided (optional based on design)
            # For now, assume query generation happens elsewhere or is passed in
            logger.warning(
                "No search queries found in state for topic: %s", state["topic"]
            )
            query = state["topic"]  # Fallback to topic itself
        else:
            query = search_queries[-1]  # Use the latest query

        try:
            # Call synchronously as invoke seems to be sync in live env
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

    async def generate_question(self, state: AgentState) -> Dict[str, Any]:
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
        # Map numeric difficulty to a descriptive name
        difficulty_map = {1: "Beginner", 2: "Intermediate", 3: "Advanced"}
        difficulty_name = difficulty_map.get(target_difficulty, "Intermediate") # Default if somehow invalid

        # Format search results for the prompt context
        search_results_list = state.get("google_results", [])
        search_context = "\n\n".join(map(str, search_results_list)) if search_results_list else "No search results available."

        prompt_input = {
            "topic": state.get("topic", "Unknown Topic"),
            "knowledge_level": state.get("knowledge_level", "beginner"),
            "target_difficulty": target_difficulty,
            "difficulty_name": difficulty_name,
            "questions_asked_str": json.dumps(state.get("questions_asked", [])),
            "search_context": search_context,
        }

        try:
            # Call synchronously as invoke seems to be sync in live env
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
            new_difficulties = state.get("question_difficulties", []) + [
                question_data.get("difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY)
            ]

            return {
                "questions_asked": new_questions,
                "question_difficulties": new_difficulties,
                "current_question": question_data["question"],
                "current_question_difficulty": question_data.get(
                    "difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
                ),
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

    async def evaluate_answer(self, state: AgentState, answer: str) -> Dict[str, Any]:
        """Node: Evaluates the user's answer."""
        logger.info("Evaluating answer for topic: %s", state["topic"])
        if not self.llm:
            return {"error_message": "LLM not available"}

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ASSESSMENT_SYSTEM_PROMPT),
                ("human", EVALUATE_ANSWER_PROMPT),
            ]
        )
        chain = prompt | self.llm

        # Ensure current_question exists before proceeding
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

        prompt_input = {
            "topic": state.get("topic", "Unknown Topic"),
            "level": state.get("knowledge_level", "beginner"),
            "question": json.dumps(
                current_question_data
            ),  # Pass the full question data
            "user_answer": answer,
        }

        try:
            response = await call_with_retry(chain.invoke, prompt_input)
            content = str(response.content).strip()
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

            # Update consecutive wrong/correct counters based on score and difficulty
            consecutive_wrong = state.get("consecutive_wrong", 0)
            consecutive_hard_correct = state.get(
                "consecutive_hard_correct_or_partial", 0
            )
            current_difficulty = state.get(
                "current_question_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
            )

            if evaluation_data["score"] < 0.5:  # Threshold for wrong
                consecutive_wrong += 1
                consecutive_hard_correct = 0
            else:
                consecutive_wrong = 0
                if (
                    current_difficulty >= settings.ONBOARDING_HARD_DIFFICULTY_THRESHOLD
                    and evaluation_data["score"] >= 0.7
                ):  # Threshold for hard correct/partial
                    consecutive_hard_correct += 1
                else:
                    consecutive_hard_correct = (
                        0  # Reset if not hard or not mostly correct
                    )

            # Adjust target difficulty based on performance (simplified logic)
            target_difficulty = state.get(
                "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
            )
            if evaluation_data["score"] < 0.3 and target_difficulty > 1:
                target_difficulty -= 1
            elif evaluation_data["score"] > 0.8 and target_difficulty < 5:
                target_difficulty += 1

            return {
                "answers": new_answers,
                "answer_evaluations": new_evaluations,
                "consecutive_wrong": consecutive_wrong,
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
        # Then check other conditions
        if state.get("consecutive_wrong", 0) >= 3:
            logger.info("Ending assessment: 3 consecutive wrong answers.")
            return False
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

        # Determine final level (same logic as original)
        if score_percentage >= 75:
            final_level = "advanced"
        elif score_percentage >= 40:
            final_level = "intermediate"
        else:
            final_level = "beginner"

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
