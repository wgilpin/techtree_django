"""
URL configuration for techtree_django project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include # Import include

urlpatterns = [
    path("admin/", admin.site.urls),
    # Include Django's built-in authentication views (login, logout, password reset, etc.)
    path("accounts/", include("django.contrib.auth.urls")),
    # Include URLs from the core app
    path("", include("core.urls")),
    # Include URLs from the onboarding app
    path("onboarding/", include("onboarding.urls")),
    path("syllabus/", include("syllabus.urls")), # Include syllabus app URLs
    path("lessons/", include("lessons.urls")), # Include lessons app URLs
]
