"""URL configuration for the core app."""

from django.urls import path
from . import views  # Import views from the current core app

# Define URL names for use in templates {% url '...' %}
# app_name = 'core' # Removed namespace for simplicity as it's included at root

urlpatterns = [
    # Example: Map root URL of the app to an index view
    path("", views.index, name="index"),
    # Map dashboard URL to a dashboard view
    path("dashboard/", views.dashboard, name="dashboard"),
    # Map register URL to a registration view
    # Note: Django's auth URLs handle login/logout, but registration needs a custom view
    path("register/", views.register, name="register"),
    # Add other core app URLs here as needed
]
