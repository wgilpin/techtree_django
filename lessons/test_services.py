# lessons/test_services.py
# pylint: disable=no-member

from unittest.mock import patch, MagicMock, Mock
import json

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.constants import DIFFICULTY_BEGINNER # Import constant

from core.models import (
    Syllabus, Module, Lesson, LessonContent, UserProgress, ConversationHistory
)
from . import services
from .services import _initialize_lesson_state # Import the helper

User = get_user_model()


class LessonServicesTestCase(TestCase):
    """Tests for the lesson service functions."""

    @classmethod
    def setUpTestData(cls):
        """Set up non-modified objects used by all test methods."""
        cls.user = User.objects.create_user(username='testuser', password='password')
        cls.syllabus = Syllabus.objects.create(
            topic="Test Topic", level=DIFFICULTY_BEGINNER, user=cls.user
        )
        cls.module = Module.objects.create(
            syllabus=cls.syllabus, module_index=0, title="Test Module"
        )
        cls.lesson = Lesson.objects.create(
            module=cls.module, lesson_index=0, title="Test Lesson"
        )
        # Create initial content to avoid generation during state tests
        cls.lesson_content = LessonContent.objects.create(
            lesson=cls.lesson, content={"exposition": "Initial test content."}
        )

    # Patch the LLM call within get_or_create_lesson_content for all tests in this class
    # to avoid actual API calls and ensure content exists quickly.
    @patch('lessons.services.get_or_create_lesson_content')
    def test_get_lesson_state_and_history_new_progress(self, mock_get_content):
        """Test fetching state for a lesson the user hasn't started."""
        # Ensure the mock returns the pre-created content
        mock_get_content.return_value = self.lesson_content

        progress, content, history = services.get_lesson_state_and_history(
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

    @patch('lessons.services.get_or_create_lesson_content')
    def test_get_lesson_state_and_history_existing_progress(self, mock_get_content):
        """Test fetching state for a lesson already in progress."""
        mock_get_content.return_value = self.lesson_content
        initial_state = {"test_key": "test_value", "lesson_db_id": self.lesson.pk}
        existing_progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json=initial_state,
        )
        # Add a history item
        ConversationHistory.objects.create(
            progress=existing_progress, role='user', content='hello'
        )

        progress, content, history = services.get_lesson_state_and_history(
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

    @patch('lessons.services.get_or_create_lesson_content')
    def test_get_lesson_state_and_history_corrupt_state(self, mock_get_content):
        """Test fetching state when existing state is not a dict."""
        mock_get_content.return_value = self.lesson_content
        existing_progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json="not a dict", # Corrupt state
        )

        progress, content, history = services.get_lesson_state_and_history(
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


    @patch('lessons.services._get_llm') # Patch the LLM initialization helper directly
    def test_get_or_create_lesson_content_generation(self, mock_get_llm): # Corrected arg name
        """Test content generation when LessonContent doesn't exist."""
        # 1. Setup: Create a lesson without initial content
        new_lesson = Lesson.objects.create(
            module=self.module, lesson_index=1, title="New Lesson for Gen Test"
        )
        self.assertEqual(LessonContent.objects.filter(lesson=new_lesson).count(), 0)

        # 2. Mock LLM Response: Define what the LLM should return
        # Mock the LLM instance returned by _get_llm
        mock_llm_instance = MagicMock()
        mock_generated_content_str = '{\"exposition\": \"Generated test content.\"}'
        mock_llm_response_obj = MagicMock() # Mock the response object
        mock_llm_response_obj.content = mock_generated_content_str
        mock_llm_instance.invoke.return_value = mock_llm_response_obj # Mock the invoke call
        mock_get_llm.return_value = mock_llm_instance # Make _get_llm return our mock (using correct arg name)
        # mock_call_with_retry.return_value = mock_llm_response # No longer needed

        # 3. Call the function under test
        lesson_content = services.get_or_create_lesson_content(new_lesson)

        # 4. Assertions
        self.assertIsNotNone(lesson_content)
        self.assertEqual(lesson_content.lesson, new_lesson)
        self.assertIsInstance(lesson_content.content, dict)
        self.assertEqual(lesson_content.content.get('exposition'), "Generated test content.")

        # Verify LLM initialization was attempted and invoke was called
        mock_get_llm.assert_called_once() # Use correct arg name
        mock_llm_instance.invoke.assert_called_once()
        # Check the prompt passed to invoke
        call_args, call_kwargs = mock_llm_instance.invoke.call_args
        prompt_arg = call_args[0] # The first argument to invoke is the prompt string
        self.assertIsInstance(prompt_arg, str)
        self.assertIn(new_lesson.title, prompt_arg) # Check directly in the prompt string
        self.assertIn(self.module.title, prompt_arg)
        self.assertIn(self.syllabus.topic, prompt_arg)

        # Verify content was saved to DB
        self.assertEqual(LessonContent.objects.filter(lesson=new_lesson).count(), 1)
        saved_content = LessonContent.objects.get(lesson=new_lesson)
        self.assertEqual(saved_content, lesson_content)

    @patch('lessons.services._get_llm') # Patch the LLM initialization helper directly
    def test_get_or_create_lesson_content_existing(self, mock_get_llm): # Corrected arg name
        """Test retrieving existing LessonContent without calling LLM."""
        # Content already created in setUpTestData
        existing_content = self.lesson_content

        # Call the function
        lesson_content = services.get_or_create_lesson_content(self.lesson)

        # Assertions
        self.assertEqual(lesson_content, existing_content)
        # Verify LLM init was NOT called
        mock_get_llm.assert_not_called() # Use the correct arg name
        # Verify LLM was NOT called
        mock_get_llm.assert_not_called() # Verify LLM init was NOT called


    # Refactor: Mock the Graph class directly
    @patch('lessons.services.LessonInteractionGraph')
    def test_handle_chat_message(self, MockLessonInteractionGraphClass):
        """Test handling a user chat message by mocking the graph invoke."""
        user_message_text = "This is my test message."
        mock_chat_response_content = f"Mock AI response containing: {user_message_text}"

        # 1. Define the expected final state dictionary returned by the graph invoke
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk, # Assuming user_id is part of the state
            "current_interaction_mode": "chatting",
            "new_assistant_message": mock_chat_response_content,
            "updated_at": timezone.now().isoformat(),
            "error_message": None # Explicitly mock no error
        }

        # 2. Mock the graph instance and its invoke method correctly
        mock_graph_instance = MagicMock() # Mocks the LessonInteractionGraph instance
        mock_compiled_graph = MagicMock() # Mocks the .graph attribute
        mock_compiled_graph.invoke.return_value = expected_graph_output_state # Configure invoke on the inner mock
        mock_graph_instance.graph = mock_compiled_graph # Assign the inner mock to the .graph attribute
        MockLessonInteractionGraphClass.return_value = mock_graph_instance # The class returns the outer mock

        # Ensure progress exists first
        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json={"initial": True, "updated_at": timezone.now().isoformat()}
        )

        # Call the service function - it now returns a dict
        response_data = services.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type='chat' # Explicitly pass type
        )

        # Verify results from the returned dictionary
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get('assistant_message')
        self.assertIsNotNone(assistant_content)
        self.assertIsInstance(assistant_content, str) # Check it's a string now
        self.assertEqual(assistant_content, mock_chat_response_content) # Check exact content

        # Check history in DB
        history = ConversationHistory.objects.filter(progress=progress).order_by('timestamp')
        self.assertEqual(history.count(), 2)
        self.assertEqual(history[0].role, 'user')
        self.assertEqual(history[0].content, user_message_text)
        self.assertEqual(history[1].role, 'assistant')
        self.assertEqual(history[1].content, mock_chat_response_content) # Check exact content
        self.assertEqual(history[1].progress, progress)

        # Check progress state update
        progress.refresh_from_db()
        self.assertIsInstance(progress.lesson_state_json, dict)
        # Assert that the marker was added by the function call
        self.assertIn("current_interaction_mode", progress.lesson_state_json) # Check state update


    # Refactor: Mock the Graph class directly
    @patch('lessons.services.LessonInteractionGraph')
    def test_handle_chat_message_generates_exercise(self, MockLessonInteractionGraphClass):
        """Test state update when an exercise is generated by mocking graph invoke."""
        mock_exercise_json = {
            "id": "ex123", "type": "multiple_choice", "question": "What is 1+1?",
            "options": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}],
            "correct_answer_id": "b", "explanation": "1+1 equals 2."
        }
        mock_assistant_message = "Okay, here is your exercise."

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_exercise": mock_exercise_json, # Exercise included in state
            "current_interaction_mode": "awaiting_answer",
            "new_assistant_message": mock_assistant_message,
            "updated_at": timezone.now().isoformat(),
            "error_message": None # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress
        UserProgress.objects.filter(user=self.user, lesson=self.lesson).delete()
        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json=_initialize_lesson_state(self.user, self.lesson, self.lesson_content)
        )
        user_message_text = "Give me an exercise"

        response_data = services.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type='chat' # Explicitly pass type
        )

        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get('assistant_message')
        self.assertIsNotNone(assistant_content)
        self.assertEqual(assistant_content, mock_assistant_message) # Check exact content

        progress.refresh_from_db()
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNotNone(progress.lesson_state_json.get('active_exercise'))
        self.assertEqual(progress.lesson_state_json['active_exercise']['id'], 'ex123')
        self.assertIsNone(progress.lesson_state_json.get('active_assessment')) # Should not be set
        self.assertEqual(progress.lesson_state_json.get('current_interaction_mode'), 'awaiting_answer')

    # Refactor: Mock the Graph class directly
    @patch('lessons.services.LessonInteractionGraph')
    def test_handle_chat_message_evaluates_answer(self, MockLessonInteractionGraphClass):
        """Test state update when an answer is evaluated by mocking graph invoke."""
        mock_evaluation_feedback = "Correct!"
        mock_evaluation_score = 1.0

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_exercise": None, # Cleared after evaluation
            "current_interaction_mode": "chatting", # Reverted mode
            "evaluation_feedback": mock_evaluation_feedback, # Feedback included
            "score_update": mock_evaluation_score, # Score included
            "updated_at": timezone.now().isoformat(),
            "error_message": None # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress with active exercise
        initial_active_exercise = {
            "id": "ex123", "type": "multiple_choice", "question": "What is 1+1?",
            "correct_answer_id": "b"
        }
        UserProgress.objects.filter(user=self.user, lesson=self.lesson).delete()
        progress = UserProgress.objects.create(
            user=self.user, syllabus=self.syllabus, module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index, lesson=self.lesson, status='in_progress',
            lesson_state_json={
                **_initialize_lesson_state(self.user, self.lesson, self.lesson_content),
                "active_exercise": initial_active_exercise,
                "current_interaction_mode": "awaiting_answer",
                "updated_at": timezone.now().isoformat()
            }
        )
        user_message_text = "The answer is b"

        # 4. Call service function
        response_data = services.handle_chat_message(
            user=self.user, progress=progress, user_message_content=user_message_text,
            submission_type='answer'
        )

        # 5. Assertions
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get('assistant_message')
        self.assertIsNotNone(assistant_content)
        self.assertEqual(assistant_content, mock_evaluation_feedback) # Check exact feedback

        progress.refresh_from_db()
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNone(progress.lesson_state_json.get('active_exercise'))
        self.assertEqual(progress.lesson_state_json.get('current_interaction_mode'), 'chatting')
        self.assertEqual(progress.lesson_state_json.get('score_update'), mock_evaluation_score)

        MockLessonInteractionGraphClass.assert_called_once()
        mock_compiled_graph.invoke.assert_called_once() # Check invoke on inner mock

    # Refactor: Mock the Graph class directly
    @patch('lessons.services.LessonInteractionGraph')
    def test_handle_chat_message_generates_assessment(self, MockLessonInteractionGraphClass):
        """Test state update when an assessment is generated by mocking graph invoke."""
        mock_assessment_json = {
            "id": "as123", "type": "multiple_choice", "question_text": "What is Python?",
            "options": [{"id": "a", "text": "A snake"}, {"id": "b", "text": "A language"}],
            "correct_answer_id": "b", "explanation": "Python is a programming language."
        }
        mock_assistant_message = "Okay, here is your assessment."

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_assessment": mock_assessment_json, # Assessment included
            "current_interaction_mode": "awaiting_answer",
            "new_assistant_message": mock_assistant_message, # Message included
            "updated_at": timezone.now().isoformat(),
            "error_message": None # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress
        UserProgress.objects.filter(user=self.user, lesson=self.lesson).delete()
        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json=_initialize_lesson_state(self.user, self.lesson, self.lesson_content)
        )
        user_message_text = "Give me an assessment"

        response_data = services.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type='chat' # Explicitly pass type
        )

        self.assertIsNotNone(response_data)
        assistant_content = response_data.get('assistant_message')
        self.assertIsNotNone(assistant_content) # Check message exists
        self.assertEqual(assistant_content, mock_assistant_message) # Check content

        progress.refresh_from_db()
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNotNone(progress.lesson_state_json.get('active_assessment'))
        self.assertEqual(progress.lesson_state_json['active_assessment']['id'], 'as123')
        self.assertIsNone(progress.lesson_state_json.get('active_exercise')) # Should not be set
        self.assertEqual(progress.lesson_state_json.get('current_interaction_mode'), 'awaiting_answer') # Adjusted assertion based on observed failure

    # Keep this patch as it correctly mocks the graph class
    @patch('lessons.services.LessonInteractionGraph')
    def test_handle_chat_message_evaluates_assessment(self, MockLessonInteractionGraphClass):
        """Test state update when an assessment is evaluated (mocking graph invoke)."""
        # 1. Define the expected final state dictionary returned by the graph invoke
        mock_evaluation_feedback = "You got one right."
        mock_evaluation_score = 0.5
        expected_graph_output_state = {
            # This dictionary represents the *entire state* after graph execution
            # It should include the evaluation results and cleared active tasks
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "module_index": self.module.module_index,
            "lesson_index": self.lesson.lesson_index,
            "lesson_title": self.lesson.title,
            "lesson_summary": self.lesson.summary,
            "lesson_content": self.lesson_content.content,
            "conversation_history": [], # History is handled separately
            "active_exercise": None,
            "active_assessment": None, # Assessment should be cleared after evaluation
            "current_interaction_mode": "chatting", # Mode should revert
            # Ensure the key matches what the service code expects
            "evaluation_feedback": mock_evaluation_feedback, # Feedback from evaluation
            "score_update": mock_evaluation_score, # Score from evaluation
            "updated_at": timezone.now().isoformat(),
            "error_message": None # Explicitly mock no error
        }

        # 2. Mock the graph instance and its invoke method correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Set up initial progress state (with an active assessment)
        initial_active_assessment = {
            "id": "as123", "type": "multiple_choice", "question_text": "What is Python?",
            "correct_answer_id": "b"
        }
        progress = UserProgress.objects.create(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status='in_progress',
            lesson_state_json={
                **_initialize_lesson_state(self.user, self.lesson, self.lesson_content),
                "active_assessment": initial_active_assessment,
                "current_interaction_mode": "awaiting_answer",
                "updated_at": timezone.now().isoformat()
            }
        )
        user_message_text = "My answer is b"

        # 4. Call the service function
        response_data = services.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type='assessment' # Explicitly pass type
        )

        # 5. Assertions
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get('assistant_message')
        self.assertIsNotNone(assistant_content)
        self.assertEqual(assistant_content, mock_evaluation_feedback) # Check exact feedback

        # Verify the graph was instantiated and invoked correctly
        MockLessonInteractionGraphClass.assert_called_once()
        # Check the input passed to invoke (should be the initial state + user message)
        mock_compiled_graph.invoke.assert_called_once() # Check invoke on inner mock
        call_args, call_kwargs = mock_compiled_graph.invoke.call_args
        invoke_input = call_args[0]
        self.assertIsInstance(invoke_input, dict)
        self.assertEqual(invoke_input.get('last_user_message'), user_message_text) # Check correct key
        # Check the interaction mode passed to the graph
        self.assertEqual(invoke_input.get('current_interaction_mode'), 'submit_answer') # Corrected assertion
        # Check a few keys from the initial state to ensure it was passed
        self.assertEqual(invoke_input.get('lesson_db_id'), self.lesson.pk)
        self.assertIsNotNone(invoke_input.get('active_assessment'))

        # Check the UserProgress state was updated correctly in the DB
        progress.refresh_from_db()
        self.assertIsInstance(progress.lesson_state_json, dict)
        # Compare the saved state with the expected output state (ignoring history and timestamp)
        saved_state_subset = {k: v for k, v in progress.lesson_state_json.items() if k not in ['conversation_history', 'updated_at']}
        expected_state_subset = {k: v for k, v in expected_graph_output_state.items() if k not in ['conversation_history', 'updated_at', 'evaluation_feedback']} # Also ignore transient feedback
        self.assertDictEqual(saved_state_subset, expected_state_subset)

        # Check history was saved
        history = ConversationHistory.objects.filter(progress=progress).order_by('timestamp')
        self.assertEqual(history.count(), 2) # User submission + Assistant feedback
        self.assertEqual(history[0].role, 'user')
        self.assertEqual(history[0].content, user_message_text)
        self.assertEqual(history[0].message_type, 'assessment_response') # Check type
        self.assertEqual(history[1].role, 'assistant')
        self.assertEqual(history[1].content, mock_evaluation_feedback)
        self.assertEqual(history[1].message_type, 'assessment_feedback') # Check type