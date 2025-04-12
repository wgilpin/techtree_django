"""URL configuration for the syllabus app."""

from django.urls import path

from . import views

app_name = "syllabus"

urlpatterns = [
    path("", views.syllabus_landing, name="landing"),
    path("generate/", views.generate_syllabus_view, name="generate"),
    path("<uuid:syllabus_id>/", views.syllabus_detail, name="detail"),
    path(
        "<uuid:syllabus_id>/module/<int:module_index>/",
        views.module_detail,
        name="module_detail",
    ),
    path(
        "<uuid:syllabus_id>/module/<int:module_index>/lesson/<int:lesson_index>/",
        views.lesson_detail,
        name="lesson_detail",
    ),
    path("wait/<uuid:task_id>/", views.wait_for_generation, name="wait_for_generation"),

    # Add other syllabus-related URLs here
]