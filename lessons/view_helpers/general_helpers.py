""" helpers for views.py in lessopns"""

import json
import logging
from django.shortcuts import get_object_or_404

from core.models import Lesson, LessonContent, Module, Syllabus, UserProgress

logger = logging.getLogger(__name__)


def _get_lesson_objects(user, syllabus_id, module_index, lesson_index):
    """Fetch core lesson-related objects with validation."""
    syllabus = get_object_or_404(Syllabus, pk=syllabus_id)
    module = get_object_or_404(Module, syllabus=syllabus, module_index=module_index)
    lesson = get_object_or_404(Lesson, module=module, lesson_index=lesson_index)
    # pylint: disable=no-member
    progress, created = UserProgress.objects.get_or_create(
        user=user,
        syllabus=syllabus,
        lesson=lesson,
        defaults={
            "module_index": module.module_index,
            "lesson_index": lesson.lesson_index,
            "status": "not_started",
        },
    )
    return syllabus, module, lesson, progress, created


def _calculate_absolute_lesson_number(lesson, syllabus):
    """Calculate position of lesson within entire syllabus."""
    try:
        all_lesson_pks = list(
            # pylint: disable=no-member
            Lesson.objects.filter(module__syllabus=syllabus)
            .order_by("module__module_index", "lesson_index")
            .values_list("pk", flat=True)
        )
        return all_lesson_pks.index(lesson.pk) + 1
    except (ValueError, Exception) as e:
        logger.error(
            "Failed to calculate absolute lesson number for lesson %s: %s",
            lesson.pk,
            e,
            exc_info=True,
        )
        return None


def _build_lesson_context(
    syllabus,
    module,
    lesson,
    progress,
    exposition_content,
    content_status,
    abs_lesson_num,
    conv_history,
    trigger_regenerate,
    regen_url,
):
    """Construct the context dictionary for lesson templates."""
    return {
        "syllabus": syllabus,
        "module": module,
        "lesson": lesson,
        "progress": progress,
        "title": f"Lesson: {lesson.title}",
        "exposition_content": exposition_content,
        "content_status": content_status,
        "absolute_lesson_number": abs_lesson_num,
        "conversation_history": conv_history,
        "lesson_state_json": (
            json.dumps(progress.lesson_state_json)
            if progress.lesson_state_json
            else "{}"
        ),
        "LessonContentStatus": {
            "COMPLETED": LessonContent.StatusChoices.COMPLETED,
            "GENERATING": LessonContent.StatusChoices.GENERATING,
            "FAILED": LessonContent.StatusChoices.FAILED,
            "PENDING": LessonContent.StatusChoices.PENDING,
        },
        "trigger_regeneration": trigger_regenerate,
        "regeneration_url": regen_url,
    }
