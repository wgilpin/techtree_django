# lessons/test_services.py
"""Tests for the get_lesson_state_and_history service function."""
# pylint: disable=no-member

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from core.constants import DIFFICULTY_BEGINNER

from core.models import (
    Syllabus, Module, Lesson, LessonContent
)

User = get_user_model()


class LessonStateHistoryServiceTests(TransactionTestCase): # Renamed class
    """Tests for the get_lesson_state_and_history service function."""

    def setUp(self):
        """Set up non-modified objects used by all test methods."""
        self.user = User.objects.create_user(username='testuser_state', password='password')
        self.syllabus = Syllabus.objects.create(
            topic="Test Topic State", level=DIFFICULTY_BEGINNER, user=self.user
        )
        self.module = Module.objects.create(
            syllabus=self.syllabus, module_index=0, title="Test Module State"
        )
        self.lesson = Lesson.objects.create(
            module=self.module, lesson_index=0, title="Test Lesson State"
        )
        # Create initial content to avoid generation during state tests
        self.lesson_content = LessonContent.objects.create(
            lesson=self.lesson, content={"exposition": "Initial test content for state tests."}
        )
