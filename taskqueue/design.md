# taskqueue

**Name:** Background Task Queue Management

**Description:**  
This folder manages the background task queue system for handling asynchronous AI operations. It defines the task model, task execution logic, and views for monitoring task status and the overall queue health. The code here enables long-running AI processes (like syllabus generation, content creation, and interactions) to run without blocking user requests.

---

## Files

### admin.py
Minimal admin configuration for the taskqueue app; no models are registered here.
- No public methods.

### apps.py
Django app configuration for the taskqueue app.
- No public methods.

### models.py
Defines the `AITask` model for tracking background AI tasks, including their type, status, input/output data, and related objects.
- No public methods except dunder methods.

### tasks.py
Defines the background task functions using `django-background-tasks`, including the main task processor and metrics logging.
- `log_task_metrics(func)`: Decorator to log task execution start, completion, and duration.
- `dummy_task()`: A simple background task for testing the worker process.
- `process_ai_task(task_id)`: Main entry point for processing AI tasks, routing them to appropriate processors.
- `get_queue_metrics()`: Retrieves metrics about the current task queue (counts, average time).
- `log_queue_metrics()`: Periodically logs queue metrics for monitoring.

### urls.py
URL configuration for the taskqueue app, mapping URL patterns to views for checking task status and viewing the monitoring dashboard.
- No public methods.

### views.py
Implements views for the taskqueue app, including an API endpoint for checking task status and an admin dashboard for monitoring.
- `check_task_status(request, task_id)`: API endpoint to check the status of a specific background AI task.
- `dashboard(request)`: Admin dashboard view for monitoring the task queue metrics and recent tasks.