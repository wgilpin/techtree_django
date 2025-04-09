# lessons/test_services_content.py
"""Tests for the get_or_create_lesson_content service function."""
# pylint: disable=no-member

from unittest.mock import patch, MagicMock
from asgiref.sync import sync_to_async

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from core.constants import DIFFICULTY_BEGINNER

from core.models import (
    Syllabus, Module, Lesson, LessonContent
)
from . import content_service  # Import content_service directly
from lessons.content_service import call_with_retry # Import for assertion

User = get_user_model()


class LessonContentServiceTests(TransactionTestCase):
    """Tests for the get_or_create_lesson_content service function."""

    def setUp(self):
        """Set up non-modified objects used by all test methods."""
        self.user = User.objects.create_user(username='testuser_content', password='password')
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
            lesson=self.lesson, content={"exposition": "Initial test content for content tests."}
        )

    # Patch call_with_retry and _get_llm
    # Corrected patches and signature
    # Restore full mocking strategy
    # Restore full mocking strategy
    @patch('lessons.content_service._fetch_syllabus_structure') # Mock the structure fetching
    @patch('lessons.content_service.asyncio.to_thread') # Mock asyncio.to_thread
    @patch('lessons.content_service._get_llm') # Add back _get_llm mock
    async def test_get_or_create_lesson_content_generation(self, mock_get_llm, mock_to_thread, mock_fetch_structure): # Add mock_get_llm
        """Test content generation when LessonContent doesn't exist."""
        # 1. Setup: Create a lesson without initial content
        # Use acreate for the lesson as well
        new_lesson = await Lesson.objects.acreate(
            module=self.module, lesson_index=1, title="New Lesson for Gen Test"
        )
        # Use async count
        self.assertEqual(await LessonContent.objects.filter(lesson=new_lesson).acount(), 0)

        # Configure mock_fetch_structure to return a simple valid structure
        mock_fetch_structure.return_value = [{"module_index": 0, "title": "Mock Module", "lessons": [{"lesson_index": 0, "title": "Mock Lesson"}]}]

        # 2. Mock LLM and Response
        mock_llm_instance = MagicMock()
        mock_get_llm.return_value = mock_llm_instance # Ensure _get_llm returns a mock
        mock_generated_content_str = '{"exposition": "Generated test content."}' # Correct JSON string
        mock_llm_response_obj = MagicMock()
        mock_llm_response_obj.content = mock_generated_content_str
        # Configure mock_to_thread to return the response directly
        mock_to_thread.return_value = mock_llm_response_obj

        # 3. Call the function under test
        lesson_content = await content_service.get_or_create_lesson_content(new_lesson) # Call content_service

        # 4. Assertions
        self.assertIsNotNone(lesson_content)
        self.assertEqual(lesson_content.lesson, new_lesson)
        self.assertIsInstance(lesson_content.content, dict)
        self.assertEqual(lesson_content.content.get('exposition'), "Generated test content.")

        # Verify mocks were called
        mock_fetch_structure.assert_called_once()
        mock_get_llm.assert_called_once() # Check _get_llm was called
        mock_to_thread.assert_called_once()
        # Check args passed to asyncio.to_thread
        call_args, call_kwargs = mock_to_thread.call_args
        self.assertEqual(call_args[0], call_with_retry) # Compare against imported call_with_retry
        self.assertEqual(call_args[1], mock_llm_instance.invoke) # Check correct invoke method passed
        prompt_arg = call_args[2]
        self.assertIsInstance(prompt_arg, str)
        self.assertIn(new_lesson.title, prompt_arg)
        self.assertIn(new_lesson.title, prompt_arg) # Check for the lesson title, not the module title
        self.assertIn(self.syllabus.topic, prompt_arg)

        # Verify content was saved to DB (use async methods)
        self.assertEqual(await LessonContent.objects.filter(lesson=new_lesson).acount(), 1)
        saved_content = await LessonContent.objects.aget(lesson=new_lesson)
        self.assertEqual(saved_content, lesson_content)

    @patch('lessons.content_service._get_llm') # Patch the LLM initialization helper directly
    async def test_get_or_create_lesson_content_existing(self, mock_get_llm): # Make async
        """Test retrieving existing LessonContent without calling LLM."""
        # Create content within the async test method
        # Create content with COMPLETED status
        existing_content = await LessonContent.objects.acreate(
            lesson=self.lesson,
            content={"exposition": "Existing test content."},
            status=LessonContent.StatusChoices.COMPLETED
        )
        # existing_content = self.lesson_content # Don't rely on setUp

        # Call the function
        lesson_content = await content_service.get_or_create_lesson_content(self.lesson) # Call content_service

        # Assertions
        self.assertEqual(lesson_content, existing_content)
        # Verify LLM init was NOT called
        mock_get_llm.assert_not_called() # Use the correct arg name
        # Verify LLM was NOT called
        mock_get_llm.assert_not_called() # Verify LLM init was NOT called