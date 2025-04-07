"""Tests for the core Django app."""

# pylint: disable=no-member

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.test import Client
from django.contrib.auth.models import User
from .models import (
    UserAssessment,
    Syllabus,
    Module,
    Lesson,
    LessonContent,
    UserProgress,
    ConversationHistory,
)


class CoreModelTests(TestCase):
    """Tests for the models in the core app."""

    @classmethod
    def setUpTestData(cls):
        """Set up non-modified objects used by all test methods."""
        cls.user = User.objects.create_user(username="testuser", password="password123")
        cls.assessment = UserAssessment.objects.create(
            user=cls.user, topic="Python Basics", knowledge_level="Intermediate"
        )
        cls.syllabus = Syllabus.objects.create(
            user=cls.user, topic="Intro to Python", level="Beginner"
        )
        cls.module = Module.objects.create(
            syllabus=cls.syllabus, title="Python Syntax", module_index=1
        )
        cls.lesson = Lesson.objects.create(
            module=cls.module, title="Variables", lesson_index=1
        )
        cls.lesson_content = LessonContent.objects.create(
            lesson=cls.lesson,
            content={"type": "text", "value": "Variables store data."},
        )
        cls.user_progress = UserProgress.objects.create(
            user=cls.user,
            syllabus=cls.syllabus,
            module_index=cls.module.module_index,
            lesson_index=cls.lesson.lesson_index,
            lesson=cls.lesson,  # Keep lesson FK for easier access if needed
            status="completed",
        )
        # Need timezone for default timestamp comparison later

        cls.conversation = ConversationHistory.objects.create(
            progress=cls.user_progress,
            role="user",
            content="User message",
            # message_type defaults to 'chat'
        )

    def test_user_assessment_creation(self):
        """Test UserAssessment model instance creation and __str__."""
        self.assertEqual(self.assessment.user, self.user)
        self.assertEqual(self.assessment.topic, "Python Basics")
        self.assertEqual(self.assessment.knowledge_level, "Intermediate")
        self.assertEqual(
            str(self.assessment), "Assessment for testuser on Python Basics"
        )

    def test_syllabus_creation(self):
        """Test Syllabus model instance creation and __str__."""
        self.assertEqual(self.syllabus.user, self.user)
        self.assertEqual(self.syllabus.topic, "Intro to Python")
        self.assertEqual(self.syllabus.level, "Beginner")
        self.assertEqual(str(self.syllabus), "Syllabus: Intro to Python (Beginner)")

    def test_module_creation(self):
        """Test Module model instance creation and __str__."""
        self.assertEqual(self.module.syllabus, self.syllabus)
        self.assertEqual(self.module.title, "Python Syntax")
        self.assertEqual(self.module.module_index, 1)
        expected_str = f"Module {self.module.module_index}: {self.module.title} (Syllabus: {self.syllabus.pk})"
        self.assertEqual(str(self.module), expected_str)

    def test_lesson_creation(self):
        """Test Lesson model instance creation and __str__."""
        self.assertEqual(self.lesson.module, self.module)
        self.assertEqual(self.lesson.title, "Variables")
        self.assertEqual(self.lesson.lesson_index, 1)
        expected_str = f"Lesson {self.lesson.lesson_index}: {self.lesson.title} (Module: {self.module.pk})"
        self.assertEqual(str(self.lesson), expected_str)

    def test_lesson_content_creation(self):
        """Test LessonContent model instance creation and __str__."""
        self.assertEqual(self.lesson_content.lesson, self.lesson)
        self.assertEqual(self.lesson_content.content["type"], "text")
        self.assertEqual(self.lesson_content.content["value"], "Variables store data.")
        expected_str = f"Content for Lesson {self.lesson.pk}"
        self.assertEqual(str(self.lesson_content), expected_str)

    def test_user_progress_creation(self):
        """Test UserProgress model instance creation and __str__."""
        self.assertEqual(self.user_progress.user, self.user)
        self.assertEqual(self.user_progress.syllabus, self.syllabus)
        self.assertEqual(self.user_progress.module_index, 1)
        self.assertEqual(self.user_progress.lesson_index, 1)
        self.assertEqual(self.user_progress.lesson, self.lesson)
        self.assertEqual(self.user_progress.status, "completed")
        expected_str = f"Progress for {self.user.username} on Lesson: {self.lesson.title} (completed)"
        self.assertEqual(str(self.user_progress), expected_str)

    def test_conversation_history_creation(self):
        """Test ConversationHistory model instance creation and __str__."""
        self.assertEqual(self.conversation.progress, self.user_progress)
        self.assertEqual(self.conversation.role, "user")
        self.assertEqual(self.conversation.content, "User message")
        self.assertEqual(self.conversation.message_type, "chat")  # Check default
        # Check timestamp is recent (within a tolerance)
        self.assertLess(
            (timezone.now() - self.conversation.timestamp).total_seconds(), 5
        )
        expected_str = (
            f"{self.conversation.role} ({self.conversation.message_type}) at "
            f"{self.conversation.timestamp}: {self.conversation.content[:50]}..."
        )
        self.assertEqual(str(self.conversation), expected_str)


class CoreViewTests(TestCase):
    """Tests for the views in the core app."""

    def setUp(self):
        """Set up the test client and a user."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser_view", password="password123", email="test@example.com"
        )
        self.register_url = reverse("register")
        self.login_url = reverse("login")
        self.dashboard_url = reverse("dashboard")
        self.index_url = reverse("index")

    def test_index_view_status_code(self):
        """Test the index view returns a 200 status code."""
        response = self.client.get(self.index_url)
        self.assertEqual(response.status_code, 200)

    def test_index_view_uses_correct_template(self):
        """Test the index view uses the correct template."""
        response = self.client.get(self.index_url)
        self.assertTemplateUsed(response, "core/index.html")

    def test_dashboard_view_redirects_unauthenticated(self):
        """Test the dashboard view redirects if user is not logged in."""
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, f"{self.login_url}?next={self.dashboard_url}")

    def test_dashboard_view_authenticated(self):
        """Test the dashboard view for an authenticated user."""
        self.client.login(username="testuser_view", password="password123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/dashboard.html")
        self.assertContains(
            response, "Welcome, testuser_view"
        )  # Check if username is displayed

    def test_register_view_get(self):
        """Test the register view returns 200 for GET requests."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")

    def test_register_view_post_success(self):
        """Test successful user registration via POST request."""
        user_data = {
            "username": "newuser",
            "email": "new@example.com",  # Note: UserCreationForm doesn't handle email by default
            "password1": "newpassword123",
            "password2": "newpassword123",
        }
        response = self.client.post(self.register_url, user_data)
        # Should redirect to login page after successful registration
        self.assertRedirects(response, self.login_url)
        # Check if the user was actually created
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_register_view_post_password_mismatch(self):
        """Test user registration failure with mismatched passwords."""
        user_data = {
            "username": "anotheruser",
            "email": "another@example.com",  # Note: UserCreationForm doesn't handle email by default
            "password1": "password123",
            "password2": "differentpassword",
        }
        response = self.client.post(self.register_url, user_data)
        self.assertEqual(response.status_code, 200)  # Should re-render the form
        self.assertTemplateUsed(response, "registration/register.html")
        # UserCreationForm's error message for password mismatch
        self.assertContains(
            response, "The two password fields didn’t match."
        )  # Use Unicode apostrophe
        self.assertFalse(User.objects.filter(username="anotheruser").exists())

    def test_register_view_post_existing_username(self):
        """Test user registration failure with an existing username."""
        user_data = {
            "username": "testuser_view",  # Existing username from setUp
            "email": "unique@example.com",  # Note: UserCreationForm doesn't handle email by default
            "password1": "password123",
            "password2": "password123",
        }
        response = self.client.post(self.register_url, user_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")
        self.assertContains(response, "A user with that username already exists.")
