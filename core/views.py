"""Views for the core application."""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages # Import messages framework
from django.urls import reverse # Import reverse for redirecting

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
    """
    # We'll create this template next
    # Add any context needed for the dashboard here later
    context = {}
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
            return redirect(reverse('login')) # Redirect to login page after successful registration
        else:
            # Form is invalid, add error messages (handled in template)
            messages.error(request, 'Please correct the errors below.')
    else:
        # GET request, display blank form
        form = UserCreationForm()

    # Render the registration template we created earlier
    return render(request, 'registration/register.html', {'form': form})
