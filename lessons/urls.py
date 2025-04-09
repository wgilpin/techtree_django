"""URL configuration for the lessons app."""

from django.urls import path, URLPattern

from . import views

app_name = "lessons"

urlpatterns: list[URLPattern] = [
    # Example: path('<int:lesson_id>/', views.lesson_detail, name='lesson_detail'),
    # Removed 'syllabus/' prefix as it's handled in the main urls.py include
    path("<uuid:syllabus_id>/module/<int:module_index>/lesson/<int:lesson_index>/", views.lesson_detail, name="lesson_detail"),
    path("<uuid:syllabus_id>/module/<int:module_index>/lesson/<int:lesson_index>/interact/", views.handle_lesson_interaction, name="handle_interaction"),
    # New URL for asynchronous content generation
    path("<uuid:syllabus_id>/module/<int:module_index>/lesson/<int:lesson_index>/generate_content/", views.generate_lesson_content_async, name="generate_content_async"),
    path("<uuid:syllabus_id>/module/<int:module_index>/lesson/<int:lesson_index>/check_content_status/", views.check_lesson_content_status, name="check_content_status"),
    # URL to handle changing to a lower difficulty level
    path("<uuid:syllabus_id>/change-difficulty/", views.change_difficulty_view, name="change_difficulty"),
]