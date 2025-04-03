# lessons/test_views.py
# pylint: disable=no-member

from unittest.mock import patch, MagicMock
import json

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Syllabus, Module, Lesson, LessonContent, UserProgress, ConversationHistory
)
# Assuming services are needed for view tests, adjust if not
# from . import services # Not directly used in view tests, mocks are used

User = get_user_model()


class LessonViewsTestCase(TestCase):
    """Tests for the lesson views."""

    @classmethod
    def setUpTestData(cls):
        """Set up non-modified objects used by all test methods."""
        cls.user = User.objects.create_user(username='testuser', password='password')
        cls.other_user = User.objects.create_user(username='otheruser', password='password')
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
            status='in_progress',
            lesson_state_json=cls.initial_progress_state.copy() # Use a copy
        )
        cls.lesson_detail_url = reverse(
            'lessons:lesson_detail', # Use namespaced URL name
            args=[cls.syllabus.pk, cls.module.module_index, cls.lesson.lesson_index]
        )
        cls.interaction_url = reverse(
            'lessons:handle_interaction', # Use namespaced URL name
            args=[cls.syllabus.pk, cls.module.module_index, cls.lesson.lesson_index]
        )

    def setUp(self):
        """Set up the test client for each test."""
        self.client = Client()
        self.client.login(username='testuser', password='password')
        # Refresh progress object in case a previous test modified it (though mocks should prevent this)
        self.progress.refresh_from_db()


    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_lesson_detail_context_with_exposition(self, mock_get_state):
        """Test context data passed to lesson_detail template."""
        # Mock the service call
        # The state saved in setUpTestData is {"lesson_db_id": cls.lesson.pk}
        # The service call mock returns this progress object.
        # The view puts progress.lesson_state_json into the context['lesson_state_json']
        mock_state_as_saved_in_db = self.initial_progress_state.copy()
        mock_history = [
            ConversationHistory(progress=self.progress, role='user', content='Hi', timestamp=timezone.now()),
            ConversationHistory(progress=self.progress, role='assistant', content='Hello', timestamp=timezone.now())
        ]
        # Ensure the mocked service returns the progress object with the correct state
        self.progress.lesson_state_json = mock_state_as_saved_in_db
        mock_get_state.return_value = (self.progress, self.lesson_content, mock_history)

        response = self.client.get(self.lesson_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'lessons/lesson_detail.html')
        mock_get_state.assert_called_once_with(
            user=self.user,
            syllabus=self.syllabus,
            module=self.module,
            lesson=self.lesson
        )

        # Check context variables
        self.assertEqual(response.context['lesson'], self.lesson)
        self.assertEqual(response.context['module'], self.module)
        self.assertEqual(response.context['syllabus'], self.syllabus)
        # The context variable 'lesson_content' holds the model instance
        self.assertEqual(response.context['lesson_content'], self.lesson_content)
        # Check the actual content attribute separately if needed, or check 'exposition_content'
        self.assertEqual(response.context['exposition_content'], self.lesson_content.content.get('exposition')) # Check correct context key
        self.assertEqual(response.context['conversation_history'], mock_history)
        self.assertEqual(response.context['progress'], self.progress)
        # Check the JSON string version passed to the template
        # Assert against the actual state saved in setUpTestData for the progress object
        self.assertEqual(response.context['lesson_state_json'], json.dumps(self.progress.lesson_state_json))
        # Check the correct context key for initial exposition
        self.assertEqual(response.context['exposition_content'], "Initial test content.") # Check correct context key
        # interaction_url is not passed in lesson_detail context

    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_lesson_detail_context_missing_exposition_key(self, mock_get_state):
        """Test context when 'exposition' key is missing in content."""
        mock_state = {"lesson_db_id": self.lesson.pk}
        mock_history = []
        # Create content without 'exposition' - need a unique lesson for this content
        lesson_no_expo = Lesson.objects.create(module=self.module, lesson_index=1, title="Lesson No Expo")
        content_no_expo = LessonContent.objects.create(
            lesson=lesson_no_expo, content={"other_key": "some value"}
        )
        # Need progress for this specific lesson
        progress_no_expo = UserProgress.objects.create(
            user=self.user, syllabus=self.syllabus, module_index=self.module.module_index,
            lesson_index=lesson_no_expo.lesson_index, lesson=lesson_no_expo, status='in_progress'
        )
        mock_get_state.return_value = (progress_no_expo, content_no_expo, mock_history)
        url_no_expo = reverse(
            'lessons:lesson_detail', # Use namespaced URL name
            args=[self.syllabus.pk, self.module.module_index, lesson_no_expo.lesson_index]
        )

        response = self.client.get(url_no_expo)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'lessons/lesson_detail.html')
        # The context variable 'lesson_content' holds the model instance
        self.assertEqual(response.context['lesson_content'], content_no_expo)
        # initial_exposition should be None or empty string if key is missing
        self.assertEqual(response.context['exposition_content'], '') # Check correct context key is empty
        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=lesson_no_expo
        )


    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_lesson_detail_context_bad_content_format(self, mock_get_state):
        """Test context when lesson content is not a dictionary."""
        mock_state = {"lesson_db_id": self.lesson.pk}
        mock_history = []
        # Create content that's not a dict - need a unique lesson
        lesson_bad_format = Lesson.objects.create(module=self.module, lesson_index=2, title="Lesson Bad Format")
        content_bad_format = LessonContent.objects.create(
            lesson=lesson_bad_format, content="just a string"
        )
        # Need progress for this specific lesson
        progress_bad_format = UserProgress.objects.create(
            user=self.user, syllabus=self.syllabus, module_index=self.module.module_index,
            lesson_index=lesson_bad_format.lesson_index, lesson=lesson_bad_format, status='in_progress'
        )
        mock_get_state.return_value = (progress_bad_format, content_bad_format, mock_history)
        url_bad_format = reverse(
            'lessons:lesson_detail', # Use namespaced URL name
            args=[self.syllabus.pk, self.module.module_index, lesson_bad_format.lesson_index]
        )

        response = self.client.get(url_bad_format)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'lessons/lesson_detail.html')
        # The context variable 'lesson_content' holds the model instance
        self.assertEqual(response.context['lesson_content'], content_bad_format)
        # initial_exposition should be None or empty string
        self.assertEqual(response.context['exposition_content'], '') # Check correct context key is empty
        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=lesson_bad_format
        )


    # --- Tests for handle_lesson_interaction view ---

    @patch('lessons.services.handle_chat_message') # Correct patch target
    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_handle_lesson_interaction_chat_success(self, mock_get_state, mock_handle_chat):
        """Test successful chat interaction via POST."""
        # Mock get_lesson_state_and_history to return the progress object
        mock_get_state.return_value = (self.progress, self.lesson_content, [])

        # Mock the state dict *as it would be returned by the service*
        mock_state_from_service = {
             "lesson_db_id": self.lesson.pk,
             "current_interaction_mode": "chatting",
             "active_exercise": None,
             "active_assessment": None,
             "user_id": self.user.pk,
             "lesson_topic": self.syllabus.topic,
             "lesson_title": self.lesson.title,
             "new_assistant_message": "AI chat response", # Include if needed by service logic
             "updated_at": timezone.now().isoformat()
        }
        # Mock the return value of the handle_chat_message service call
        mock_service_return = {
            "assistant_message": {"role": "assistant", "content": "AI chat response"},
            "updated_state": mock_state_from_service # Service returns the state dict
        }
        mock_handle_chat.return_value = mock_service_return

        post_data = json.dumps({
            "message": "User chat message",
            "submission_type": "chat"
        })
        response = self.client.post(
            self.interaction_url,
            data=post_data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        response_json = response.json()

        self.assertEqual(response_json['status'], 'success')
        self.assertEqual(response_json['assistant_message'], mock_service_return['assistant_message'])

        # Assert against the state *as it exists in the DB before the call*
        # because the mock doesn't actually save the updated state.
        response_state = response_json['updated_state']
        expected_state_in_response = self.initial_progress_state.copy() # State before interaction
        # Remove dynamic keys if they were added by the view logic unexpectedly
        response_state.pop('updated_at', None)

        self.assertEqual(response_state, expected_state_in_response)

        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=self.lesson
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="User chat message",
            submission_type="chat"
        )

    @patch('lessons.services.handle_chat_message') # Correct patch target
    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_handle_lesson_interaction_answer_success(self, mock_get_state, mock_handle_chat):
        """Test successful answer submission interaction via POST."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        # Mock the state dict *as it would be returned by the service*
        mock_state_from_service = {
            "lesson_db_id": self.lesson.pk,
            "current_interaction_mode": "chatting",
            "active_exercise": None,
            "active_assessment": None,
            "score_update": 1.0,
            "user_id": self.user.pk,
            "lesson_topic": self.syllabus.topic,
            "lesson_title": self.lesson.title,
            "evaluation_feedback": "Correct!",
            "updated_at": timezone.now().isoformat()
        }
        # Mock the return value of the handle_chat_message service call
        mock_service_return = {
            "assistant_message": {"role": "assistant", "content": "Correct!"},
            "updated_state": mock_state_from_service
        }
        mock_handle_chat.return_value = mock_service_return

        post_data = json.dumps({
            "message": "My answer is B",
            "submission_type": "answer"
        })
        response = self.client.post(
            self.interaction_url,
            data=post_data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'success')
        self.assertEqual(response_json['assistant_message'], mock_service_return['assistant_message'])

        # Assert against the state *as it exists in the DB before the call*
        response_state = response_json['updated_state']
        expected_state_in_response = self.initial_progress_state.copy() # State before interaction
        response_state.pop('updated_at', None) # Ignore dynamic field from actual response
        self.assertEqual(response_state, expected_state_in_response)

        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=self.lesson
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="My answer is B",
            submission_type="answer"
        )

    @patch('lessons.services.handle_chat_message') # Correct patch target
    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_handle_lesson_interaction_assessment_success(self, mock_get_state, mock_handle_chat):
        """Test successful assessment submission interaction via POST."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        # Mock the state dict *as it would be returned by the service*
        mock_state_from_service = {
            "lesson_db_id": self.lesson.pk,
            "current_interaction_mode": "chatting",
            "active_exercise": None,
            "active_assessment": None,
            "score_update": 0.5,
            "user_id": self.user.pk,
            "lesson_topic": self.syllabus.topic,
            "lesson_title": self.lesson.title,
            "evaluation_feedback": "Assessment feedback.",
            "updated_at": timezone.now().isoformat()
        }
        # Mock the return value of the handle_chat_message service call
        mock_service_return = {
            "assistant_message": {"role": "assistant", "content": "Assessment feedback."},
            "updated_state": mock_state_from_service
        }
        mock_handle_chat.return_value = mock_service_return

        post_data = json.dumps({
            "message": "Assessment answer",
            "submission_type": "assessment"
        })
        response = self.client.post(
            self.interaction_url,
            data=post_data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'success')
        self.assertEqual(response_json['assistant_message'], mock_service_return['assistant_message'])

        # Assert against the state *as it exists in the DB before the call*
        response_state = response_json['updated_state']
        expected_state_in_response = self.initial_progress_state.copy() # State before interaction
        response_state.pop('updated_at', None) # Ignore dynamic field from actual response
        self.assertEqual(response_state, expected_state_in_response)

        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=self.lesson
        )
        mock_handle_chat.assert_called_once_with(
            user=self.user,
            progress=self.progress,
            user_message_content="Assessment answer",
            submission_type="assessment"
        )

    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_handle_lesson_interaction_invalid_json(self, mock_get_state):
        """Test interaction with invalid JSON payload."""
        # Need to ensure get_lesson_state_and_history is called even with bad JSON
        # to check ownership/existence before erroring fully.
        mock_get_state.return_value = (self.progress, self.lesson_content, [])

        invalid_post_data = "this is not json"
        response = self.client.post(
            self.interaction_url,
            data=invalid_post_data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'error')
        self.assertIn('Invalid JSON', response_json['message'])
        mock_get_state.assert_called_once_with(
            user=self.user, syllabus=self.syllabus, module=self.module, lesson=self.lesson
        )


    @patch('lessons.services.handle_chat_message') # Correct patch target
    @patch('lessons.services.get_lesson_state_and_history') # Correct patch target
    def test_handle_lesson_interaction_service_error(self, mock_get_state, mock_handle_chat):
        """Test interaction when handle_chat_message raises an exception."""
        mock_get_state.return_value = (self.progress, self.lesson_content, [])
        # Simulate an error during chat handling
        mock_handle_chat.side_effect = Exception("LLM Service Unavailable")

        post_data = json.dumps({
            "message": "Trigger error",
            "submission_type": "chat"
        })
        response = self.client.post(
            self.interaction_url,
            data=post_data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 500)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'error')
        self.assertIn('An unexpected error occurred', response_json['message'])
        mock_get_state.assert_called_once()
        mock_handle_chat.assert_called_once()

    def test_handle_lesson_interaction_requires_login(self):
        """Test that the interaction endpoint requires login."""
        self.client.logout()
        post_data = json.dumps({"message": "test", "submission_type": "chat"})
        response = self.client.post(
            self.interaction_url,
            data=post_data,
            content_type='application/json'
        )
        # Should redirect to login page (login URL doesn't need namespacing usually)
        login_url = reverse('login')
        expected_redirect = f'{login_url}?next={self.interaction_url}'
        self.assertRedirects(response, expected_redirect, status_code=302, fetch_redirect_response=False)


    def test_handle_lesson_interaction_post_only(self):
        """Test that the interaction endpoint only accepts POST."""
        response = self.client.get(self.interaction_url)
        self.assertEqual(response.status_code, 405) # Method Not Allowed