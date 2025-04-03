"""Core models for the TechTree Django application."""

import uuid
from typing import Optional, TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone

# For type checking ForeignKey relations to Django's User model
if TYPE_CHECKING:
    from django.contrib.auth.models import User


class UserAssessment(models.Model):
    """Represents a user's assessment on a specific topic."""
    assessment_id: models.UUIDField = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    # Use string reference for User model if not imported directly
    # Ensure Optional is used for nullable ForeignKey
    user: models.ForeignKey[Optional["User"]] = models.ForeignKey( # type: ignore[misc]
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who took the assessment."
    )
    topic: models.CharField = models.CharField(
        max_length=255,
        help_text="The topic of the assessment."
    )
    knowledge_level: models.CharField = models.CharField(
        max_length=50,
        help_text="The assessed knowledge level (e.g., beginner, intermediate)."
    )
    score: models.FloatField = models.FloatField(
        null=True,
        blank=True,
        help_text="The numerical score achieved, if applicable."
    )
    # Annotate JSONField content type if possible, otherwise use Any
    question_history: models.JSONField = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON containing the history of questions asked."
    )
    response_history: models.JSONField = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON containing the history of user responses."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the assessment was created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the assessment was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the assessment."""
        # Access user safely, might be None
        user_repr = self.user.username if self.user else "Unknown User"  # type: ignore[attr-defined] # pylint: disable=no-member
        return f"Assessment for {user_repr} on {self.topic}"

    class Meta:
        """Meta options for UserAssessment."""
        indexes = [
            models.Index(fields=['user']),
        ]
        verbose_name = "User Assessment"
        verbose_name_plural = "User Assessments"


class Syllabus(models.Model):
    """Represents a learning syllabus for a specific topic and level."""
    syllabus_id: models.UUIDField = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    # Ensure Optional is used for nullable ForeignKey
    user: models.ForeignKey[Optional["User"]] = models.ForeignKey( # type: ignore[misc]
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user for whom this syllabus was generated (if any)."
    )
    topic: models.CharField = models.CharField(
        max_length=255,
        help_text="The main topic of the syllabus."
    )
    level: models.CharField = models.CharField(
        max_length=50,
        help_text="The target knowledge level (e.g., beginner, advanced)."
    )
    user_entered_topic: models.TextField = models.TextField(
        null=True,
        blank=True,
        help_text="The original topic string entered by the user, if different."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the syllabus was created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the syllabus was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the syllabus."""
        return f"Syllabus: {self.topic} ({self.level})"

    class Meta:
        """Meta options for Syllabus."""
        indexes = [
            models.Index(fields=['topic', 'level']),
            models.Index(fields=['user']),
        ]
        verbose_name = "Syllabus"
        verbose_name_plural = "Syllabi"


class Module(models.Model):
    """Represents a module within a syllabus."""
    # Django adds 'id' as primary key automatically (type int)
    id: int
    syllabus: models.ForeignKey[Syllabus] = models.ForeignKey(
        Syllabus,
        on_delete=models.CASCADE,
        related_name='modules',
        help_text="The syllabus this module belongs to."
    )
    module_index: models.IntegerField = models.IntegerField(
        help_text="The sequential index of this module within the syllabus."
    )
    title: models.CharField = models.CharField(
        max_length=255,
        help_text="The title of the module."
    )
    summary: models.TextField = models.TextField(
        null=True,
        blank=True,
        help_text="A brief summary of the module content."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the module was created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the module was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the module."""
        # Correctly access related syllabus ID
        return f"Module {self.module_index}: {self.title} (Syllabus: {self.syllabus.pk})"  # type: ignore[attr-defined] # pylint: disable=no-member

    class Meta:
        """Meta options for Module."""
        unique_together = ('syllabus', 'module_index')
        ordering = ['syllabus', 'module_index']
        indexes = [
            models.Index(fields=['syllabus']),
        ]


class Lesson(models.Model):
    """Represents a lesson within a module."""
    # Django adds 'id' as primary key automatically (type int)
    id: int
    module: models.ForeignKey[Module] = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='lessons',
        help_text="The module this lesson belongs to."
    )
    lesson_index: models.IntegerField = models.IntegerField(
        help_text="The sequential index of this lesson within the module."
    )
    title: models.CharField = models.CharField(
        max_length=255,
        help_text="The title of the lesson."
    )
    summary: models.TextField = models.TextField(
        null=True,
        blank=True,
        help_text="A brief summary of the lesson content."
    )
    duration: models.IntegerField = models.IntegerField(
        null=True,
        blank=True,
        help_text="Estimated duration of the lesson in minutes."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the lesson was created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the lesson was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the lesson."""
        # Correctly access related module ID
        return f"Lesson {self.lesson_index}: {self.title} (Module: {self.module.pk})"  # type: ignore[attr-defined] # pylint: disable=no-member

    class Meta:
        """Meta options for Lesson."""
        unique_together = ('module', 'lesson_index')
        ordering = ['module', 'lesson_index']
        indexes = [
            models.Index(fields=['module']),
        ]


class LessonContent(models.Model):
    """Stores the actual content for a lesson, likely in JSON format."""
    content_id: models.UUIDField = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    lesson: models.ForeignKey[Lesson] = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='content_items',
        help_text="The lesson this content belongs to."
    )
    content: models.JSONField = models.JSONField(
        help_text="The structured content of the lesson (e.g., text, exercises)."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the content was created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the content was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the lesson content."""
        # Correctly access related lesson ID
        return f"Content for Lesson {self.lesson.pk}"  # type: ignore[attr-defined] # pylint: disable=no-member

    class Meta:
        """Meta options for LessonContent."""
        indexes = [
            models.Index(fields=['lesson']),
        ]
        verbose_name = "Lesson Content"
        verbose_name_plural = "Lesson Contents"


class UserProgress(models.Model):
    """Tracks a user's progress through a specific lesson in a syllabus."""
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    progress_id: models.UUIDField = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user: models.ForeignKey["User"] = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text="The user whose progress is being tracked."
    )
    syllabus: models.ForeignKey[Syllabus] = models.ForeignKey(
        Syllabus,
        on_delete=models.CASCADE,
        help_text="The syllabus the progress relates to."
    )
     # Ensure Optional is used for nullable ForeignKey
    lesson: models.ForeignKey[Optional[Lesson]] = models.ForeignKey( # type: ignore[misc]
        Lesson,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The specific lesson the progress relates to."
    )
    module_index: models.IntegerField = models.IntegerField(
        help_text="Original module index (potentially redundant if lesson FK is used)."
    )
    lesson_index: models.IntegerField = models.IntegerField(
        help_text="Original lesson index (potentially redundant if lesson FK is used)."
    )
    status: models.CharField = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='not_started',
        help_text="The current completion status of the lesson for the user."
    )
    score: models.FloatField = models.FloatField(
        null=True,
        blank=True,
        help_text="Score achieved by the user for this lesson, if applicable."
    )
    lesson_state_json: models.JSONField = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON blob storing conversational state or other lesson-specific data."
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the progress record was first created."
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the progress record was last updated."
    )

    def __str__(self) -> str:
        """Return a string representation of the user progress."""
        # Check if lesson exists before accessing title
        lesson_title = self.lesson.title if self.lesson else "N/A"  # type: ignore[attr-defined] # pylint: disable=no-member
        user_repr = self.user.username if self.user else "Unknown User"  # type: ignore[attr-defined] # pylint: disable=no-member
        return f"Progress for {user_repr} on Lesson: {lesson_title} ({self.status})"

    class Meta:
        """Meta options for UserProgress."""
        unique_together = ('user', 'syllabus', 'module_index', 'lesson_index')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['syllabus']),
            models.Index(fields=['user', 'syllabus']),
            models.Index(fields=['lesson']),
        ]
        verbose_name = "User Progress"
        verbose_name_plural = "User Progress Records"


class ConversationHistory(models.Model):
    """Stores individual messages exchanged during a user's lesson interaction."""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    MESSAGE_TYPE_CHOICES = [
        ('chat', 'Chat Message'),
        ('exercise_prompt', 'Exercise Prompt'),
        ('exercise_response', 'Exercise Response'),
        ('system_update', 'System Update'),
    ]

    message_id: models.UUIDField = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    progress: models.ForeignKey[UserProgress] = models.ForeignKey(
        UserProgress,
        on_delete=models.CASCADE,
        related_name='conversation_history',
        help_text="The user progress record this message belongs to."
    )
    timestamp: models.DateTimeField = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Timestamp when the message was recorded."
    )
    role: models.CharField = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        help_text="The role of the sender (user, assistant, system)."
    )
    message_type: models.CharField = models.CharField(
        max_length=50,
        choices=MESSAGE_TYPE_CHOICES,
        default='chat',
        help_text="The type or context of the message."
    )
    content: models.TextField = models.TextField(
        help_text="The textual content of the message."
    )
    metadata: models.JSONField = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional JSON blob for additional message metadata."
    )

    def __str__(self) -> str:
        """Return a string representation of the conversation message."""
        # Content is TextField (str), slicing is valid.
        return f"{self.role} ({self.message_type}) at {self.timestamp}: {self.content[:50]}..."  # pylint: disable=unsubscriptable-object

    class Meta:
        """Meta options for ConversationHistory."""
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['progress']),
            models.Index(fields=['timestamp']),
        ]
        verbose_name = "Conversation History Message"
        verbose_name_plural = "Conversation History"
