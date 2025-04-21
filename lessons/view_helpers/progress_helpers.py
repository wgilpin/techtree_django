import logging
from typing import List

from core.models import ConversationHistory, LessonContent
from lessons.state_service import initialize_lesson_state

logger = logging.getLogger(__name__)


def update_progress_if_needed(progress, user, lesson, created):
    """Initialize and update user progress status as needed."""
    if created:
        initial_lesson_content = LessonContent.objects.filter(
            lesson=lesson, status=LessonContent.StatusChoices.COMPLETED
        ).first()

        progress.lesson_state_json = initialize_lesson_state(
            user, lesson, initial_lesson_content
        )
        progress.save()

    if created or progress.status == "not_started":
        progress.status = "in_progress"
        progress.save(update_fields=["status", "updated_at"])
        logger.info("Set/updated UserProgress %s status to 'in_progress'.", progress.pk)


def prepare_conversation_history(progress, lesson) -> List[ConversationHistory]:
    """Prepare conversation history with initial welcome message if empty."""
    history = list(
        # pylint: disable=no-member
        ConversationHistory.objects.filter(progress=progress).order_by("timestamp")
    )

    if not history:
        welcome_content = (
            "Is there anything I can explain more? Ask me any questions, or we can do "
            "exercises to help to think about it all. Once you're happy with this "
            "lesson, ask me to start a quiz"
        )
        history.insert(
            0,
            ConversationHistory(
                progress=progress,
                role="assistant",
                content=welcome_content,
            ),
        )
        logger.info(
            "Prepended welcome message to empty history for lesson %s", lesson.pk
        )
    return history
