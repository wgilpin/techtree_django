# mypy: disable-error-code="attr-defined"
""" Definitions for the Django admin site """

import json  # Import json for pretty printing
from django.contrib import admin

# Import models from core app
from core.models import LessonContent

@admin.register(LessonContent)
class LessonContentAdmin(admin.ModelAdmin):
    """Admin configuration for LessonContent model."""
    list_display = ('lesson_title', 'lesson_id', 'created_at', 'content_id')
    list_filter = ('lesson__module__syllabus__topic', 'lesson__module') # Filter by syllabus topic or module
    search_fields = ('lesson__title', 'lesson__module__title', 'lesson__module__syllabus__topic')
    readonly_fields = ('content_id', 'created_at', 'updated_at', 'pretty_content')
    # Add a method to display the lesson title
    list_select_related = ('lesson', 'lesson__module', 'lesson__module__syllabus')

    # Add a field to display the JSON content nicely formatted
    fields = ('lesson', 'pretty_content', 'created_at', 'updated_at', 'content_id')

    def lesson_title(self, obj: LessonContent) -> str:
        """Return the title of the related lesson."""
        return obj.lesson.title if obj.lesson else "N/A"
    lesson_title.short_description = 'Lesson Title' # Column header
    lesson_title.admin_order_field = 'lesson__title' # Allow sorting

    def lesson_id(self, obj: LessonContent) -> int | str:
        """Return the ID of the related lesson."""
        return obj.lesson.id if obj.lesson else "N/A"
    lesson_id.short_description = 'Lesson ID'
    lesson_id.admin_order_field = 'lesson__id'

    def pretty_content(self, obj: LessonContent) -> str:
        """Format the JSON content for display."""
        if isinstance(obj.content, dict):
            return json.dumps(obj.content, indent=2)
        return str(obj.content) # Fallback if not a dict
    pretty_content.short_description = 'Formatted Content'
