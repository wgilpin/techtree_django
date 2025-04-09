# lessons/test_services_chat.py
"""Tests for the handle_chat_message service function."""
# pylint: disable=no-member, invalid-name

from unittest.mock import patch, MagicMock

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.constants import DIFFICULTY_BEGINNER

from core.models import (
    Syllabus,
    Module,
    Lesson,
    LessonContent,
    UserProgress,
    ConversationHistory,
)
from . import services, state_service, interaction_service
from .state_service import _initialize_lesson_state  # Import the helper

User = get_user_model()


class LessonChatServiceTests(TransactionTestCase):
    """Tests for the handle_chat_message service function."""

    def setUp(self):
        """Set up non-modified objects used by all test methods."""
        self.user = User.objects.create_user(
            username="testuser_chat", password="password"
        )
        self.syllabus = Syllabus.objects.create(
            topic="Test Topic Chat", level=DIFFICULTY_BEGINNER, user=self.user
        )
        self.module = Module.objects.create(
            syllabus=self.syllabus, module_index=0, title="Test Module Chat"
        )
        self.lesson = Lesson.objects.create(
            module=self.module, lesson_index=0, title="Test Lesson Chat"
        )
        # Create initial content needed for initializing state in some tests
        self.lesson_content = LessonContent.objects.create(
            lesson=self.lesson,
            content={"exposition": "Initial test content for chat tests."},
        )

    # Refactor: Mock the Graph class directly
    @patch("lessons.interaction_service.LessonInteractionGraph")
    async def test_handle_chat_message(
        self, MockLessonInteractionGraphClass
    ):  # Make async
        """Test handling a user chat message by mocking the graph invoke."""
        user_message_text = "This is my test message."
        mock_chat_response_content = f"Mock AI response containing: {user_message_text}"

        # 1. Define the expected final state dictionary returned by the graph invoke
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,  # Assuming user_id is part of the state
            "current_interaction_mode": "chatting",
            "new_assistant_message": mock_chat_response_content,
            "updated_at": timezone.now().isoformat(),
            "error_message": None,  # Explicitly mock no error
        }

        # 2. Mock the graph instance and its invoke method correctly
        mock_graph_instance = MagicMock()  # Mocks the LessonInteractionGraph instance
        mock_compiled_graph = MagicMock()  # Mocks the .graph attribute
        mock_compiled_graph.invoke.return_value = (
            expected_graph_output_state  # Configure invoke on the inner mock
        )
        mock_graph_instance.graph = (
            mock_compiled_graph  # Assign the inner mock to the .graph attribute
        )
        MockLessonInteractionGraphClass.return_value = (
            mock_graph_instance  # The class returns the outer mock
        )

        # Ensure progress exists first (use async create)
        progress = await UserProgress.objects.acreate(
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

        # Call the service function - it now returns a dict
        response_data = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type="chat",  # Explicitly pass type
        )

        # Verify results from the returned dictionary
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get("assistant_message")
        self.assertIsNotNone(assistant_content)
        self.assertIsInstance(assistant_content, str)  # Check it's a string now
        self.assertEqual(
            assistant_content, mock_chat_response_content
        )  # Check exact content

        # Check history in DB
        # Use async filter and convert to list
        history_qs = ConversationHistory.objects.filter(progress=progress).order_by(
            "timestamp"
        )
        history = [h async for h in history_qs]
        self.assertEqual(len(history), 2)  # Use len() for list length
        self.assertEqual(history[0].role, "user")
        self.assertEqual(history[0].content, user_message_text)
        self.assertEqual(history[1].role, "assistant")
        self.assertEqual(
            history[1].content, mock_chat_response_content
        )  # Check exact content
        self.assertEqual(history[1].progress, progress)

        # Check progress state update
        await progress.arefresh_from_db()  # Use async refresh
        self.assertIsInstance(progress.lesson_state_json, dict)
        # Assert that the marker was added by the function call
        self.assertIn(
            "current_interaction_mode", progress.lesson_state_json
        )  # Check state update

    # Refactor: Mock the Graph class directly
    @patch("lessons.interaction_service.LessonInteractionGraph")
    async def test_handle_chat_message_generates_exercise(
        self, MockLessonInteractionGraphClass
    ):  # Make async
        """Test state update when an exercise is generated by mocking graph invoke."""
        mock_exercise_json = {
            "id": "ex123",
            "type": "multiple_choice",
            "question": "What is 1+1?",
            "options": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}],
            "correct_answer_id": "b",
            "explanation": "1+1 equals 2.",
        }
        mock_assistant_message = "Okay, here is your exercise."

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_exercise": mock_exercise_json,  # Exercise included in state
            "current_interaction_mode": "awaiting_answer",
            "new_assistant_message": mock_assistant_message,
            "updated_at": timezone.now().isoformat(),
            "error_message": None,  # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress
        await UserProgress.objects.filter(user=self.user, lesson=self.lesson).adelete()
        # Await the initial state first
        initial_state = await state_service._initialize_lesson_state(
            self.user, self.lesson, self.lesson_content
        )
        progress = await UserProgress.objects.acreate(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json=initial_state,  # Use the awaited state
        )
        user_message_text = "Give me an exercise"

        response_data = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type="chat",  # Explicitly pass type
        )

        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get("assistant_message")
        self.assertIsNotNone(assistant_content)
        self.assertEqual(
            assistant_content, mock_assistant_message
        )  # Check exact content

        await progress.arefresh_from_db()  # Use async refresh
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNotNone(progress.lesson_state_json.get("active_exercise"))
        self.assertEqual(progress.lesson_state_json["active_exercise"]["id"], "ex123")
        self.assertIsNone(
            progress.lesson_state_json.get("active_assessment")
        )  # Should not be set
        self.assertEqual(
            progress.lesson_state_json.get("current_interaction_mode"),
            "awaiting_answer",
        )

    # Refactor: Mock the Graph class directly
    @patch("lessons.interaction_service.LessonInteractionGraph")
    async def test_handle_chat_message_evaluates_answer(
        self, MockLessonInteractionGraphClass
    ):  # Make async
        """Test state update when an answer is evaluated by mocking graph invoke."""
        mock_evaluation_feedback = "Correct!"
        mock_evaluation_score = 1.0

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_exercise": None,  # Cleared after evaluation
            "current_interaction_mode": "chatting",  # Reverted mode
            "evaluation_feedback": mock_evaluation_feedback,  # Feedback included
            "score_update": mock_evaluation_score,  # Score included
            "updated_at": timezone.now().isoformat(),
            "error_message": None,  # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress with active exercise
        initial_active_exercise = {
            "id": "ex123",
            "type": "multiple_choice",
            "question": "What is 1+1?",
            "correct_answer_id": "b",
        }
        await UserProgress.objects.filter(user=self.user, lesson=self.lesson).adelete()
        # Await the initial state first
        initial_base_state = await state_service._initialize_lesson_state(
            self.user, self.lesson, self.lesson_content
        )
        progress = await UserProgress.objects.acreate(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                **initial_base_state,  # Unpack the awaited state
                "active_exercise": initial_active_exercise,
                "current_interaction_mode": "awaiting_answer",
                "updated_at": timezone.now().isoformat(),
            },
        )
        user_message_text = "The answer is b"

        # 4. Call service function
        response_data = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type="answer",
        )

        # 5. Assertions
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get("assistant_message")
        self.assertIsNotNone(assistant_content)
        self.assertEqual(
            assistant_content, mock_evaluation_feedback
        )  # Check exact feedback

        await progress.arefresh_from_db()  # Use async refresh
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNone(progress.lesson_state_json.get("active_exercise"))
        self.assertEqual(
            progress.lesson_state_json.get("current_interaction_mode"), "chatting"
        )
        self.assertEqual(
            progress.lesson_state_json.get("score_update"), mock_evaluation_score
        )

        MockLessonInteractionGraphClass.assert_called_once()
        mock_compiled_graph.invoke.assert_called_once()  # Check invoke on inner mock

    # Refactor: Mock the Graph class directly
    @patch("lessons.interaction_service.LessonInteractionGraph")
    async def test_handle_chat_message_generates_assessment(
        self, MockLessonInteractionGraphClass
    ):  # Make async
        """Test state update when an assessment is generated by mocking graph invoke."""
        mock_assessment_json = {
            "id": "as123",
            "type": "multiple_choice",
            "question_text": "What is Python?",
            "options": [
                {"id": "a", "text": "A snake"},
                {"id": "b", "text": "A language"},
            ],
            "correct_answer_id": "b",
            "explanation": "Python is a programming language.",
        }
        mock_assistant_message = "Okay, here is your assessment."

        # 1. Define expected final state from graph
        expected_graph_output_state = {
            "lesson_db_id": self.lesson.pk,
            "user_id": self.user.pk,
            "active_assessment": mock_assessment_json,  # Assessment included
            "current_interaction_mode": "awaiting_answer",
            "new_assistant_message": mock_assistant_message,  # Message included
            "updated_at": timezone.now().isoformat(),
            "error_message": None,  # Explicitly mock no error
        }

        # 2. Mock graph instance and invoke correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Setup progress
        await UserProgress.objects.filter(user=self.user, lesson=self.lesson).adelete()
        # Await the initial state first
        initial_state = await state_service._initialize_lesson_state(
            self.user, self.lesson, self.lesson_content
        )
        progress = await UserProgress.objects.acreate(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json=initial_state,  # Use the awaited state
        )
        user_message_text = "Give me an assessment"

        response_data = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type="chat",  # Explicitly pass type
        )

        self.assertIsNotNone(response_data)
        assistant_content = response_data.get("assistant_message")
        self.assertIsNotNone(assistant_content)  # Check message exists
        self.assertEqual(assistant_content, mock_assistant_message)  # Check content

        await progress.arefresh_from_db()  # Use async refresh
        self.assertIsInstance(progress.lesson_state_json, dict)
        self.assertIsNotNone(progress.lesson_state_json.get("active_assessment"))
        self.assertEqual(progress.lesson_state_json["active_assessment"]["id"], "as123")
        self.assertIsNone(
            progress.lesson_state_json.get("active_exercise")
        )  # Should not be set
        self.assertEqual(
            progress.lesson_state_json.get("current_interaction_mode"),
            "awaiting_answer",
        )  # Adjusted assertion based on observed failure

    # Keep this patch as it correctly mocks the graph class
    @patch("lessons.interaction_service.LessonInteractionGraph")
    async def test_handle_chat_message_evaluates_assessment(
        self, MockLessonInteractionGraphClass
    ):  # Make async
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
            "conversation_history": [],  # History is handled separately
            "active_exercise": None,
            "active_assessment": None,  # Assessment should be cleared after evaluation
            "current_interaction_mode": "chatting",  # Mode should revert
            # Ensure the key matches what the service code expects
            "evaluation_feedback": mock_evaluation_feedback,  # Feedback from evaluation
            "score_update": mock_evaluation_score,  # Score from evaluation
            "updated_at": timezone.now().isoformat(),
            "error_message": None,  # Explicitly mock no error
        }

        # 2. Mock the graph instance and its invoke method correctly
        mock_graph_instance = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_compiled_graph.invoke.return_value = expected_graph_output_state
        mock_graph_instance.graph = mock_compiled_graph
        MockLessonInteractionGraphClass.return_value = mock_graph_instance

        # 3. Set up initial progress state (with an active assessment)
        initial_active_assessment = {
            "id": "as123",
            "type": "multiple_choice",
            "question_text": "What is Python?",
            "correct_answer_id": "b",
        }
        # Await the initial state first
        initial_base_state = await state_service._initialize_lesson_state(
            self.user, self.lesson, self.lesson_content
        )
        progress = await UserProgress.objects.acreate(
            user=self.user,
            syllabus=self.syllabus,
            module_index=self.module.module_index,
            lesson_index=self.lesson.lesson_index,
            lesson=self.lesson,
            status="in_progress",
            lesson_state_json={
                **initial_base_state,  # Unpack the awaited state
                "active_assessment": initial_active_assessment,
                "current_interaction_mode": "awaiting_answer",
                "updated_at": timezone.now().isoformat(),
            },
        )
        user_message_text = "My answer is b"

        # 4. Call the service function
        response_data = interaction_service.handle_chat_message(
            user=self.user,
            progress=progress,
            user_message_content=user_message_text,
            submission_type="assessment",  # Explicitly pass type
        )

        # 5. Assertions
        self.assertIsNotNone(response_data)
        self.assertIsInstance(response_data, dict)
        assistant_content = response_data.get("assistant_message")
        self.assertIsNotNone(assistant_content)
        self.assertEqual(
            assistant_content, mock_evaluation_feedback
        )  # Check exact feedback

        # Verify the graph was instantiated and invoked correctly
        MockLessonInteractionGraphClass.assert_called_once()
        # Check the input passed to invoke (should be the initial state + user message)
        mock_compiled_graph.invoke.assert_called_once()  # Check invoke on inner mock
        call_args, _ = mock_compiled_graph.invoke.call_args
        invoke_input = call_args[0]
        self.assertIsInstance(invoke_input, dict)
        self.assertEqual(
            invoke_input.get("last_user_message"), user_message_text
        )  # Check correct key
        # Check the interaction mode passed to the graph
        self.assertEqual(
            invoke_input.get("current_interaction_mode"), "submit_answer"
        )  # Corrected assertion
        # Check a few keys from the initial state to ensure it was passed
        self.assertEqual(invoke_input.get("lesson_db_id"), self.lesson.pk)
        self.assertIsNotNone(invoke_input.get("active_assessment"))

        # Check the UserProgress state was updated correctly in the DB
        await progress.arefresh_from_db()  # Use async refresh
        self.assertIsInstance(progress.lesson_state_json, dict)
        # Compare the saved state with the expected output state (ignoring history and timestamp)
        saved_state_subset = {
            k: v
            for k, v in progress.lesson_state_json.items()
            if k not in ["conversation_history", "updated_at"]
        }
        expected_state_subset = {
            k: v
            for k, v in expected_graph_output_state.items()
            if k not in ["conversation_history", "updated_at", "evaluation_feedback"]
        }  # Also ignore transient feedback
        self.assertDictEqual(saved_state_subset, expected_state_subset)

        # Check history was saved
        # Use async filter and convert to list
        history_qs = ConversationHistory.objects.filter(progress=progress).order_by(
            "timestamp"
        )
        history = [h async for h in history_qs]
        self.assertEqual(len(history), 2)  # Use len() for list length
        self.assertEqual(history[0].role, "user")
        self.assertEqual(history[0].content, user_message_text)
        self.assertEqual(history[0].message_type, "assessment_response")  # Check type
        self.assertEqual(history[1].role, "assistant")
        self.assertEqual(history[1].content, mock_evaluation_feedback)
        self.assertEqual(history[1].message_type, "assessment_feedback")  # Check type
