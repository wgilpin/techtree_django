"""Views for the core application."""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.urls import reverse
from django.db.models import Count, Q # Import Q for complex lookups if needed
from .models import Syllabus, UserProgress # Import Syllabus and UserProgress

def index(request):
    """
    Renders the home/index page.
    If the user is authenticated, redirect to the dashboard.
    """
    if request.user.is_authenticated:
        return redirect(reverse('dashboard')) # Use reverse without namespace
    # Render a simple index page for anonymous users
    # We'll create this template next
    return render(request, 'core/index.html')

@login_required # Decorator to ensure user is logged in
def dashboard(request):
    """
    Renders the user's dashboard page.
    Requires user to be logged in.
    Fetches user's syllabi (courses) and progress stats.
    """
    user = request.user
    # Fetch syllabi associated with the current user
    user_courses = Syllabus.objects.filter(user=user).order_by('created_at') # pylint: disable=no-member

    # Calculate progress statistics
    progress_records = UserProgress.objects.filter(user=user) # pylint: disable=no-member
    total_lessons_tracked = progress_records.count()
    total_completed_lessons = progress_records.filter(status='completed').count()

    # Calculate average progress
    average_progress = 0
    if total_lessons_tracked > 0:
        average_progress = round((total_completed_lessons / total_lessons_tracked) * 100)

    # Add data to the context
    context = {
        'courses': user_courses,
        'total_completed_lessons': total_completed_lessons,
        'average_progress': average_progress,
        'total_lessons_tracked': total_lessons_tracked, # Optional: might be useful
    }
    return render(request, 'core/dashboard.html', context)

def register(request):
    """
    Handles user registration.
    Uses Django's built-in UserCreationForm.
    """
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save() # Creates the user
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            return redirect(reverse('login'))
        else:
            # Form is invalid, add error messages (handled in template)
            messages.error(request, 'Please correct the errors below.')
    else:
        # GET request, display blank form
        form = UserCreationForm()

    # Render the registration template we created earlier
    return render(request, 'registration/register.html', {'form': form})
