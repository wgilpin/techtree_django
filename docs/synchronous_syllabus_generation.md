# Synchronous Syllabus Generation Implementation Plan

## Overview

This document outlines the implementation plan for changing the syllabus difficulty change feature from using background tasks to a synchronous JavaScript-based approach. This will simplify the architecture by eliminating the need for background task workers while still providing a good user experience.

## Current Implementation Issues

The current implementation uses `asyncio.create_task()` to start the syllabus generation in the background, but this task gets cancelled when the HTTP request completes, resulting in a `CancelledError` and the syllabus never being generated.

## Proposed Solution

Instead of redirecting the user to a loading page and using background tasks, we'll:

1. Keep the user on the current page
2. Show a loading overlay with JavaScript
3. Make an AJAX request to generate the syllabus synchronously
4. Redirect the user to the new syllabus when generation is complete

This approach eliminates the need for background tasks and polling, simplifying the architecture while maintaining a good user experience.

## Implementation Details

### 1. Modify `change_difficulty_view` in `lessons/views.py`

The current view redirects to a loading page and uses background tasks. We'll modify it to:
- Check if the request is an AJAX request
- Generate the syllabus synchronously (no background tasks)
- Return a JSON response for AJAX requests or redirect for regular requests

```python
@require_GET
async def change_difficulty_view(request: HttpRequest, syllabus_id: uuid.UUID) -> HttpResponse:
    """Handles the request to switch to a lower difficulty syllabus."""
    user = await request.auser()
    if not user.is_authenticated:
        # Handle unauthenticated user
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
        messages.error(request, "You must be logged in to change syllabus difficulty.")
        return redirect(settings.LOGIN_URL + "?next=" + request.path)

    # Check if this is an AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    try:
        # Fetch the current syllabus
        current_syllabus = await sync_to_async(Syllabus.objects.get)(pk=syllabus_id, user=user)
        current_level = current_syllabus.level
        topic = current_syllabus.topic
        
        # Determine the next lower level
        new_level = get_lower_difficulty(current_level)
        if new_level is None:
            if is_ajax:
                return JsonResponse({
                    'success': False, 
                    'error': 'Already at lowest difficulty level'
                })
            messages.info(request, "You are already at the lowest difficulty level.")
            return redirect(reverse("syllabus:detail", args=[syllabus_id]))
        
        # Log the change
        logger.info(f"Changing difficulty for syllabus {syllabus_id} (User: {user.pk}) from '{current_level}' to '{new_level}' for topic '{topic}'")
        
        # Generate the syllabus synchronously (no background tasks)
        new_syllabus_id = await syllabus_service.get_or_generate_syllabus_sync(
            topic=topic, level=new_level, user=user
        )
        
        # Get the URL for the new syllabus
        new_syllabus_url = reverse('syllabus:detail', args=[new_syllabus_id])
        
        if is_ajax:
            return JsonResponse({
                'success': True,
                'redirect_url': new_syllabus_url
            })
        else:
            return redirect(new_syllabus_url)
            
    except Exception as e:
        logger.error(f"Error during difficulty change process: {e}", exc_info=True)
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
        messages.error(request, "An unexpected error occurred while changing the difficulty.")
        return redirect(reverse("dashboard"))
```

### 2. Add a Synchronous Method to `SyllabusService` in `syllabus/services.py`

```python
async def get_or_generate_syllabus_sync(self, topic, level, user):
    """
    Synchronously gets or generates a syllabus without using background tasks.
    """
    # First, check if a completed syllabus already exists
    try:
        syllabus_obj = await Syllabus.objects.aget(
            topic=topic, level=level, user=user, status=Syllabus.StatusChoices.COMPLETED
        )
        return syllabus_obj.syllabus_id
    except Syllabus.DoesNotExist:
        # No existing syllabus, generate a new one
        
        # Create a new syllabus with GENERATING status
        placeholder_syllabus = await Syllabus.objects.acreate(
            topic=topic,
            level=level,
            user=user,
            user_entered_topic=topic,
            status=Syllabus.StatusChoices.GENERATING,
        )
        
        # Generate the syllabus content directly (no background task)
        syllabus_ai = SyllabusAI()
        syllabus_ai.initialize(
            topic=topic, knowledge_level=level, user_id=str(user.pk) if user else None
        )
        
        # Run the AI graph to generate the syllabus
        final_state = await syllabus_ai.get_or_create_syllabus()
        
        # The save_syllabus node should have updated the status to COMPLETED
        
        return placeholder_syllabus.syllabus_id
```

### 3. Update the Change Difficulty Link in `lessons/templates/lessons/lesson_detail.html`

```html
{% if syllabus.level != 'beginner' %}
    <div class="mb-3 mt-2">
        <a href="#"
           id="change-difficulty-btn"
           class="btn btn-sm btn-outline-secondary change-difficulty-link"
           data-url="{% url 'lessons:change_difficulty' syllabus.pk %}">
            <i class="fas fa-arrow-down"></i> Switch to Lower Difficulty
        </a>
    </div>
    
    <!-- Loading Overlay (hidden by default) -->
    <div id="loading-overlay" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; flex-direction: column;">
        <div class="spinner-border text-light" style="width: 3rem; height: 3rem;" role="status"></div>
        <p style="color: white; margin-top: 20px;">Generating syllabus with lower difficulty level...</p>
    </div>
{% endif %}
```

### 4. Add JavaScript to Handle the AJAX Request

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const changeDifficultyBtn = document.getElementById('change-difficulty-btn');
    const loadingOverlay = document.getElementById('loading-overlay');
    
    if (changeDifficultyBtn) {
        changeDifficultyBtn.addEventListener('click', function(e) {
            e.preventDefault();
            
            if (confirm('Are you sure you want to switch to a lower difficulty level? This will generate a new syllabus.')) {
                // Show loading overlay
                loadingOverlay.style.display = 'flex';
                
                // Get the URL from the data attribute
                const url = this.dataset.url;
                
                // Make AJAX request
                fetch(url, {
                    method: 'GET',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Redirect to the new syllabus
                        window.location.href = data.redirect_url;
                    } else {
                        // Hide loading overlay
                        loadingOverlay.style.display = 'none';
                        // Show error
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    // Hide loading overlay
                    loadingOverlay.style.display = 'none';
                    console.error('Error:', error);
                    alert('An error occurred. Please try again.');
                });
            }
        });
    }
});
```

## Implementation Steps

1. Add the `get_or_generate_syllabus_sync` method to `SyllabusService` in `syllabus/services.py`
2. Modify the `change_difficulty_view` in `lessons/views.py` to handle AJAX requests and generate syllabi synchronously
3. Update the change difficulty link in `lessons/templates/lessons/lesson_detail.html` to include the loading overlay and JavaScript

## Advantages Over Background Tasks

1. **Simplicity**: No need for background task workers or process managers
2. **Reliability**: The syllabus generation is guaranteed to complete (unless the request times out)
3. **User Experience**: The user still sees a loading indicator while waiting
4. **Maintainability**: Fewer moving parts means less complexity and fewer potential points of failure

## Potential Drawbacks

1. **Request Timeout**: If syllabus generation takes longer than the web server's timeout setting, the request might fail
2. **Server Resources**: Long-running requests tie up server resources, potentially affecting scalability
3. **Client Connection**: If the user's internet connection is interrupted during generation, the process will fail

## Conclusion

This approach provides a simpler solution to the `CancelledError` issue while maintaining a good user experience. It eliminates the need for background tasks and separate worker processes, making the system easier to deploy and maintain.