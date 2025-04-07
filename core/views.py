"""Views for the core application."""
# pylint: disable=no-member

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.urls import reverse
from django.db.models import Count, Q, F, Value, FloatField, Case, When # Import ORM tools
from .models import Syllabus, UserProgress # Import models

def index(request):
    """
    Renders the home/index page.
    If the user is authenticated, redirect to the dashboard.
    """
    if request.user.is_authenticated:
        return redirect(reverse('dashboard')) # Use reverse without namespace
    # Render a simple index page for anonymous users
    return render(request, 'core/index.html')

@login_required # Decorator to ensure user is logged in
def dashboard(request):
    """
    Renders the user's dashboard page.
    Requires user to be logged in.
    Fetches user's syllabi (courses) and progress stats.
    """
    user = request.user
    # Fetch syllabi associated with the current user and annotate with progress
    user_courses = Syllabus.objects.filter(user=user).annotate( # type: ignore[misc]
        total_lessons=Count('modules__lessons', distinct=True),
        completed_lessons=Count(
            'userprogress',
            filter=Q(userprogress__user=user, userprogress__status='completed'),
            distinct=True
        )
    ).annotate(
        progress_percentage=Case(
            When(total_lessons=0, then=Value(0.0)), # Handle division by zero
            default=(F('completed_lessons') * 100.0 / F('total_lessons')),
            output_field=FloatField()
        )
    ).order_by('created_at')

    # Calculate overall aggregate statistics (can differ from sum of annotated values)
    progress_records = UserProgress.objects.filter(user=user) # type: ignore[misc]
    total_lessons_tracked_agg = progress_records.count()
    total_completed_lessons_agg = progress_records.filter(status='completed').count()

    # Calculate average progress based on all tracked progress records
    average_progress = 0
    if total_lessons_tracked_agg > 0:
        average_progress = round((total_completed_lessons_agg / total_lessons_tracked_agg) * 100)

    # Add data to the context
    context = {
        'courses': user_courses, # Annotated courses list
        'total_completed_lessons': total_completed_lessons_agg, # Overall completed
        'average_progress': average_progress, # Overall average
        'total_lessons_tracked': total_lessons_tracked_agg, # Overall tracked
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
