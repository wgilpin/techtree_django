# lessons/test_services.py
"""Tests for the get_lesson_state_and_history service function."""
# pylint: disable=no-member

from unittest.mock import patch
from asgiref.sync import sync_to_async

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from core.constants import DIFFICULTY_BEGINNER

from core.models import (
    Syllabus, Module, Lesson, LessonContent, UserProgress, ConversationHistory
)
from . import services, state_service # Import state_service

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

    # Patch the LLM call within get_or_create_lesson_content for all tests in this class
    # to avoid actual API calls and ensure content exists quickly.
    @patch('lessons.state_service.get_or_create_lesson_content') # Target lookup within state_service
    async def test_get_lesson_state_and_history_new_progress(self, mock_get_content): # Make async
        """Test fetching state for a lesson the user hasn't started."""
        # Ensure the mock returns the pre-created content
        mock_get_content.return_value = self.lesson_content

        progress, content, history = await state_service.get_lesson_state_and_history( # Call state_service
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )

        self.assertIsNotNone(progress)
        self.assertEqual(progress.user, self.user)
        self.assertEqual(progress.lesson, self.lesson)
        self.assertEqual(progress.status, 'in_progress') # Should be updated
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertEqual(progress.lesson_state_json.get('lesson_db_id'), self.lesson.pk)
        self.assertEqual(content, self.lesson_content)
        self.assertEqual(len(history), 0)
        mock_get_content.assert_called_once_with(self.lesson)

    @patch('lessons.state_service.get_or_create_lesson_content') # Target lookup within state_service
    async def test_get_lesson_state_and_history_existing_progress(self, mock_get_content): # Make async
        """Test fetching state for a lesson already in progress."""
        mock_get_content.return_value = self.lesson_content
        initial_state = {"test_key": "test_value", "lesson_db_id": self.lesson.pk}
        existing_progress = await sync_to_async(UserProgress.objects.create)(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json=initial_state,
        )
        # Add a history item
        await sync_to_async(ConversationHistory.objects.create)(
            progress=existing_progress, role='user', content='hello'
        )

        progress, content, history = await state_service.get_lesson_state_and_history( # Call state_service
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )

        self.assertEqual(progress, existing_progress)
        self.assertEqual(progress.lesson_state_json, initial_state) # State should be loaded
        self.assertEqual(content, self.lesson_content)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].content, 'hello')
        mock_get_content.assert_called_once_with(self.lesson)

    @patch('lessons.state_service.get_or_create_lesson_content') # Target lookup within state_service
    async def test_get_lesson_state_and_history_corrupt_state(self, mock_get_content): # Make async
        """Test fetching state when existing state is not a dict."""
        mock_get_content.return_value = self.lesson_content
        existing_progress = await sync_to_async(UserProgress.objects.create)(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json="not a dict", # Corrupt state
        )

        progress, content, history = await state_service.get_lesson_state_and_history( # Call state_service
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )

        self.assertEqual(progress, existing_progress)
        self.assertIsInstance(progress.lesson_state_json, dict) # Should re-initialize
        self.assertIn('lesson_db_id', progress.lesson_state_json) # Check a key exists
        self.assertEqual(progress.lesson_state_json.get('lesson_db_id'), self.lesson.pk)
        self.assertEqual(content, self.lesson_content)
        self.assertEqual(len(history), 0) # History is separate from state re-init
        mock_get_content.assert_called_once_with(self.lesson)