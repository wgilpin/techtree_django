"""Tests for the handle_chat_message service function."""
# pylint: disable=no-member, unused-argument, missing-function-docstring, invalid-name

from unittest.mock import patch
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    Syllabus,
    Module,
    Lesson,
    LessonContent,
    UserProgress,
)
from . import interaction_service

User = get_user_model()


class LessonChatServiceTests(TransactionTestCase):
    """Tests for the handle_chat_message service function."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser_chat", password="password"
        )
        self.syllabus = Syllabus.objects.create(
            topic="Test Topic Chat", level="beginner", user=self.user
        )
        self.module = Module.objects.create(
            syllabus=self.syllabus, module_index=0, title="Test Module Chat"
        )
        self.lesson = Lesson.objects.create(
            module=self.module, lesson_index=0, title="Test Lesson Chat"
        )
        self.lesson_content = LessonContent.objects.create(
            lesson=self.lesson,
            content={"exposition": "Initial test content for chat tests."},
        )

    @patch("lessons.interaction_service.handle_chat_message")
    @patch("lessons.interaction_service.LessonInteractionGraph")
    def test_handle_chat_message(self, MockGraph, mock_handle_chat_message):
        user_message = "Hello AI"
        mock_response = {"new_assistant_message": "Hi human!"}
        mock_handle_chat_message.return_value = mock_response

        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                "initial": True,
                "updated_at": timezone.now().isoformat(),
            },
        )

        response = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message,
            submission_type="chat",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("new_assistant_message"), "Hi human!")

    @patch("lessons.interaction_service.handle_chat_message")
    @patch("lessons.interaction_service.LessonInteractionGraph")
    def test_handle_chat_message_generates_exercise(
        self, MockGraph, mock_handle_chat_message
    ):
        mock_handle_chat_message.return_value = {
            "new_assistant_message": "Here is an exercise"
        }

        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                "initial": True,
                "updated_at": timezone.now().isoformat(),
            },
        )

        response = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content="Give me an exercise",
            submission_type="chat",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("new_assistant_message"), "Here is an exercise")

    @patch("lessons.interaction_service.handle_chat_message")
    @patch("lessons.interaction_service.LessonInteractionGraph")
    def test_handle_chat_message_evaluates_answer(
        self, MockGraph, mock_handle_chat_message
    ):
        mock_handle_chat_message.return_value = {"new_assistant_message": "Correct!"}

        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                "initial": True,
                "updated_at": timezone.now().isoformat(),
            },
        )

        response = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content="The answer is B",
            submission_type="answer",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("new_assistant_message"), "Correct!")

    @patch("lessons.interaction_service.handle_chat_message")
    @patch("lessons.interaction_service.LessonInteractionGraph")
    def test_handle_chat_message_generates_assessment(
        self, MockGraph, mock_handle_chat_message
    ):
        mock_handle_chat_message.return_value = {
            "new_assistant_message": "Here is an assessment"
        }

        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                "initial": True,
                "updated_at": timezone.now().isoformat(),
            },
        )

        response = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content="Give me an assessment",
            submission_type="chat",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("new_assistant_message"), "Here is an assessment")

    @patch("lessons.interaction_service.handle_chat_message")
    @patch("lessons.interaction_service.LessonInteractionGraph")
    def test_handle_chat_message_evaluates_assessment(
        self, MockGraph, mock_handle_chat_message
    ):
        mock_handle_chat_message.return_value = {
            "new_assistant_message": "You got one right."
        }

        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                "initial": True,
                "updated_at": timezone.now().isoformat(),
            },
        )

        response = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content="My answer is B",
            submission_type="assessment",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get("new_assistant_message"), "You got one right.")
