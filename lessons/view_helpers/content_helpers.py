"""for lessons/views.py"""

# pylint: disable=no-member

import logging
import re
# Import Any if still needed, otherwise remove
from typing import Optional, cast, Any

# Import get_user_model
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.contrib import messages
from core.models import LessonContent
# This import is no longer needed and was causing the circular import
# from lessons.views import AuthUserType
from taskqueue.models import AITask
from taskqueue.tasks import process_ai_task as schedule_ai_task

logger = logging.getLogger(__name__)
# Get the actual user model class
UserModel = get_user_model()


def _handle_lesson_content_creation(lesson, user):
    """Handle lesson content retrieval/creation and task scheduling."""
    current_lesson_content = LessonContent.objects.filter(lesson=lesson).first()
    content_status = (
        current_lesson_content.status if current_lesson_content else "NOT_FOUND"
    )

    if not current_lesson_content:
        current_lesson_content = LessonContent.objects.create(
            lesson=lesson,
            content={},
            status=LessonContent.StatusChoices.PENDING,
        )
        content_status = LessonContent.StatusChoices.PENDING
        # Pass the user object to the scheduling function
        _schedule_content_task_if_needed(lesson, user)

    return current_lesson_content, content_status


def _schedule_content_task_if_needed(lesson, user):
    """Schedule content generation task if no existing pending task."""
    existing_task = (
        AITask.objects.filter(
            lesson=lesson,
            task_type=AITask.TaskType.LESSON_CONTENT,
            status__in=[AITask.TaskStatus.PENDING, AITask.TaskStatus.PROCESSING],
        )
        .order_by("-created_at")
        .first()
    )

    if not existing_task:
        # Cast the user object to the actual UserModel
        user_obj = cast(UserModel, user)
        task = AITask.objects.create(
            task_type=AITask.TaskType.LESSON_CONTENT,
            input_data={"lesson_id": str(lesson.pk)},
            user=user_obj, # Use the correctly cast user object
            lesson=lesson,
        )
        schedule_ai_task(task_id=task.task_id)


def _extract_and_validate_exposition(lesson_content, content_status):
    """Extract exposition content and validate its integrity, adjusting status if needed."""
    exposition_content_value: Optional[str] = None

    # Extract exposition content with defensive handling
    try:
        if lesson_content and content_status not in [
            LessonContent.StatusChoices.FAILED,
            LessonContent.StatusChoices.GENERATING,
        ]:
            content_data = lesson_content.content
            if isinstance(content_data, dict):
                exposition_value = content_data.get("exposition")
                if exposition_value:
                    exposition_content_value = clean_exposition_string(exposition_value)
    except Exception as e:
        logger.error(
            "Error extracting exposition content for lesson %s: %s",
            lesson_content.lesson.pk if lesson_content else "unknown",
            e,
            exc_info=True,
        )
        exposition_content_value = None

    # Validate and adjust content status based on exposition content
    if exposition_content_value and (
        content_status == LessonContent.StatusChoices.PENDING or not content_status
    ):
        if lesson_content:
            logger.info(
                "Found valid exposition for lesson content %s with status %s, "
                "treating as COMPLETED for display.",
                lesson_content.pk,
                content_status,
            )
        content_status = LessonContent.StatusChoices.COMPLETED
    elif content_status == LessonContent.StatusChoices.COMPLETED:
        if lesson_content and not isinstance(lesson_content.content, dict):
            logger.warning(
                "Lesson content (pk=%s) status is COMPLETED but content is not a dict (Type: %s). "
                "Marking as FAILED.",
                lesson_content.pk,
                type(lesson_content.content),
            )
            content_status = LessonContent.StatusChoices.FAILED
        elif not exposition_content_value:
            logger.warning(
                "Lesson content (pk=%s) status is COMPLETED but 'exposition' is missing or empty. "
                "Marking as FAILED.",
                lesson_content.pk,
            )
            content_status = LessonContent.StatusChoices.FAILED

    return exposition_content_value, content_status


def _handle_failed_content(
    content_status, syllabus_id, module_index, lesson_index, request
):
    """Handle failed content by setting up regeneration."""
    trigger_regeneration = False
    regeneration_url = None

    if content_status == LessonContent.StatusChoices.FAILED:
        trigger_regeneration = True
        regeneration_url = reverse(
            "lessons:generate_lesson_content",
            args=[syllabus_id, module_index, lesson_index],
        )
        messages.info(
            request,
            "Lesson content generation failed previously. Automatically retrying...",
        )

    return trigger_regeneration, regeneration_url


def clean_exposition_string(text: Optional[str]) -> Optional[str]:
    """Decodes unicode escapes and fixes specific known issues in exposition text."""
    if not text:
        return text

    cleaned_text = text
    try:
        # Decode standard Python unicode escapes (\uXXXX, \xXX)
        # Using 'latin-1' to handle potential byte values mixed with unicode escapes
        # and 'ignore' errors to skip problematic sequences.
        # Use 'raw_unicode_escape' which only handles \uXXXX and \UXXXXXXXX, leaving other backslashes alone.
        cleaned_text = cleaned_text.encode("latin-1", errors="ignore").decode(
            "raw_unicode_escape", errors="ignore"
        )
        # Alternative: cleaned_text = bytes(text, "utf-8").decode("unicode_escape")
    except Exception as e:
        logger.warning("Failed to decode unicode escapes in exposition: %s", e)
        # Continue with the original text if decoding fails, specific fixes might still apply

    # --- Specific known fixes (apply AFTER unicode decoding) ---

    # Fix: \u0007pprox -> \approx (where \u0007 might be a bell char or similar artifact)
    # This handles the case where the unicode decoding might not have fixed it.
    cleaned_text = cleaned_text.replace(
        "\u0007pprox", r"\approx"
    )  # Use raw string for \approx

    # Fix: \x08egin{ -> \begin{ (Backspace artifact)
    cleaned_text = cleaned_text.replace("\x08egin{", r"\begin{")  # Use raw string

    # Fix: â€" -> – (common Mojibake for en-dash)
    cleaned_text = cleaned_text.replace("â€“", "\u2013")
    # Fix: Ã¶ -> ö (common Mojibake for o-umlaut, e.g., Eötvös)
    cleaned_text = cleaned_text.replace("Ã¶", "ö")
    # Fix: \\, -> \, (Extra backslash before LaTeX space)
    cleaned_text = cleaned_text.replace("\\\\,", r"\,")
    # Fix: \\mu -> \mu, \\alpha -> \alpha, etc. (Extra backslash before greek letters)
    # Using regex to be more general for common LaTeX commands
    cleaned_text = re.sub(r"\\\\([a-zA-Z]+)", r"\\\1", cleaned_text)

    # Add other specific replacements if needed based on observed errors

    return cleaned_text
