"""
Processor for handling quiz interaction tasks.
"""

import logging
import uuid
from typing import Any, Dict, cast

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from core.models import UserProgress
from quiz.ai.quiz_graph import QuizState, create_quiz_graph
from taskqueue.models import AITask

logger = logging.getLogger(__name__)

channel_layer = get_channel_layer()


def process_quiz_task(task_id: uuid.UUID) -> None:
    """
    Processes a quiz interaction task by invoking the quiz LangGraph.

    Fetches the task, loads the state from UserProgress, invokes the graph,
    updates UserProgress with the new state, updates the task
    with results, and sends messages to the channel layer.
    """
    logger.info(f"Starting processing for quiz task {task_id}")

    try:
        # pylint: disable=no-member
        task = AITask.objects.get(task_id=task_id)

        user_id = task.user_id
        lesson_obj = task.lesson  # Get the Lesson object linked to the task

        if user_id is None or lesson_obj is None:
            logger.error(f"Task {task_id} is missing user_id or lesson object.")
            task.status = AITask.TaskStatus.FAILED
            task.result_data = {"error": "Task is missing user_id or lesson object."}
            task.save(update_fields=["status", "result_data", "updated_at"])
            return

        # --- Load the current state from UserProgress ---
        try:
            # Fetch UserProgress using user_id and lesson_obj
            user_progress = UserProgress.objects.get(
                user_id=user_id,
                lesson=lesson_obj,  # Use the lesson object here
                # Assuming syllabus is linked via lesson -> module -> syllabus for UserProgress lookup
                # This might need adjustment based on your UserProgress model structure
                # For simplicity, assuming lesson_obj and user_id are sufficient for lookup here
            )
            # Use the state from UserProgress as the starting state for the graph
            # Ensure it's treated as a mutable dictionary initially
            state_dict: Dict[str, Any] = user_progress.lesson_state_json or {}
            logger.info(f"Loaded initial quiz state from UserProgress: {state_dict}")

        except UserProgress.DoesNotExist:
            logger.error(
                f"UserProgress not found for user {user_id}, lesson {lesson_obj.pk} for task {task_id}."
            )
            task.status = AITask.TaskStatus.FAILED
            task.result_data = {"error": "UserProgress not found."}
            task.save(update_fields=["status", "result_data", "updated_at"])
            return
        except Exception as e:
            logger.error(
                f"Error loading UserProgress state for task {task_id}: {e}",
                exc_info=True,
            )
            task.status = AITask.TaskStatus.FAILED
            task.result_data = {"error": f"Error loading UserProgress state: {e}"}
            task.save(update_fields=["status", "result_data", "updated_at"])
            raise  # Re-raise to allow background_task to handle retries

        # Ensure required initial state keys are present, or handle missing ones
        # These are the keys expected by the graph's entry point
        # The consumer should ideally provide these, but add defaults defensively
        state_dict.setdefault(
            "lesson_id", lesson_obj.pk
        )  # Pass lesson ID (int) to state
        state_dict.setdefault("user_id", user_id)  # Pass user ID (int) to state
        # Difficulty might be in the loaded state, or need to be fetched if missing
        if "difficulty" not in state_dict:
            # Use the lesson object fetched from the task
            if (
                lesson_obj and lesson_obj.module and lesson_obj.module.syllabus
            ):  # Check if lesson, module, and syllabus exist
                state_dict["difficulty"] = lesson_obj.module.syllabus.level
            else:
                logger.warning(
                    f"Could not determine difficulty for task {task_id}, defaulting to Beginner."
                )
                state_dict["difficulty"] = "Beginner"

        # The user_answer should have been added by the consumer before saving the state
        # Ensure it's present for evaluation if expected
        # This check might be too simplistic; the graph's router should handle this.
        # Removing this defensive check here and relying on graph routing.
        # if "user_answer" not in state_dict and len(state_dict.get("questions_asked", [])) > len(state_dict.get("answers_given", [])):
        #      logger.warning(f"User answer missing in state for task {task_id} when expected.")
        #      state_dict["error_message"] = "User answer missing when expected."

        # Instantiate and invoke the quiz graph
        graph = create_quiz_graph()
        updated_state_dict: Dict[
            str, Any
        ]  # Use a generic dict for graph output initially

        try:
            # Invoke the graph with the current state loaded from UserProgress.
            # The graph handles the logic based on the state.
            logger.info(f"Invoking quiz graph with state: {state_dict}")
            graph_output = graph.invoke(state_dict)
            updated_state_dict = cast(
                Dict[str, Any], graph_output  # Cast output to Dict[str, Any]
            )
            logger.info(
                f"Graph invocation successful. Updated state dict: {updated_state_dict}"
            )

        except Exception as e:
            logger.error(
                f"Error during quiz graph execution for task {task_id}: {str(e)}",
                exc_info=True,
            )
            # Update the state_dict with the error message before saving
            # Avoid using ** expansion with Dict and TypedDict for mypy compatibility
            state_dict["error_message"] = f"Error during quiz processing: {e}"
            updated_state_dict = state_dict  # Use the state_dict with error
            # Mark task as failed and save state with error below
            task.status = AITask.TaskStatus.FAILED
            task.result_data = {"error": updated_state_dict["error_message"]}
            # Continue to state saving and message sending logic below

        # --- Update UserProgress with the new state from the graph ---
        # This is crucial for persisting the state between user interactions.
        try:
            # Cast the updated_state_dict to QuizState before saving
            user_progress.lesson_state_json = cast(QuizState, updated_state_dict)
            user_progress.save(update_fields=["lesson_state_json", "updated_at"])
            logger.info(
                f"UserProgress for user {user_id}, lesson {lesson_obj.pk} updated with new quiz state after graph invocation."
            )

        except Exception as e:
            logger.error(
                f"Error updating UserProgress after graph invocation for task {task_id}: {e}",
                exc_info=True,
            )
            # If UserProgress update fails, mark the task as failed as the state won't persist correctly.
            # Ensure task status is set to FAILED if not already due to graph error.
            if task.status != AITask.TaskStatus.FAILED:
                task.status = AITask.TaskStatus.FAILED
                task.result_data = {
                    "error": f"Error updating UserProgress after graph: {e}"
                }
                task.save(update_fields=["status", "result_data", "updated_at"])
            raise  # Re-raise to potentially trigger background_task retry

        # Prepare result data for the task (optional, mainly for debugging/logging task results)
        # Use the updated_state_dict for constructing task result and message payload
        task_result_data: Dict[str, Any] = {
            "updated_state": updated_state_dict,
            "quiz_complete": updated_state_dict.get("quiz_complete", False),
            "error": updated_state_dict.get("error_message"),
            "current_question": (
                updated_state_dict.get("questions_asked", [])[-1]
                if updated_state_dict.get("questions_asked")
                else None
            ),
            "last_evaluation": (
                updated_state_dict.get("answers_given", [])[-1]
                if updated_state_dict.get("answers_given")
                else None
            ),
            "final_score": updated_state_dict.get("final_score"),
        }
        task.result_data = task_result_data

        # --- Determine the message type and payload to send to the frontend ---
        message_type = None
        payload: Dict[str, Any] = {}
        current_step = "processing"  # Default

        if updated_state_dict.get("error_message"):
            current_step = "error"
            message_type = "quiz.error"
            payload = {"error": updated_state_dict["error_message"]}
            logger.info("Determined step: error")

        elif (
            updated_state_dict.get("quiz_complete", False)
            and updated_state_dict.get("final_score") is not None
        ):
            current_step = "final_result"
            message_type = "quiz.result"
            payload = {
                "score": updated_state_dict.get("final_score"),
                "total_questions": 5,  # Hardcoded
                "summary": updated_state_dict.get(
                    "quiz_summary", "Quiz completed!"
                ),  # Use quiz_summary from state if available
                "state": updated_state_dict,  # Send full state if needed by frontend
            }
            logger.info("Determined step: final_result")

        # Check if a new question was generated by comparing list lengths
        # This implies the graph successfully generated a question and updated the state
        elif len(updated_state_dict.get("questions_asked", [])) > len(
            updated_state_dict.get("answers_given", [])
        ):
            current_step = "question"
            message_type = "quiz.question"
            questions_asked = updated_state_dict.get("questions_asked", [])
            if questions_asked:
                current_question = questions_asked[-1]
                payload = {
                    "question_text": current_question.get("question_text", ""),
                    "options": current_question.get("options", []),
                    "question_index": updated_state_dict.get(
                        "current_question_index", 1
                    ),
                    "total_questions": 5,  # Hardcoded
                }
            else:
                # Should not happen if the condition is met, but handle defensively
                logger.error(
                    f"State indicates new question, but questions_asked is empty for task {task_id}"
                )
                current_step = "error"
                message_type = "quiz.error"
                payload = {"error": "Failed to retrieve new quiz question from state."}
            logger.info("Determined step: question")

        # Check if an answer was just evaluated (lengths are equal) and it was incorrect
        # This implies the graph evaluated an answer and the state reflects the result
        elif len(updated_state_dict.get("questions_asked", [])) > 0 and len(
            updated_state_dict.get("questions_asked", [])
        ) == len(updated_state_dict.get("answers_given", [])):
            last_evaluation = (
                updated_state_dict.get("answers_given", [])[-1]
                if updated_state_dict.get("answers_given")
                else None
            )
            if last_evaluation and not last_evaluation.get("is_correct", True):
                current_step = "feedback"
                message_type = "quiz.feedback"
                payload = {
                    "feedback": last_evaluation.get(
                        "feedback", "No feedback provided."
                    ),
                    "is_correct": False,
                    "question_index": updated_state_dict.get(
                        "current_question_index", 1
                    ),  # Use current index for feedback context
                    "total_questions": 5,  # Hardcoded
                }
                logger.info("Determined step: feedback (incorrect answer)")
            # If answer was correct and lengths are equal, the graph should have routed to generate_question
            # in the same invocation, resulting in len(questions_asked) > len(answers_given).
            # If we reach here with a correct answer and equal lengths, it might indicate an issue in graph routing or state updates.
            # For now, if lengths are equal and answer was correct, we don't send a specific message here.
            # The next message should be the next question, triggered by the next user input.
            elif last_evaluation and last_evaluation.get("is_correct", True):
                logger.info(
                    "Determined step: processing (correct answer, waiting for next input)"
                )
                current_step = "processing"  # Stay in processing, no message needed until next question is generated

            else:
                # Should not happen in normal flow if lengths are equal and > 0
                logger.warning(
                    f"Unexpected state after evaluation for task {task_id}. questions={len(updated_state_dict.get('questions_asked', []))}, answers={len(updated_state_dict.get('answers_given', []))}"
                )
                current_step = "processing"  # Default

        # Send message to channel layer if a message type was determined
        if message_type and channel_layer:
            # Use the lesson_obj primary key for the group name
            group_name = f"lesson_chat_{lesson_obj.pk}"
            logger.info(
                f"Sending message to chat group: {group_name} with type {message_type}"
            )
            try:
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        "type": message_type,
                        "payload": payload,
                    },
                )
                logger.info(
                    f"Message sent to group {group_name} with type {message_type}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to send message to channel layer group {group_name}: {e}",
                    exc_info=True,
                )
        elif not channel_layer:
            logger.warning("Channel layer is not configured. Skipping message send.")
        else:
            logger.warning(
                f"No message type determined for step: {current_step} for task {task_id}"
            )

        # --- Final Task Status Update ---
        # Use a transaction to ensure atomicity of the final task status update
        with transaction.atomic():
            # Check completion/error status from the updated state dictionary
            if (
                updated_state_dict.get("quiz_complete", False)
                and updated_state_dict.get("final_score") is not None
            ):
                logger.info(
                    f"Quiz task {task_id} indicates quiz completion. Marking task as completed."
                )
                task.status = AITask.TaskStatus.COMPLETED
                task.save(update_fields=["status", "result_data", "updated_at"])
                logger.info(f"Task {task_id} marked as COMPLETED.")

            elif updated_state_dict.get("error_message"):
                logger.info(
                    f"Quiz task {task_id} indicates an error. Marking task as failed."
                )
                task.status = AITask.TaskStatus.FAILED
                task.save(update_fields=["status", "result_data", "updated_at"])
                logger.info(f"Task {task_id} marked as FAILED.")

            else:
                # If quiz is not complete and no error, the task is still considered processing
                # We save the result_data and updated_at.
                # The background_task library manages the task status based on successful execution.
                task.save(update_fields=["result_data", "updated_at"])
                logger.info(
                    f"Quiz task {task_id} processing step completed. Quiz not yet complete. Task state saved."
                )
        # --- End Final Task Status Update ---

    except AITask.DoesNotExist:
        logger.error(f"Task with id {task_id} not found during processing.")
        # This might be handled by the background_task library's internal error handling
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during processing of quiz task {task_id}: {str(e)}",
            exc_info=True,
        )
        # Re-raise to allow background_task to handle task status update on exception
        raise
