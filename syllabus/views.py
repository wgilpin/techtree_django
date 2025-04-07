"""Views for the syllabus app."""

import logging

# Removed sync_to_async import
# Removed sync_to_async import

from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render, redirect
from django.urls import reverse

from core.exceptions import NotFoundError, ApplicationError
from .services import SyllabusService

logger = logging.getLogger(__name__)

# Instantiate the service - consider dependency injection for larger apps
syllabus_service = SyllabusService()


# Removed @login_required decorator
def syllabus_landing(request: HttpRequest) -> HttpResponse:
    """
    Placeholder view for the main syllabus page.
    Likely needs a form to input topic/level or list existing syllabi.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    context = {"message": "Syllabus Landing Page - To be implemented"}
    return render(request, "syllabus/landing.html", context)


# Removed @login_required decorator
# Keep this view async as it calls an async service
async def generate_syllabus_view(request: HttpRequest) -> HttpResponse:
    """Handles the generation or retrieval of a syllabus."""
    user = await request.auser()  # Use async user fetch
    if not user.is_authenticated:
        # Handle redirect for POST request appropriately, maybe return error or redirect GET
        # For simplicity, redirecting GET part of login flow
        return redirect(
            f"{reverse('login')}?next={reverse('syllabus:landing')}"
        )  # Redirect to landing after login
    if request.method == "POST":
        topic = request.POST.get("topic", "").strip()
        level = request.POST.get("level", "beginner").strip()
        # user is fetched asynchronously above

        if not topic:
            # Handle error: topic is required
            # Add messages framework or pass error to context
            logger.warning("Syllabus generation request missing topic.")
            # Redirect back or render form with error
            return redirect(reverse("syllabus:landing"))  # Or render form with error

        try:
            # Use the user object fetched with await request.auser()
            logger.info(
                f"Generating syllabus for user {user.pk}: Topic='{topic}', Level='{level}'"
            )
            # Call the async service method
            # Call the async service method, which now returns a UUID
            syllabus_uuid = await syllabus_service.get_or_generate_syllabus(
                topic=topic, level=level, user=user
            )
            # Redirect to the onboarding page to show generation progress
            return redirect("onboarding:generating_syllabus", syllabus_id=syllabus_uuid)

        except ApplicationError as e:
            logger.error(f"Error generating syllabus: {e}", exc_info=True)
            # Handle error display to user
            # Add error message
            return redirect(reverse("syllabus:landing"))  # Or render form with error
        except Exception as e:
            logger.exception(f"Unexpected error during syllabus generation: {e}")
            # Handle error display to user
            # Add error message
            return redirect(reverse("syllabus:landing"))  # Or render form with error

    # If GET or other methods, redirect to landing (or show form)
    return redirect(reverse("syllabus:landing"))


# Changed back to sync def
def syllabus_detail(request: HttpRequest, syllabus_id: str) -> HttpResponse:
    """Displays the details of a specific syllabus."""
    # Use sync user check
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    try:
        # Call the sync service method
        syllabus_data = syllabus_service.get_syllabus_by_id_sync(syllabus_id)
        # Ensure the user has access to this syllabus (optional, depends on requirements)
        # if syllabus_data.get("user_id") != str(request.user.pk) and syllabus_data.get("user_id") is not None:
        #     raise Http404("Syllabus not found or access denied.")

        context = {"syllabus": syllabus_data}
        # Use standard render
        return render(request, "syllabus/detail.html", context)
    except NotFoundError as e:
        raise Http404("Syllabus not found.") from e
    except ApplicationError as e:
        logger.error(f"Error displaying syllabus {syllabus_id}: {e}", exc_info=True)
        # Handle error display - maybe redirect with message
        return redirect(reverse("syllabus:landing"))  # Or render an error page


# Changed back to sync def
def module_detail(
    request: HttpRequest, syllabus_id: str, module_index: int
) -> HttpResponse:
    """Displays the details of a specific module."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    try:
        # Call the sync service method
        module_data = syllabus_service.get_module_details_sync(
            syllabus_id, module_index
        )
        # Add access control if necessary

        context = {"module": module_data, "syllabus_id": syllabus_id}
        # Use standard render
        return render(request, "syllabus/module_detail.html", context)
    except NotFoundError as e:
        raise Http404("Module not found.") from e
    except ApplicationError as e:
        logger.error(
            f"Error displaying module {module_index} for syllabus {syllabus_id}: {e}",
            exc_info=True,
        )
        return redirect(
            reverse("syllabus:detail", args=[syllabus_id])
        )  # Redirect to syllabus


# Changed back to sync def
def lesson_detail(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """Displays the details of a specific lesson."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    try:
        # Call the sync service method
        lesson_data = syllabus_service.get_lesson_details_sync(
            syllabus_id, module_index, lesson_index
        )
        # Add access control if necessary

        context = {
            "lesson": lesson_data,
            "syllabus_id": syllabus_id,
            "module_index": module_index,
        }
        # Use standard render
        return render(request, "syllabus/lesson_detail.html", context)
    except NotFoundError as e:
        raise Http404("Lesson not found.") from e
    except ApplicationError as e:
        logger.error(
            f"Error displaying lesson {lesson_index} (module {module_index}, syllabus {syllabus_id}): {e}",
            exc_info=True,
        )
        return redirect(
            reverse("syllabus:module_detail", args=[syllabus_id, module_index])
        )  # Redirect to module
