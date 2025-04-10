"""
Service layer for managing lesson state and history.

This module contains functions related to fetching, initializing,
and updating the state associated with a user's progress through a lesson.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

# pylint: disable=no-member
from asgiref.sync import sync_to_async
from django.utils import timezone as django_timezone

# Import necessary models
from core.models import LessonContent
from core.models import Module  # type: ignore[misc]
from core.models import ConversationHistory, Lesson, Syllabus, UserProgress
from asgiref.sync import sync_to_async, async_to_sync

# Import the function needed from the content service
from .content_service import get_or_create_lesson_content

# For type checking ForeignKey relations to Django's User model
if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def _get_conversation_history_sync(progress):
    """
    Synchronously fetches conversation history for a given progress record.

    Args:
        progress: The UserProgress record.

    Returns:
        A list of ConversationHistory objects ordered by timestamp.
    """
    return list(
        ConversationHistory.objects.filter(progress=progress).order_by("timestamp")
    )


async def _initialize_lesson_state(
    user: "User", lesson: Lesson, lesson_content: LessonContent
) -> Dict[str, Any]:
    """
    Creates the initial state dictionary for a user starting a lesson.

    Args:
        user: The user starting the lesson.
        lesson: The Lesson object.
        lesson_content: The generated LessonContent object.

    Returns:
        A dictionary representing the initial lesson state.
    """
    # Wrap sync ORM access
    module = await sync_to_async(lambda: lesson.module)()
    assert isinstance(module, Module)  # Help mypy with type inference
    # Wrap sync ORM access
    syllabus = await sync_to_async(lambda: module.syllabus)()  # type: ignore[attr-defined]
    assert isinstance(syllabus, Syllabus)  # Help mypy with type inference
    now_iso = django_timezone.now().isoformat()  # Use Django's timezone

    # Extract exposition safely from content JSON
    exposition_text = ""
    if isinstance(lesson_content.content, dict):
        exposition_text = lesson_content.content.get("exposition", "")
    elif isinstance(
        lesson_content.content, str
    ):  # Handle case where content might be just a string
        exposition_text = lesson_content.content

    # Basic initial state structure
    initial_state = {
        "topic": await sync_to_async(lambda: syllabus.topic)(),
        "user_knowledge_level": await sync_to_async(lambda: syllabus.level)(),
        "lesson_title": await sync_to_async(lambda: lesson.title)(),
        "module_title": await sync_to_async(lambda: module.title)(),
        "lesson_uid": f"{str(await sync_to_async(lambda: syllabus.pk)())}_{module.module_index}_{lesson.lesson_index}",
        "user_id": str(await sync_to_async(lambda: user.pk)()),
        "lesson_db_id": await sync_to_async(lambda: lesson.pk)(),
        "content_db_id": str(await sync_to_async(lambda: lesson_content.pk)()),
        "created_at": now_iso,
        "updated_at": now_iso,
        "current_interaction_mode": "chatting",
        "current_exercise_index": None,
        "current_quiz_question_index": None,
        "generated_exercises": [],
        "generated_assessment_questions": [],
        "user_responses": [],
        "user_performance": {},
        "error_message": None,
        "active_exercise": None,
        "active_assessment": None,
        "lesson_exposition": exposition_text,
    }
    logger.info(
        "Initialized state dictionary for lesson %s, user %s",
        await sync_to_async(lambda: lesson.pk)(),
        await sync_to_async(lambda: user.pk)()
    )
    return initial_state


async def get_lesson_state_and_history(
    user: "User",
    syllabus: Syllabus,
    module: Module,
    lesson: Lesson,
) -> Tuple[
    Optional[UserProgress], Optional[LessonContent], List[ConversationHistory]
]:
    """
    Fetches or initializes user progress, lesson content, and conversation history.

    Args:
        user: The authenticated user.
        syllabus: The relevant Syllabus object.
        module: The relevant Module object.
        lesson: The relevant Lesson object.

    Returns:
        A tuple containing:
            - The UserProgress object (with potentially initialized state).
            - The LessonContent object (or None if fetch/generation fails).
            - A list of ConversationHistory messages for this progress record.
        Returns (None, None, []) if essential components like lesson content fail.
    """
    logger.info(
        "Fetching state/history for user %s, lesson %s (%s)",
        user.username,
        lesson.pk,
        lesson.title,
    )

    # 1. Get or Create Lesson Content (required for state initialization)
    lesson_content = await get_or_create_lesson_content(lesson)
    if not lesson_content:
        logger.error(
            "Failed to get or create lesson content for lesson %s. Cannot proceed.",
            lesson.pk,
        )
        return None, None, []

    # 2. Get or Create User Progress record
    progress, created = await sync_to_async(UserProgress.objects.get_or_create)(
        user=user,
        syllabus=syllabus,
        lesson=lesson,
        defaults={
            "module_index": module.module_index,
            "lesson_index": lesson.lesson_index,
            "status": "not_started",
        },
    )

    conversation_history: List[ConversationHistory] = []
    lesson_state: Optional[Dict[str, Any]] = None

    if created:
        logger.info(
            "Created new UserProgress (ID: %s) for user %s, lesson %s.",
            progress.pk,
            user.username,
            lesson.pk,
        )
        try:
            lesson_state = await _initialize_lesson_state(user, lesson, lesson_content)
            progress.lesson_state_json = lesson_state
            progress.status = "in_progress"
            await sync_to_async(progress.save)(
                update_fields=["lesson_state_json", "status", "updated_at"]
            )
            logger.info(
                "Initialized and saved state for new UserProgress %s.", progress.pk
            )
        except Exception as e:
            logger.error(
                "Failed to initialize or save state for new UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )
            progress.lesson_state_json = {"error": "Initialization failed"}
            await sync_to_async(progress.save)(
                update_fields=["lesson_state_json", "updated_at"]
            )

    else:
        logger.info(
            "Found existing UserProgress (ID: %s) for user %s, lesson %s.",
            progress.pk,
            user.username,
            lesson.pk,
        )
        if isinstance(progress.lesson_state_json, dict):
            lesson_state = progress.lesson_state_json
            if not lesson_state.get("lesson_db_id") == lesson.pk:
                logger.warning(
                    "State lesson ID (%s) mismatch for UserProgress %s. Updating.",
                    lesson_state.get("lesson_db_id"),
                    progress.pk,
                )
                lesson_state["lesson_db_id"] = lesson.pk
                lesson_state["updated_at"] = django_timezone.now().isoformat()
                progress.lesson_state_json = lesson_state
                await sync_to_async(progress.save)(
                    update_fields=["lesson_state_json", "updated_at"]
                )

        elif progress.lesson_state_json is not None:
            logger.warning(
                "UserProgress %s has non-dict lesson_state_json (%s). Re-initializing.",
                progress.pk,
                type(progress.lesson_state_json),
            )
            try:
                lesson_state = await _initialize_lesson_state(
                    user, lesson, lesson_content
                )
                progress.lesson_state_json = lesson_state
                await sync_to_async(progress.save)(
                    update_fields=["lesson_state_json", "updated_at"]
                )
            except Exception as e:
                logger.error(
                    "Failed to re-initialize state for UserProgress %s: %s",
                    progress.pk,
                    e,
                    exc_info=True,
                )
                progress.lesson_state_json = {"error": "Re-initialization failed"}
                await sync_to_async(progress.save)(
                    update_fields=["lesson_state_json", "updated_at"]
                )
                lesson_state = None
        else:
            logger.warning(
                "UserProgress %s has NULL lesson_state_json. Initializing.", progress.pk
            )
            try:
                lesson_state = await _initialize_lesson_state(
                    user, lesson, lesson_content
                )
                progress.lesson_state_json = lesson_state
                await sync_to_async(progress.save)(
                    update_fields=["lesson_state_json", "updated_at"]
                )
            except Exception as e:
                logger.error(
                    "Failed to initialize NULL state for UserProgress %s: %s",
                    progress.pk,
                    e,
                    exc_info=True,
                )
                progress.lesson_state_json = {"error": "Initialization failed"}
                await sync_to_async(progress.save)(
                    update_fields=["lesson_state_json", "updated_at"]
                )
                lesson_state = None

        if progress.status == "not_started":
            progress.status = "in_progress"
            await sync_to_async(progress.save)(update_fields=["status", "updated_at"])
            logger.info("Updated UserProgress %s status to 'in_progress'.", progress.pk)

        try:
            # Use the local synchronous helper function
            conversation_history = await sync_to_async(_get_conversation_history_sync)(
                progress
            )
            logger.info(
                "Fetched %d history messages for UserProgress %s.",
                len(conversation_history),
                progress.pk,
            )
        except Exception as e:
            logger.error(
                "Failed to fetch conversation history for UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )

    if lesson_state is not None:
        progress.lesson_state_json = lesson_state

    return progress, lesson_content, conversation_history