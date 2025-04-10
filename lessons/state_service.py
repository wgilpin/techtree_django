"""
Service layer for managing lesson state and history.

This module contains functions related to fetching, initializing,
and updating the state associated with a user's progress through a lesson.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

# pylint: disable=no-member
from django.utils import timezone as django_timezone

# Import necessary models
from core.models import LessonContent
from core.models import Module  # type: ignore[misc]
from core.models import ConversationHistory, Lesson, Syllabus, UserProgress

# Import the function needed from the content service

# For type checking ForeignKey relations to Django's User model
if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def initialize_lesson_state(user, lesson, lesson_content):
    """ initialize the lesson state for a new UserProgress."""
    return {
        "user_id": str(user.pk) if user else None,
        "lesson_id": str(lesson.pk),
        "lesson_title": lesson.title,
        "lesson_summary": lesson.summary,
        "lesson_content": lesson_content.content if lesson_content else {},
        "history_context": [],
        "current_interaction_mode": "chatting",
        "last_user_message": None,
        "new_assistant_message": None,
        "evaluation_feedback": None,
    }
