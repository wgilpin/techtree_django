# lessons/test_services_content.py
"""Tests for the get_or_create_lesson_content service function."""
# pylint: disable=no-member

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from core.constants import DIFFICULTY_BEGINNER
from core.models import Lesson, LessonContent, Module, Syllabus

User = get_user_model()


class LessonContentServiceTests(TransactionTestCase):
    """Tests for the get_or_create_lesson_content service function."""

    def setUp(self):
        """Set up non-modified objects used by all test methods."""
        self.user = User.objects.create_user(
            username="testuser_content", password="password"
        )
        self.syllabus = Syllabus.objects.create(
            topic="Test Topic Content", level=DIFFICULTY_BEGINNER, user=self.user
        )
        self.module = Module.objects.create(
            syllabus=self.syllabus, module_index=0, title="Test Module Content"
        )
        self.lesson = Lesson.objects.create(
            module=self.module, lesson_index=0, title="Test Lesson Content"
        )
        # Keep this for the existing test, though generation test creates its own lesson
        self.lesson_content = LessonContent.objects.create(
            lesson=self.lesson,
            content={"exposition": "Initial test content for content tests."},
        )

    # Patch call_with_retry and _get_llm
    # Corrected patches and signature
    # Restore full mocking strategy
    # Restore full mocking strategy
