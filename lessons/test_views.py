# lessons/test_views.py
# pylint: disable=no-member

from unittest.mock import patch
import json

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Syllabus,
    Module,
    Lesson,
    LessonContent,
    UserProgress,
    ConversationHistory,
)
from .templatetags.markdown_extras import markdownify  # Import for testing view output

# Assuming services are needed for view tests, adjust if not
# from . import services # Not directly used in view tests, mocks are used
User = get_user_model()


class LessonViewsTestCase(TestCase):
    """Tests for the lesson views."""

    @classmethod
    def setUpTestData(cls):
        """Set up non-modified objects used by all test methods."""
        cls.user = User.objects.create_user(username="testuser", password="password")
        cls.other_user = User.objects.create_user(
            username="otheruser", password="password"
        )
        cls.syllabus = Syllabus.objects.create(
            topic="Test Topic", level="beginner", user=cls.user
        )
        cls.module = Module.objects.create(
            syllabus=cls.syllabus, module_index=0, title="Test Module"
        )
        cls.lesson = Lesson.objects.create(
            module=cls.module, lesson_index=0, title="Test Lesson"
        )
        cls.lesson_content = LessonContent.objects.create(
            lesson=cls.lesson, content={"exposition": "Initial test content."}
        )
        # Create progress for the main test user
        cls.initial_progress_state = {"lesson_db_id": cls.lesson.pk}
        cls.progress = UserProgress.objects.create(
            user=cls.user,
            syllabus=cls.syllabus,
            module_index=cls.module.module_index,
            lesson_index=cls.lesson.lesson_index,
            lesson=cls.lesson,
            status="in_progress",
            lesson_state_json=cls.initial_progress_state.copy(),  # Use a copy
        )
        cls.lesson_detail_url = reverse(
            "lessons:lesson_detail",  # Use namespaced URL name
            args=[cls.syllabus.pk, cls.module.module_index, cls.lesson.lesson_index],
        )
        cls.interaction_url = reverse(
            "lessons:handle_interaction",  # Use namespaced URL name
            args=[cls.syllabus.pk, cls.module.module_index, cls.lesson.lesson_index],
        )

    def setUp(self):
        """Set up the test client for each test."""
        self.client = Client()
        self.client.login(username="testuser", password="password")
        # Refresh progress object in case a previous test modified it (though mocks should prevent this)
        self.progress.refresh_from_db()

    # Removed incorrect patch @patch('lessons.services.get_lesson_state_and_history')
    def test_lesson_detail_context_with_exposition(self):
        """Test context data passed to lesson_detail template (using direct ORM access)."""
        # No service mock needed, view fetches directly.
        # Create some history for this test (using 'role' field)
        history1 = ConversationHistory.objects.create(
            progress=self.progress, role="user", content="Hi", timestamp=timezone.now()
        )
        history2 = ConversationHistory.objects.create(
            progress=self.progress,
            role="assistant",
            content="Hello",
            timestamp=timezone.now(),
        )
        expected_history = [history1, history2]

        response = self.client.get(self.lesson_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "lessons/lesson_detail.html")
        # No mock call to assert

        # Check context variables
        self.assertEqual(response.context["lesson"], self.lesson)
        self.assertEqual(response.context["module"], self.module)
        self.assertEqual(response.context["syllabus"], self.syllabus)
        # The view fetches lesson_content directly, check 'exposition_content' derived from it
        # self.assertEqual(response.context['lesson_content'], self.lesson_content) # Key no longer exists
        # Check the actual content attribute separately if needed, or check 'exposition_content'
        self.assertEqual(
            response.context["exposition_content"],
            self.lesson_content.content.get("exposition"),
        )  # Check correct context key
        self.assertEqual(
            list(response.context["conversation_history"]), expected_history
        )  # Compare history fetched by view
        self.assertEqual(response.context["progress"], self.progress)
        # Check the JSON string version passed to the template
        # Assert against the actual state saved in setUpTestData for the progress object
        self.assertEqual(
            response.context["lesson_state_json"],
            json.dumps(self.progress.lesson_state_json),
        )
        # Check the correct context key for initial exposition
        self.assertEqual(
            response.context["exposition_content"], "Initial test content."
        )  # Check correct context key
        # interaction_url is not passed in lesson_detail context

    # Removed incorrect patch
    def test_lesson_detail_context_missing_exposition_key(
        self,
    ):  # Removed mock_get_state argument
        """Test context when 'exposition' key is missing in content."""
        # No service mock needed
        # Create content without 'exposition'
        lesson_no_expo = Lesson.objects.create(
            module=self.module, lesson_index=1, title="Lesson No Expo"
        )
        LessonContent.objects.create(
            lesson=lesson_no_expo, content={"other_key": "some value"}
        )
        # Ensure progress exists for this lesson (view fetches it)
        UserProgress.objects.get_or_create(
            user=self.user,
            syllabus=self.syllabus,
            lesson=lesson_no_expo,
            defaults={
                "module_index": self.module.module_index,
                "lesson_index": lesson_no_expo.lesson_index,
            },
        )
        url_no_expo = reverse(
            "lessons:lesson_detail",  # Use namespaced URL name
            args=[
                self.syllabus.pk,
                self.module.module_index,
                lesson_no_expo.lesson_index,
            ],
        )

        response = self.client.get(url_no_expo)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "lessons/lesson_detail.html")
        # Check the derived 'exposition_content' context variable
        # self.assertEqual(response.context['lesson_content'], content_no_expo) # Key no longer exists
        # initial_exposition should be None if key is missing (to trigger async loading)
        self.assertEqual(
            response.context["exposition_content"], None
        )  # Check correct context key is None
        # No mock call to assert

    # Removed incorrect patch
    def test_lesson_detail_context_bad_content_format(
        self,
    ):  # Removed mock_get_state argument
        """Test context when lesson content is not a dictionary."""
        # No service mock needed
        # Create content that's not a dict
        lesson_bad_format = Lesson.objects.create(
            module=self.module, lesson_index=2, title="Lesson Bad Format"
        )
        LessonContent.objects.create(lesson=lesson_bad_format, content="just a string")
        # Ensure progress exists for this lesson (view fetches it)
        UserProgress.objects.get_or_create(
            user=self.user,
            syllabus=self.syllabus,
            lesson=lesson_bad_format,
            defaults={
                "module_index": self.module.module_index,
                "lesson_index": lesson_bad_format.lesson_index,
            },
        )
        url_bad_format = reverse(
            "lessons:lesson_detail",  # Use namespaced URL name
            args=[
                self.syllabus.pk,
                self.module.module_index,
                lesson_bad_format.lesson_index,
            ],
        )

        response = self.client.get(url_bad_format)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "lessons/lesson_detail.html")
        # Check the derived 'exposition_content' context variable
        # self.assertEqual(response.context['lesson_content'], content_bad_format) # Key no longer exists
        # initial_exposition should be None or empty string
        self.assertEqual(
            response.context["exposition_content"], None
        )  # Check correct context key is None
        # No mock call to assert

    # --- Tests for handle_lesson_interaction view ---

    @patch("lessons.services.handle_chat_message")
    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_chat_success(
        self, mock_get_state, mock_handle_chat
    ):
        """Test successful chat interaction via POST."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])

        # Mock the return value of the handle_chat_message service call
        mock_service_return = {
            "assistant_message": "AI chat response",  # Simplified
        }
        mock_handle_chat.return_value = mock_service_return

        # IMPORTANT: Simulate the state the view will find *after* the service call.
        # Since the service is mocked and doesn't save, we manually set the state
        # on the progress object that the view will refresh *from*.
        updated_state_in_db = {
            "lesson_db_id": self.lesson.pk,
            "last_interaction": "chat",
        }
        self.progress.lesson_state_json = updated_state_in_db
        self.progress.save()  # Ensure the DB has the state the refresh will find

        post_data = json.dumps(
            {"message": "User chat message", "submission_type": "chat"}
        )
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["status"], "success")
        # Compare against the markdownified version, as the view does
        self.assertEqual(
            response_json["assistant_message"],
            markdownify(mock_service_return["assistant_message"]),
        )

        # Assert against the state *as it exists in the DB AFTER the mocked service call*
        # because the view calls refresh_from_db()
        self.assertEqual(
            response_json["updated_state"], updated_state_in_db
        )  # Compare with the state we saved

        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="User chat message",
            submission_type="chat",
        )

    @patch("lessons.services.handle_chat_message")
    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_answer_success(
        self, mock_get_state, mock_handle_chat
    ):
        """Test successful answer submission interaction via POST."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        mock_service_return = {
            "assistant_message": "Correct!",
        }
        mock_handle_chat.return_value = mock_service_return

        # State the service *would* save
        updated_state_in_db = {
            "lesson_db_id": self.lesson.pk,
            "last_interaction": "answer",
            "score": 1.0,
        }
        self.progress.lesson_state_json = updated_state_in_db
        self.progress.save()

        post_data = json.dumps(
            {"message": "My answer is B", "submission_type": "answer"}
        )
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["status"], "success")
        # Compare against the markdownified version
        self.assertEqual(
            response_json["assistant_message"],
            markdownify(mock_service_return["assistant_message"]),
        )
        self.assertEqual(
            response_json["updated_state"], updated_state_in_db
        )  # Check against saved state

        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="My answer is B",
            submission_type="answer",
        )

    @patch("lessons.services.handle_chat_message")
    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_assessment_success(
        self, mock_get_state, mock_handle_chat
    ):
        """Test successful assessment submission interaction via POST."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        mock_service_return = {
            "assistant_message": "Assessment feedback.",
        }
        mock_handle_chat.return_value = mock_service_return

        # State the service *would* save
        updated_state_in_db = {
            "lesson_db_id": self.lesson.pk,
            "last_interaction": "assessment",
            "score": 0.5,
        }
        self.progress.lesson_state_json = updated_state_in_db
        self.progress.save()

        post_data = json.dumps(
            {"message": "Assessment answer", "submission_type": "assessment"}
        )
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json["status"], "success")
        # Compare against the markdownified version
        self.assertEqual(
            response_json["assistant_message"],
            markdownify(mock_service_return["assistant_message"]),
        )
        self.assertEqual(
            response_json["updated_state"], updated_state_in_db
        )  # Check against saved state

        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="Assessment answer",
            submission_type="assessment",
        )

    @patch("lessons.services.get_lesson_state_and_history")  # Correct patch target
    def test_handle_lesson_interaction_invalid_json(self, mock_get_state):
        """Test interaction with invalid JSON payload."""
        # Need to ensure get_lesson_state_and_history is called even with bad JSON
        # to check ownership/existence before erroring fully.
        mock_get_state.return_value = (self.progress, self.lesson_content, [])

        invalid_post_data = "this is not json"
        response = self.client.post(
            self.interaction_url,
            data=invalid_post_data,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("Invalid JSON", response_json["message"])
        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )

    @patch("lessons.services.handle_chat_message")  # Correct patch target
    @patch("lessons.services.get_lesson_state_and_history")  # Correct patch target
    def test_handle_lesson_interaction_service_error(
        self, mock_get_state, mock_handle_chat
    ):
        """Test interaction when handle_chat_message raises an exception."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        # Simulate an error during chat handling
        mock_handle_chat.side_effect = Exception("LLM Service Unavailable")

        post_data = json.dumps({"message": "Trigger error", "submission_type": "chat"})
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 500)
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("An unexpected error occurred", response_json["message"])
        mock_get_state.assert_called_once()
        mock_handle_chat.assert_called_once()

    def test_handle_lesson_interaction_requires_login(self):
        """Test that the interaction endpoint requires login."""
        self.client.logout()
        post_data = json.dumps({"message": "test", "submission_type": "chat"})
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )
        # Should redirect to login page (login URL doesn't need namespacing usually)
        login_url = reverse("login")
        expected_redirect = f"{login_url}?next={self.interaction_url}"
        self.assertRedirects(
            response, expected_redirect, status_code=302, fetch_redirect_response=False
        )

    def test_handle_lesson_interaction_post_only(self):
        """Test that the interaction endpoint only accepts POST."""
        response = self.client.get(self.interaction_url)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

    def test_handle_lesson_interaction_missing_lesson(self):
        """Test interaction with a non-existent lesson index."""
        non_existent_lesson_index = 999
        bad_url = reverse(
            "lessons:handle_interaction",
            args=[
                self.syllabus.pk,
                self.module.module_index,
                non_existent_lesson_index,
            ],
        )
        post_data = json.dumps({"message": "test", "submission_type": "chat"})
        response = self.client.post(
            bad_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 404)
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("Lesson context not found", response_json["message"])

    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_missing_progress(self, mock_get_state):
        """Test interaction when UserProgress cannot be found for the user/lesson."""
        # Simulate the service returning None for progress
        mock_get_state.return_value = (None, None, [])

        post_data = json.dumps({"message": "test", "submission_type": "chat"})
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 500)  # View returns 500 in this case
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("Could not load user progress", response_json["message"])
        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson,
        )

    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_empty_message(self, mock_get_state):
        """Test interaction with an empty message payload."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])

        post_data = json.dumps(
            {"message": "   ", "submission_type": "chat"}
        )  # Empty after strip
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("Message cannot be empty", response_json["message"])
        mock_get_state.assert_called_once()  # Should still fetch state first

    @patch("lessons.services.handle_chat_message")
    @patch("lessons.services.get_lesson_state_and_history")
    def test_handle_lesson_interaction_service_returns_none(
        self, mock_get_state, mock_handle_chat
    ):
        """Test interaction when the service returns None instead of a dict."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        mock_handle_chat.return_value = (
            None  # Simulate service failure/unexpected return
        )

        post_data = json.dumps({"message": "test", "submission_type": "chat"})
        response = self.client.post(
            self.interaction_url, data=post_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 500)
        response_json = response.json()
        self.assertEqual(response_json["status"], "error")
        self.assertIn("Failed to process interaction", response_json["message"])
        mock_get_state.assert_called_once()
        mock_handle_chat.assert_called_once()
