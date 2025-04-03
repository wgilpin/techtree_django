"""Views for the syllabus app."""

import logging
from typing import Any, Dict

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse

from core.exceptions import NotFoundError, ApplicationError
from .services import SyllabusService

logger = logging.getLogger(__name__)

# Instantiate the service - consider dependency injection for larger apps
syllabus_service = SyllabusService()


@login_required
def syllabus_landing(request: HttpRequest) -> HttpResponse:
    """
    Placeholder view for the main syllabus page.
    Likely needs a form to input topic/level or list existing syllabi.
    """
    # TODO: Implement logic to list user's syllabi or show creation form
    context = {"message": "Syllabus Landing Page - To be implemented"}
    return render(request, "syllabus/landing.html", context)


@login_required
def generate_syllabus_view(request: HttpRequest) -> HttpResponse:
    """Handles the generation or retrieval of a syllabus."""
    if request.method == "POST":
        topic = request.POST.get("topic", "").strip()
        level = request.POST.get("level", "beginner").strip()
        user = request.user

        if not topic:
            # Handle error: topic is required
            # Add messages framework or pass error to context
            logger.warning("Syllabus generation request missing topic.")
            # Redirect back or render form with error
            return redirect(reverse("syllabus:landing")) # Or render form with error

        try:
            logger.info(f"Generating syllabus for user {user.pk}: Topic='{topic}', Level='{level}'")
            syllabus_data = syllabus_service.get_or_generate_syllabus(
                topic=topic, level=level, user=user
            )
            syllabus_id = syllabus_data.get("syllabus_id")
            if syllabus_id:
                # Redirect to the detail view of the newly created/found syllabus
                return redirect(reverse("syllabus:detail", args=[syllabus_id]))
            else:
                # Handle error: syllabus ID missing after generation
                logger.error("Syllabus ID missing after generation/retrieval.")
                # Add error message
                return redirect(reverse("syllabus:landing")) # Or render form with error

        except ApplicationError as e:
            logger.error(f"Error generating syllabus: {e}", exc_info=True)
            # Handle error display to user
            # Add error message
            return redirect(reverse("syllabus:landing")) # Or render form with error
        except Exception as e:
            logger.exception(f"Unexpected error during syllabus generation: {e}")
            # Handle error display to user
            # Add error message
            return redirect(reverse("syllabus:landing")) # Or render form with error

    # If GET or other methods, redirect to landing (or show form)
    return redirect(reverse("syllabus:landing"))


@login_required
def syllabus_detail(request: HttpRequest, syllabus_id: str) -> HttpResponse:
    """Displays the details of a specific syllabus."""
    try:
        syllabus_data = syllabus_service.get_syllabus_by_id(syllabus_id)
        # Ensure the user has access to this syllabus (optional, depends on requirements)
        # if syllabus_data.get("user_id") != str(request.user.pk) and syllabus_data.get("user_id") is not None:
        #     raise Http404("Syllabus not found or access denied.")

        context = {"syllabus": syllabus_data}
        return render(request, "syllabus/detail.html", context)
    except NotFoundError:
        raise Http404("Syllabus not found.")
    except ApplicationError as e:
        logger.error(f"Error displaying syllabus {syllabus_id}: {e}", exc_info=True)
        # Handle error display - maybe redirect with message
        return redirect(reverse("syllabus:landing")) # Or render an error page


@login_required
def module_detail(request: HttpRequest, syllabus_id: str, module_index: int) -> HttpResponse:
    """Displays the details of a specific module."""
    try:
        module_data = syllabus_service.get_module_details(syllabus_id, module_index)
        # Add access control if necessary

        context = {"module": module_data, "syllabus_id": syllabus_id}
        return render(request, "syllabus/module_detail.html", context)
    except NotFoundError:
        raise Http404("Module not found.")
    except ApplicationError as e:
        logger.error(f"Error displaying module {module_index} for syllabus {syllabus_id}: {e}", exc_info=True)
        return redirect(reverse("syllabus:detail", args=[syllabus_id])) # Redirect to syllabus


@login_required
def lesson_detail(request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int) -> HttpResponse:
    """Displays the details of a specific lesson."""
    try:
        lesson_data = syllabus_service.get_lesson_details(syllabus_id, module_index, lesson_index)
        # Add access control if necessary

        context = {
            "lesson": lesson_data,
            "syllabus_id": syllabus_id,
            "module_index": module_index,
        }
        return render(request, "syllabus/lesson_detail.html", context)
    except NotFoundError:
        raise Http404("Lesson not found.")
    except ApplicationError as e:
        logger.error(f"Error displaying lesson {lesson_index} (module {module_index}, syllabus {syllabus_id}): {e}", exc_info=True)
        return redirect(reverse("syllabus:module_detail", args=[syllabus_id, module_index])) # Redirect to module
