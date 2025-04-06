"""Admin configurations for the core application models."""

# mypy: disable-error-code="attr-defined"

from django.contrib import admin
from .models import (
    ConversationHistory, UserProgress, Syllabus, Module, Lesson, LessonContent, UserAssessment
)

class ConversationHistoryAdmin(admin.ModelAdmin):
    """Admin configuration for the ConversationHistory model."""
    list_display = ('get_user', 'get_lesson', 'timestamp', 'role', 'message_type', 'rendered_content') # Use new method
    list_filter = ('role', 'message_type', 'timestamp', 'progress__user', 'progress__lesson')
    search_fields = ('content', 'progress__user__username')
    readonly_fields = ('timestamp',) # Timestamp shouldn't be editable

    @admin.display(description='User')
    def get_user(self, obj) -> str:
        """Return the username associated with the conversation message."""
        # Safely access user through progress
        return obj.progress.user.username if obj.progress and obj.progress.user else 'N/A'

    @admin.display(description='Lesson')
    def get_lesson(self, obj) -> str:
        """Return the title of the lesson associated with the conversation message."""
        # Safely access lesson through progress
        return obj.progress.lesson.title if obj.progress and obj.progress.lesson else 'N/A'

    @admin.display(description='Rendered Content')
    def rendered_content(self, obj) -> str:
        """Return the message content ."""
        return obj.content

    # Optional: Add ordering if needed
    # ordering = ('-timestamp',)

admin.site.register(ConversationHistory, ConversationHistoryAdmin)

# Also register other relevant core models if not done elsewhere
# Consider registering these if they aren't registered in their respective app's admin.py
admin.site.register(UserProgress)
admin.site.register(Syllabus)
admin.site.register(Module)
admin.site.register(Lesson)
# admin.site.register(LessonContent) # Unregister the simple one

class LessonContentAdmin(admin.ModelAdmin):
    """Admin configuration for the LessonContent model."""
    list_display = ('display_module_title_lesson_number', 'created_at') # Use new method name
    list_filter = ('lesson__module__syllabus', 'lesson__module', 'lesson') # Corrected fields
    search_fields = ('lesson__module__title', 'lesson__title', 'content_id') # Also search by module title
    ordering = ('lesson__module__module_index', 'lesson__lesson_index') # Define default ordering here

    @admin.display(description='Module Title: Lesson Number') # Removed ordering from decorator
    def display_module_title_lesson_number(self, obj) -> str:
        """Return the related module's title and lesson number formatted."""
        if obj.lesson and obj.lesson.module:
            return f"{obj.lesson.module.title}: {obj.lesson.lesson_index}"
        return "N/A" # Handle cases where lesson/module might be null

admin.site.register(LessonContent, LessonContentAdmin)
admin.site.register(UserAssessment)
