"""
Background task definitions for the taskqueue app.
"""
# pylint: disable=no-member

import logging
import time
from datetime import timedelta
from functools import wraps

from background_task import background
from background_task.models import Task as BGTask
from django.conf import settings
from django.utils import timezone

from taskqueue.processors.interaction_processor import process_lesson_interaction
from taskqueue.processors.lesson_processor import process_lesson_content
from taskqueue.processors.onboarding_processor import process_onboarding_assessment
from taskqueue.processors.syllabus_utils import process_syllabus_generation

from .models import AITask

# Configure logger
logger = logging.getLogger(__name__)

# Create a metrics logger for task monitoring
metrics_logger = logging.getLogger("taskqueue.metrics")


def log_task_metrics(func):
    """
    Decorator to log task execution metrics.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        task_id = args[0] if args else kwargs.get("task_id")
        start_time = time.time()

        try:
            # Log task start
            metrics_logger.info(f"Task {task_id} started")

            # Execute the task
            result = func(*args, **kwargs)

            # Calculate execution time
            execution_time = time.time() - start_time

            # Log task completion
            metrics_logger.info(
                f"Task {task_id} completed successfully in {execution_time:.2f} seconds"
            )

            return result

        except Exception as e:
            # Calculate execution time even for failed tasks
            execution_time = time.time() - start_time

            # Log task failure
            metrics_logger.error(
                f"Task {task_id} failed after {execution_time:.2f} seconds: {str(e)}"
            )

            # Re-raise the exception
            raise

    return wrapper


@background(schedule=0)
def dummy_task():
    """
    A simple background task for testing the worker process.
    """
    logger.info("Dummy background task executed successfully.")


@background(schedule=0)
@log_task_metrics
def process_ai_task(task_id):
    """
    Process an AI task from the queue.

    This is the main entry point for all background AI tasks. It retrieves the task
    from the database, routes it to the appropriate processor based on task type,
    and handles errors and retries.

    Args:
        task_id: The UUID of the task to process
    """
    try:
        # Get the task from the database
        task = AITask.objects.get(task_id=task_id)

        # Update status to processing
        task.status = AITask.TaskStatus.PROCESSING
        task.attempt_count += 1
        task.save(update_fields=["status", "attempt_count", "updated_at"])

        logger.info(
            f"Processing task {task_id} of type {task.task_type}, attempt {task.attempt_count}"
        )

        # Route to appropriate processor based on task type
        if task.task_type == AITask.TaskType.SYLLABUS_GENERATION:
            result = process_syllabus_generation(task)
        elif task.task_type == AITask.TaskType.LESSON_CONTENT:
            result = process_lesson_content(task)
        elif task.task_type == AITask.TaskType.LESSON_INTERACTION:
            result = process_lesson_interaction(task)
        elif task.task_type == AITask.TaskType.ONBOARDING_ASSESSMENT:
            result = process_onboarding_assessment(task)
        else:
            logger.error(
                f"Unknown task type encountered: {task.task_type!r}. "
                f"Available types: {[t for t in AITask.TaskType.values]}"
            )
            raise ValueError(f"Unknown task type: {task.task_type}")

        # Update task with result
        task.result_data = result
        task.status = AITask.TaskStatus.COMPLETED
        task.save(update_fields=["result_data", "status", "updated_at"])

        logger.info(f"Task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"Error processing task {task_id}: {str(e)}", exc_info=True)

        try:
            task = AITask.objects.get(task_id=task_id)
            task.error_message = str(e)

            # Implement retry logic with exponential backoff
            max_attempts = getattr(settings, "MAX_ATTEMPTS", 3)

            if task.attempt_count < max_attempts:
                # Calculate backoff time: 5min, 20min, 80min, etc.
                backoff_minutes = 5 * (4 ** (task.attempt_count - 1))
                task.status = AITask.TaskStatus.PENDING
                task.save(update_fields=["error_message", "status", "updated_at"])

                # Reschedule the task
                process_ai_task(task_id, schedule=timedelta(minutes=backoff_minutes))
                logger.info(
                    f"Rescheduled task {task_id} for retry in {backoff_minutes} minutes"
                )
            else:
                # Max retries reached, mark as failed
                task.status = AITask.TaskStatus.FAILED
                task.save(update_fields=["error_message", "status", "updated_at"])
                logger.error(
                    f"Task {task_id} failed after {task.attempt_count} attempts"
                )

        except Exception as inner_e:
            logger.error(
                f"Error handling task failure for {task_id}: {str(inner_e)}",
                exc_info=True,
            )


def get_queue_metrics():
    """
    Get metrics about the current task queue.

    Returns:
        dict: A dictionary containing queue metrics
    """
    now = timezone.now()

    # Get counts of tasks by status
    pending_count = AITask.objects.filter(status=AITask.TaskStatus.PENDING).count()
    processing_count = AITask.objects.filter(
        status=AITask.TaskStatus.PROCESSING
    ).count()
    completed_count = AITask.objects.filter(
        status=AITask.TaskStatus.COMPLETED, updated_at__gte=now - timedelta(days=1)
    ).count()
    failed_count = AITask.objects.filter(
        status=AITask.TaskStatus.FAILED, updated_at__gte=now - timedelta(days=1)
    ).count()

    # Get counts of background tasks
    scheduled_count = BGTask.objects.filter(run_at__gt=now).count()

    # Calculate average processing time for completed tasks in the last day
    completed_tasks = AITask.objects.filter(
        status=AITask.TaskStatus.COMPLETED, updated_at__gte=now - timedelta(days=1)
    )

    if completed_tasks.exists():
        # Calculate average time between created_at and updated_at
        total_seconds = sum(
            (task.updated_at - task.created_at).total_seconds()
            for task in completed_tasks
        )
        avg_processing_time = total_seconds / completed_tasks.count()
    else:
        avg_processing_time = 0

    return {
        "pending_count": pending_count,
        "processing_count": processing_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "scheduled_count": scheduled_count,
        "avg_processing_time": avg_processing_time,
        "timestamp": now.isoformat(),
    }


@background(schedule=timedelta(minutes=15))
def log_queue_metrics():
    """
    Periodically log queue metrics for monitoring.
    """
    metrics = get_queue_metrics()

    metrics_logger.info(
        f"Queue metrics: "
        f"pending={metrics['pending_count']}, "
        f"processing={metrics['processing_count']}, "
        f"completed_24h={metrics['completed_count']}, "
        f"failed_24h={metrics['failed_count']}, "
        f"scheduled={metrics['scheduled_count']}, "
        f"avg_time={metrics['avg_processing_time']:.2f}s"
    )
