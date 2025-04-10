"""Views for the syllabus app."""

import logging

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.exceptions import ApplicationError, NotFoundError
from taskqueue.models import AITask
from taskqueue.tasks import process_ai_task  # type: ignore[attr-defined]  # pylint: disable=no-name-in-module

from .services import SyllabusService


logger = logging.getLogger(__name__)

# Instantiate the service - consider dependency injection for larger apps
syllabus_service = SyllabusService()


def syllabus_landing(request: HttpRequest) -> HttpResponse:
    """
    Placeholder view for the main syllabus page.
    Likely needs a form to input topic/level or list existing syllabi.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    context = {"message": "Syllabus Landing Page - To be implemented"}
    return render(request, "syllabus/landing.html", context)


# pylint: disable=no-member
def generate_syllabus_view(request: HttpRequest) -> HttpResponse:
    """
    Handles syllabus generation by creating a background task and redirecting to a waiting page.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={reverse('syllabus:landing')}")

    if request.method == "POST":
        topic = request.POST.get("topic", "").strip()
        level = request.POST.get("level", "beginner").strip()

        if not topic:
            logger.warning("Syllabus generation request missing topic.")
            return redirect(reverse("syllabus:landing"))

        try:

            # Create the task record
            # pylint: disable=no-member
            task = AITask.objects.create(  # type: ignore[attr-defined]
                task_type=AITask.TaskType.SYLLABUS_GENERATION,
                input_data={
                    "topic": topic,
                    "knowledge_level": level,
                    "user_id": request.user.id,
                },
                user=request.user,
            )

            # Schedule the background task
            process_ai_task(str(task.task_id))

            # Redirect to a waiting/progress page (to be implemented)
            return redirect(reverse("syllabus:landing"))  # Placeholder

        except Exception as e:
            logger.exception("Error creating syllabus background task: %s", str(e))
            return redirect(reverse("syllabus:landing"))

    # GET or other methods
    return redirect(reverse("syllabus:landing"))


def syllabus_detail(request: HttpRequest, syllabus_id: str) -> HttpResponse:
    """
    Displays the details of a specific syllabus, based on background task status.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")

    try:
        # Find the latest syllabus generation task for this syllabus
        task = (
            AITask.objects.filter(
                syllabus__syllabus_id=syllabus_id,
                task_type=AITask.TaskType.SYLLABUS_GENERATION,
            )
            .order_by("-created_at")
            .first()
        )

        if not task:
            logger.warning(f"No background task found for syllabus {syllabus_id}")
            return redirect(reverse("syllabus:landing"))

        if task.status in [AITask.TaskStatus.PENDING, AITask.TaskStatus.PROCESSING]:
            # Redirect to or render a waiting page
            return render(
                request,
                "syllabus/wait.html",
                {"task_id": task.task_id, "syllabus_id": syllabus_id},
            )

        if task.status == AITask.TaskStatus.FAILED:
            # Show error page or retry option
            context = {
                "error_message": task.error_message or "Syllabus generation failed.",
                "syllabus_id": syllabus_id,
                "task_id": task.task_id,
            }
            return render(request, "syllabus/error.html", context)

        # If completed, display the result data
        syllabus_data = task.result_data or {}
        context = {"syllabus": syllabus_data, "syllabus_id": syllabus_id}
        return render(request, "syllabus/detail.html", context)

    except Exception as e:
        logger.error(f"Error displaying syllabus {syllabus_id}: {e}", exc_info=True)
        return redirect(reverse("syllabus:landing"))


def module_detail(
    request: HttpRequest, syllabus_id: str, module_index: int
) -> HttpResponse:
    """
    Displays the details of a specific module, based on background task status.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")

    try:
        # Find the latest syllabus generation task for this syllabus
        task = (
            AITask.objects.filter(
                syllabus__syllabus_id=syllabus_id,
                task_type=AITask.TaskType.SYLLABUS_GENERATION,
            )
            .order_by("-created_at")
            .first()
        )

        if not task:
            logger.warning(f"No background task found for syllabus {syllabus_id}")
            return redirect(reverse("syllabus:landing"))

        if task.status in [AITask.TaskStatus.PENDING, AITask.TaskStatus.PROCESSING]:
            return render(
                request,
                "syllabus/wait.html",
                {"task_id": task.task_id, "syllabus_id": syllabus_id},
            )

        if task.status == AITask.TaskStatus.FAILED:
            context = {
                "error_message": task.error_message or "Syllabus generation failed.",
                "syllabus_id": syllabus_id,
                "task_id": task.task_id,
            }
            return render(request, "syllabus/error.html", context)

        # If completed, extract module data from result_data
        syllabus_data = task.result_data or {}
        modules = syllabus_data.get("modules", [])
        module_data = next(
            (m for m in modules if m.get("module_index") == module_index), None
        )

        if not module_data:
            raise Http404("Module not found.")

        context = {
            "module": module_data,
            "syllabus_id": syllabus_id,
            "module_index": module_index,
        }
        return render(request, "syllabus/module_detail.html", context)

    except Exception as e:
        logger.error(
            f"Error displaying module {module_index} for syllabus {syllabus_id}: {e}",
            exc_info=True,
        )
        return redirect(reverse("syllabus:detail", args=[syllabus_id]))


# Changed back to sync def
def lesson_detail(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Displays the details of a specific lesson, based on background task status.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")

    try:
        # Find the latest syllabus generation task for this syllabus
        task = (
            AITask.objects.filter(
                syllabus__syllabus_id=syllabus_id,
                task_type=AITask.TaskType.SYLLABUS_GENERATION,
            )
            .order_by("-created_at")
            .first()
        )

        if not task:
            logger.warning(f"No background task found for syllabus {syllabus_id}")
            return redirect(reverse("syllabus:landing"))

        if task.status in [AITask.TaskStatus.PENDING, AITask.TaskStatus.PROCESSING]:
            return render(
                request,
                "syllabus/wait.html",
                {"task_id": task.task_id, "syllabus_id": syllabus_id},
            )

        if task.status == AITask.TaskStatus.FAILED:
            context = {
                "error_message": task.error_message or "Syllabus generation failed.",
                "syllabus_id": syllabus_id,
                "task_id": task.task_id,
            }
            return render(request, "syllabus/error.html", context)

        # If completed, extract lesson data from result_data
        syllabus_data = task.result_data or {}
        modules = syllabus_data.get("modules", [])
        module_data = next(
            (m for m in modules if m.get("module_index") == module_index), None
        )
        if not module_data:
            raise Http404("Module not found.")

        lessons = module_data.get("lessons", [])
        lesson_data = next(
            (l for l in lessons if l.get("lesson_index") == lesson_index), None
        )
        if not lesson_data:
            raise Http404("Lesson not found.")

        context = {
            "lesson": lesson_data,
            "syllabus_id": syllabus_id,
            "module_index": module_index,
            "lesson_index": lesson_index,
        }
        return render(request, "syllabus/lesson_detail.html", context)

    except Exception as e:
        logger.error(
            f"Error displaying lesson {lesson_index} (module {module_index}, syllabus {syllabus_id}): {e}",
            exc_info=True,
        )
        return redirect(
            reverse("syllabus:module_detail", args=[syllabus_id, module_index])
        )
