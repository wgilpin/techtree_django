"""
Models for the taskqueue app, including AITask which tracks background AI processing tasks.
"""

import uuid

from django.db import models


class AITask(models.Model):
    """
    Model representing an AI-related background task, including its type, status, input, result, and related objects.
    """

    class TaskType(models.TextChoices):
        """
        Enumeration of AI task types such as syllabus generation, lesson content creation, and lesson interaction.
        """
        SYLLABUS_GENERATION = "syllabus_generation", "Syllabus Generation"
        LESSON_CONTENT = "lesson_content", "Lesson Content Generation"
        LESSON_INTERACTION = "lesson_interaction", "Lesson Interaction"
        ONBOARDING_ASSESSMENT = "onboarding_assessment", "Onboarding Assessment"

    class TaskStatus(models.TextChoices):
        """
        Enumeration of task statuses including pending, processing, completed, and failed.
        """
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    task_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_type = models.CharField(max_length=50, choices=TaskType.choices)
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING
    )
    input_data = models.JSONField()
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    attempt_count = models.IntegerField(default=0)

    # Add relevant foreign keys based on task type
    syllabus = models.ForeignKey(
        "core.Syllabus", null=True, blank=True, on_delete=models.CASCADE
    )
    lesson = models.ForeignKey(
        "core.Lesson", null=True, blank=True, on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.task_type} - {self.status} - {self.task_id}"
