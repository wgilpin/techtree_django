"""
API views for the taskqueue app, including task status checking and monitoring dashboard.
"""

from datetime import timedelta
from collections import Counter

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.shortcuts import render
from django.utils import timezone
from background_task.models import Task as BGTask

from .models import AITask
from .tasks import get_queue_metrics


@login_required
@require_GET
def check_task_status(request, task_id):
    """
    API endpoint to check the status of a background AI task.

    Returns JSON with task status, timestamps, and result or error if applicable.
    Only the task owner or staff can access the task status.
    """
    try:
        task = AITask.objects.get(task_id=task_id)  # pylint: disable=no-member

        # Permission check
        if task.user and task.user != request.user and not request.user.is_staff:
            return JsonResponse(
                {"status": "error", "message": "Permission denied"}, status=403
            )

        response = {
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

        if task.status == AITask.TaskStatus.COMPLETED:
            response["result"] = task.result_data
        elif task.status == AITask.TaskStatus.FAILED:
            response["error"] = task.error_message

        return JsonResponse(response)

    except ObjectDoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Task not found"}, status=404
        )


@login_required
@user_passes_test(lambda u: u.is_staff)
def dashboard(request):
    """
    Admin dashboard for monitoring the task queue.
    
    Shows metrics, recent tasks, and task distribution by type.
    Only accessible to staff users.
    """
    # Get queue metrics
    metrics = get_queue_metrics()
    
    # Get recent tasks (last 50)
    recent_tasks = AITask.objects.all().order_by('-updated_at')[:50]
    
    # Count tasks by type
    task_types = AITask.objects.values_list('task_type', flat=True)
    task_type_counts = {}
    for task_type, count in Counter(task_types).items():
        # Get display name for the task type
        display_name = dict(AITask.TaskType.choices).get(task_type, task_type)
        task_type_counts[display_name] = count
    
    # Count active workers (background tasks that have been claimed)
    worker_count = BGTask.objects.filter(
        locked_by__isnull=False,
        locked_at__gte=timezone.now() - timedelta(minutes=5)
    ).values('locked_by').distinct().count()
    
    context = {
        'metrics': metrics,
        'recent_tasks': recent_tasks,
        'task_type_counts': task_type_counts,
        'worker_count': worker_count,
    }
    
    return render(request, 'taskqueue/dashboard.html', context)
