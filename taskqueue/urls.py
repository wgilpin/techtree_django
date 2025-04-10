"""
URL configuration for the taskqueue app.
"""

from django.urls import path
from . import views

app_name = 'taskqueue'

urlpatterns = [
    path("api/tasks/status/<uuid:task_id>/", views.check_task_status, name="check_task_status"),
    path("dashboard/", views.dashboard, name="dashboard"),
]