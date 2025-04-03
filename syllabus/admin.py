from django.contrib import admin

# Import models from core app
from core.models import Syllabus, Module, Lesson

# Register your models here.

@admin.register(Syllabus)
class SyllabusAdmin(admin.ModelAdmin):
    """Admin configuration for Syllabus model."""
    list_display = ('topic', 'level', 'user', 'created_at', 'syllabus_id')
    list_filter = ('level', 'user')
    search_fields = ('topic', 'user__username') # Search by topic or username
    readonly_fields = ('syllabus_id', 'created_at', 'updated_at')

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    """Admin configuration for Module model."""
    list_display = ('title', 'module_index', 'syllabus', 'created_at')
    list_filter = ('syllabus__topic',) # Filter by syllabus topic
    search_fields = ('title', 'syllabus__topic')
    readonly_fields = ('created_at', 'updated_at')
    # Link to syllabus admin page
    list_select_related = ('syllabus',)

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    """Admin configuration for Lesson model."""
    list_display = ('title', 'lesson_index', 'module', 'created_at')
    list_filter = ('module__syllabus__topic', 'module') # Filter by syllabus topic or module
    search_fields = ('title', 'module__title', 'module__syllabus__topic')
    readonly_fields = ('created_at', 'updated_at')
    # Link to module admin page
    list_select_related = ('module', 'module__syllabus')
