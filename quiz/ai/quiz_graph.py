"""Defines the LangGraph structure for the end-of-lesson quiz."""

# pylint: disable=no-member

import logging
from typing import Any, Dict, List, Optional, TypedDict

from django.conf import settings
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.models import Lesson, LessonContent
from quiz.ai.prompts import (
    PROMPT_EVALUATE_ANSWER,
    PROMPT_GENERATE_QUESTION,
    PROMPT_RETRY_QUESTION,
)
from techtree_django.settings import FAST_MODEL


logger = logging.getLogger(__name__)


# Define the state for the quiz graph
class QuizState(TypedDict, total=False):
    """Represents the state of the quiz generation and execution process."""

    lesson_id: int
    user_id: int
    task_id: Optional[int]
    difficulty: str  # Difficulty level (e.g., 'Beginner', 'Intermediate', 'Advanced')
    current_question_index: int
    questions_asked: List[Dict[str, Any]]  # List of questions generated so far
    answers_given: List[
        Dict[str, Any]
    ]  # List of answers provided by the user and evaluation results
    incorrect_subtopics: List[str]  # Subtopics the user struggled with
    retry_count: int  # Number of retry attempts for the current quiz session
    final_score: Optional[float]
    quiz_complete: bool
    error_message: Optional[str]
    lesson_content: Optional[str]  # Store fetched lesson content
    user_answer: Optional[str]  # The user's answer for the current question
    waiting_for_user_input: bool  # Flag to indicate we're waiting for user input
    # Add options to the question structure within questions_asked
    # Each item in questions_asked will now be expected to have:
    # {"question_text": str, "options": List[str], "correct_answer": str, "subtopics": List[str], "difficulty": str}


# Initialize the LLM and parsers
# Adjust model name and configuration as needed
llm = ChatGoogleGenerativeAI(
    model=FAST_MODEL,
    google_api_key=settings.GEMINI_API_KEY,  # Explicitly pass API key
)  # type: ignore[call-arg]

json_parser = JsonOutputParser()

# Create prompt templates
generate_question_prompt = ChatPromptTemplate.from_template(PROMPT_GENERATE_QUESTION)
evaluate_answer_prompt = ChatPromptTemplate.from_template(PROMPT_EVALUATE_ANSWER)
retry_question_prompt = ChatPromptTemplate.from_template(PROMPT_RETRY_QUESTION)

# Create runnable chains
generate_question_chain = generate_question_prompt | llm | json_parser
evaluate_answer_chain = evaluate_answer_prompt | llm | json_parser
retry_question_chain = retry_question_prompt | llm | json_parser


# --- Node Functions ---


def initialize_quiz(state: QuizState) -> Dict[str, Any]:
    """Initializes the quiz state and fetches lesson content."""
    logger.info(
        "Initializing quiz for lesson %s, user %s",
        state.get("lesson_id"),
        state.get("user_id"),
    )

    lesson_id = state.get("lesson_id")

    # --- Check if lesson_id is provided ---
    if lesson_id is None:
        logger.error("Initialization failed: lesson_id is missing from the state.")
        return {"error_message": "Initialization failed: lesson_id is missing."}
    # --- End of check ---

    lesson_content_text = ""  # Initialize variable to store the actual text content

    try:
        # Fetch the Lesson instance
        lesson = Lesson.objects.get(id=lesson_id)  # pylint: disable=no-member

        # --- Corrected Content Fetching ---
        # Fetch the related LessonContent, preferably the completed one
        lesson_content_obj = LessonContent.objects.filter(  # pylint: disable=no-member
            lesson=lesson, status=LessonContent.StatusChoices.COMPLETED
        ).first()

        if lesson_content_obj:
            # Check if the content is a dictionary and extract the 'exposition'
            if isinstance(lesson_content_obj.content, dict):
                lesson_content_text = lesson_content_obj.content.get("exposition", "")
                if not lesson_content_text:
                    logger.warning(
                        "LessonContent (pk=%s) found but 'exposition' key is missing or empty.",
                        lesson_content_obj.pk,
                    )
            else:
                logger.warning(
                    "LessonContent (pk=%s) found but its 'content' field is not a dictionary (type: %s).",
                    lesson_content_obj.pk,
                    type(lesson_content_obj.content),
                )
        else:
            logger.warning(
                "No completed LessonContent found for Lesson with id %s.", lesson_id
            )
        # --- End of Corrected Content Fetching ---

    except Lesson.DoesNotExist:  # pylint: disable=no-member
        logger.error("Lesson with id %s not found.", lesson_id)
        return {"error_message": f"Lesson with id {lesson_id} not found."}
    except Exception as e:
        # Log the full exception details
        logger.error(
            "Error fetching lesson or its content for lesson_id %s: %s",
            lesson_id,
            e,
            exc_info=True,
        )
        return {"error_message": f"Error fetching lesson content: {e}"}

    # Return the initial state, now with the correctly fetched content text
    return {
        "lesson_id": lesson_id,  # Ensure lesson_id is passed through
        "user_id": state.get("user_id"),  # Ensure user_id is passed through
        "difficulty": state.get("difficulty"),  # Ensure difficulty is passed through
        "current_question_index": 0,
        "questions_asked": [],
        "answers_given": [],
        "incorrect_subtopics": [],
        "retry_count": 0,
        "final_score": None,
        "quiz_complete": False,
        "error_message": None,
        "lesson_content": lesson_content_text,  # Use the fetched text
        "user_answer": None,  # Clear user answer for the start
    }


def generate_question(state: QuizState) -> Dict[str, Any]:
    """Generates the next quiz question based on the current state."""
    logger.info(
        "Generating question %d for quiz.", state.get("current_question_index", 0) + 1
    )

    lesson_content = state.get("lesson_content", "")
    difficulty = state.get("difficulty", "Beginner")
    previous_subtopics = [
        st for q in state.get("questions_asked", []) for st in q.get("subtopics", [])
    ]
    incorrect_subtopics = state.get("incorrect_subtopics", [])

    try:
        # Use the appropriate chain based on whether it's a retry or initial question
        if state.get("retry_count", 0) > 0 and incorrect_subtopics:
            question_output = retry_question_chain.invoke(
                {
                    "incorrect_subtopics": ", ".join(incorrect_subtopics),
                    "lesson_content": lesson_content,
                    "difficulty": difficulty,
                }
            )
        else:
            question_output = generate_question_chain.invoke(
                {
                    "lesson_content": lesson_content,
                    "difficulty": difficulty,
                    "previous_subtopics": ", ".join(previous_subtopics),
                    "incorrect_subtopics": ", ".join(incorrect_subtopics),
                }
            )

        # Validate expected keys in the output, including 'options'
        if not all(
            k in question_output
            for k in [
                "question_text",
                "options",
                "correct_answer",
                "subtopics",
                "difficulty",
            ]
        ):
            # Log the actual output for debugging
            logger.error(
                f"LLM output missing required keys for question generation: {question_output}"
            )
            raise ValueError(
                "LLM output missing required keys for question generation."
            )

        # Ensure options is a list
        if not isinstance(question_output.get("options"), list):
            logger.error(
                f"LLM output 'options' is not a list: {question_output.get('options')}"
            )
            raise ValueError("LLM output 'options' is not a list.")

        new_question = {
            "question_text": question_output["question_text"],
            "options": question_output.get("options", []),  # Include options
            "correct_answer": question_output["correct_answer"],
            "subtopics": question_output.get(
                "subtopics", []
            ),  # Ensure subtopics is a list
            "difficulty": question_output.get("difficulty", difficulty),
        }

        questions_asked = state.get("questions_asked", []) + [new_question]
        current_question_index = state.get("current_question_index", 0) + 1

        return {
            "questions_asked": questions_asked,
            "current_question_index": current_question_index,
            "user_answer": None,  # Clear user answer for the new question
            "error_message": None,
        }

    except Exception as e:
        logger.error("Error generating question: %s", e, exc_info=True)
        return {"error_message": f"Error generating question: {e}"}


def evaluate_answer(state: QuizState) -> Dict[str, Any]:
    """Evaluates the user's answer to the last question."""
    logger.info(
        "Evaluating answer for question %d.", state.get("current_question_index", 1)
    )

    questions_asked = state.get("questions_asked", [])
    if not questions_asked:
        logger.error("No questions asked to evaluate.")
        return {"error_message": "No questions asked to evaluate."}

    last_question = questions_asked[-1]
    user_answer = state.get("user_answer")

    if user_answer is None:
        # This case should ideally not be reached if routing is correct,
        # but handle defensively.
        logger.error("Evaluate node called without a user answer.")
        return {"error_message": "No user answer provided for evaluation."}

    try:
        evaluation_output = evaluate_answer_chain.invoke(
            {
                "question_text": last_question.get("question_text", ""),
                "correct_answer": last_question.get("correct_answer", ""),
                "user_answer": user_answer,
                "question_subtopics": last_question.get("subtopics", []),
            }
        )

        # Validate expected keys in the output
        if not all(
            k in evaluation_output
            for k in ["is_correct", "feedback", "subtopics_covered", "subtopics_missed"]
        ):
            raise ValueError("LLM output missing required keys for answer evaluation.")

        evaluation_result = {
            "question_index": state.get("current_question_index", 1)
            - 1,  # Index of the question being evaluated
            "user_answer": user_answer,
            "is_correct": evaluation_output.get("is_correct", False),
            "feedback": evaluation_output.get("feedback", "No feedback provided."),
            "subtopics_covered": evaluation_output.get("subtopics_covered", []),
            "subtopics_missed": evaluation_output.get("subtopics_missed", []),
            "prompt_for_detail": evaluation_output.get("prompt_for_detail", False),
        }

        answers_given = state.get("answers_given", []) + [evaluation_result]
        incorrect_subtopics = list(
            set(
                state.get("incorrect_subtopics", [])
                + evaluation_result.get("subtopics_missed", [])
            )
        )

        return {
            "answers_given": answers_given,
            "incorrect_subtopics": incorrect_subtopics,
            "user_answer": None,  # Clear user answer after evaluation
            "error_message": None,
        }

    except Exception as e:
        logger.error("Error evaluating answer: %s", e, exc_info=True)
        return {"error_message": f"Error evaluating answer: {e}"}


def should_evaluate(state: QuizState) -> str:
    """Router: Decides whether to evaluate an answer or end the initial invocation."""
    user_answer = state.get("user_answer")
    current_question_index = state.get("current_question_index", 0)
    answers_given = state.get("answers_given", [])

    logger.info("Routing: Checking if evaluation is needed.")
    # If it's the first question generated and no answer is present yet
    if user_answer is None and current_question_index > 0 and not answers_given:
        logger.info("Routing: Initial state, no answer yet. Ending invocation.")
        return "end_initial_invocation"
    elif user_answer is not None:
        logger.info("Routing: User answer present. Proceeding to evaluation.")
        return "evaluate_answer"
    else:
        # This case might occur if generate_question fails or state is inconsistent
        logger.error(
            "Routing: Unexpected state in should_evaluate. Routing to record_result."
        )
        return "record_result"  # Route to record_result to handle potential errors


def route_after_evaluation(state: QuizState) -> str:
    """Router: Determines the next step AFTER evaluating an answer."""
    logger.info("Routing: Determining next step after evaluation.")

    current_question_index = state.get("current_question_index", 0)
    answers_given = state.get(
        "answers_given", []
    )  # Should exist if this router is called
    incorrect_subtopics = state.get("incorrect_subtopics", [])
    retry_count = state.get("retry_count", 0)
    error_message = state.get("error_message")  # Check for errors from evaluate_answer

    # If there was an error during evaluation, stop the quiz
    if error_message:
        logger.error("Routing: Error detected during evaluation, finalizing quiz.")
        return "record_result"

    # Check if the last answer was incorrect and if a retry is possible/needed
    if (
        answers_given
        and not answers_given[-1].get("is_correct", True)
        and incorrect_subtopics
        and retry_count < 1
    ):
        logger.info("Routing: Answer incorrect, initiating retry.")
        return "generate_retry_quiz"

    # Check if enough questions have been asked
    if current_question_index >= 5:
        logger.info("Routing: Reached maximum questions, recording result.")
        return "record_result"

    # Otherwise, generate the next question
    logger.info("Routing: Quiz continues, generating next question.")
    return "generate_question"


def end_initial_invocation(state: QuizState) -> QuizState:
    """Node: Ends the graph invocation after the first question is generated."""
    logger.info("Node: end_initial_invocation executed. Graph pausing.")
    # Return the state dictionary. The graph connects this node to END.
    # The processor receives this state and waits for the next task with the user's answer.
    return state


def record_result(state: QuizState) -> Dict[str, Any]:
    """Calculates the final quiz result and marks the quiz as complete."""
    logger.info("Recording quiz result.")

    # This node is now only called for actual completion or errors.
    # The initial state is handled by the 'should_evaluate' router and 'end_initial_invocation' node.

    answers_given = state.get("answers_given", [])

    # If there's an error, just finalize with the error
    if state.get("error_message"):
        logger.info("Quiz finalized with error: %s", state.get("error_message"))
        return {
            "final_score": 0.0,
            "quiz_complete": True,
            "error_message": state.get("error_message"),
        }

    # Normal quiz completion with score calculation
    total_questions = len(state.get("questions_asked", []))
    correct_answers = sum(
        1 for answer in answers_given if answer.get("is_correct", False)
    )

    final_score = (
        (correct_answers / total_questions) * 100 if total_questions > 0 else 0.0
    )

    logger.info("Quiz finished. Final score: %.2f%%", final_score)

    return {
        "final_score": final_score,
        "quiz_complete": True,
        "error_message": None,
    }


def generate_retry_quiz(state: QuizState) -> Dict[str, Any]:
    """Prepares the state for a retry quiz focusing on incorrectly answered subtopics."""
    logger.info("Preparing state for retry quiz.")

    # Increment retry count
    retry_count = state.get("retry_count", 0) + 1

    # Reset question/answer history for the retry round, but keep incorrect subtopics
    return {
        "current_question_index": 0,  # Reset index for the retry round
        "questions_asked": [],  # Clear previous questions
        "answers_given": [],  # Clear previous answers
        "retry_count": retry_count,
        "user_answer": None,  # Clear user answer
        "error_message": None,
        # incorrect_subtopics are carried over by the graph state
    }


# --- Graph Definition ---


def create_quiz_graph() -> CompiledStateGraph:
    """Creates and compiles the LangGraph for the quiz."""
    workflow = StateGraph(QuizState)

    # Add nodes
    workflow.add_node("initialize_quiz", initialize_quiz)
    workflow.add_node("generate_question", generate_question)
    workflow.add_node("evaluate_answer", evaluate_answer)
    workflow.add_node(
        "end_initial_invocation", end_initial_invocation
    )  # Node to end initial invocation
    workflow.add_node("record_result", record_result)
    workflow.add_node("generate_retry_quiz", generate_retry_quiz)

    # Define edges and entry point
    workflow.set_entry_point("initialize_quiz")
    workflow.add_edge("initialize_quiz", "generate_question")

    # After generating a question, route to check if we should evaluate or end
    workflow.add_conditional_edges(
        "generate_question",
        should_evaluate,  # Use the should_evaluate router
        {
            "evaluate_answer": "evaluate_answer",
            "end_initial_invocation": "end_initial_invocation",
            "record_result": "record_result",  # Handle potential error case from router
        },
    )

    # Conditional edge after evaluating an answer
    workflow.add_conditional_edges(
        "evaluate_answer",
        route_after_evaluation,  # Use the route_after_evaluation router
        {
            "generate_question": "generate_question",
            "generate_retry_quiz": "generate_retry_quiz",
            "record_result": "record_result",
        },
    )

    # After generating retry quiz state, generate the first question of the retry round
    workflow.add_edge("generate_retry_quiz", "generate_question")

    # End the graph after the initial invocation or after recording the final result
    workflow.add_edge("end_initial_invocation", END)
    workflow.add_edge("record_result", END)

    # Compile the graph
    app = workflow.compile()
    logger.info("Quiz graph compiled successfully.")
    return app


# Example usage (optional, for testing)
if __name__ == "__main__":
    graph = create_quiz_graph()
    print("Graph created. Ready for invocation.")
    # Example initial state for testing:
    # initial_state: QuizState = {
    #     'lesson_id': 1,
    #     'user_id': 123,
    #     'difficulty': 'Beginner',
    #     'current_question_index': 0,
    #     'questions_asked': [],
    #     'answers_given': [],
    #     'incorrect_subtopics': [],
    #     'retry_count': 0,
    #     'final_score': None,
    #     'quiz_complete': False,
    #     'error_message': None,
    #     'lesson_content': 'This is some lesson content about Python basics...',
    #     'user_answer': None,
    # }
    #
    # To run the first step (initialization and first question generation):
    # result = graph.invoke(initial_state)
    # print("First step result:", result)
    #
    # To run the next step with a user answer (assuming the graph is stateful or you pass the updated state):
    # next_state = result # Or load state from storage if async
    # next_state['user_answer'] = "User's answer here"
    # result_with_answer = graph.invoke(next_state)
    # print("Result after answer evaluation:", result_with_answer)
