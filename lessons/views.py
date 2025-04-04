"""Views for the lessons app."""

# pylint: disable=no-member

import json  # Move json import up
import logging
from typing import TYPE_CHECKING, Optional

import markdown  # For async view
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe  # For async view
from django.views.decorators.http import require_POST  # Import require_POST

from core.models import (
    ConversationHistory,
    Lesson,
    LessonContent,
    Module,
    Syllabus,
    UserProgress,
)

from . import services  # Import the services module
from .templatetags.markdown_extras import markdownify  # Import markdownify

if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)  # Ensure logger is initialized


@login_required
def lesson_detail(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Display a specific lesson within a syllabus module (GET request).

    Handles fetching lesson content, user progress, and history for display.
    POST interactions are handled by the 'handle_lesson_interaction' view.
    """

    user: "User" = request.user  # type: ignore[assignment]

    if request.method == "POST":
        # Redirect POST requests intended for the detail page (e.g., non-JS form fallback)
        # to the dedicated interaction handler or simply disallow standard POST here.
        # For simplicity, let's redirect to the GET version.
        # A more robust solution might show an error or handle basic form submissions
        # if non-AJAX interaction is desired.
        logger.warning(
            "Received standard POST on lesson_detail view for lesson %s:%s:%s. Redirecting.",
            syllabus_id,
            module_index,
            lesson_index,
        )
        return redirect(request.path_info)

    # --- GET Request Logic ---
    try:
        syllabus = get_object_or_404(Syllabus, pk=syllabus_id)  # Add user check later
        module = get_object_or_404(Module, syllabus=syllabus, module_index=module_index)
        lesson = get_object_or_404(Lesson, module=module, lesson_index=lesson_index)

        # --- Fetch existing data, but don't trigger generation here ---
        progress, created = UserProgress.objects.get_or_create(
            user=user,
            syllabus=syllabus,
            lesson=lesson,
            defaults={
                "module_index": module.module_index,
                "lesson_index": lesson.lesson_index,
                "status": "not_started",
            },
        )
        if created or progress.status == "not_started":
            progress.status = "in_progress"
            progress.save(update_fields=["status", "updated_at"])
            logger.info(
                "Set/updated UserProgress %s status to 'in_progress'.", progress.pk
            )

        # Try fetching existing content only
        lesson_content = LessonContent.objects.filter(lesson=lesson).first()
        conversation_history = list(
            ConversationHistory.objects.filter(progress=progress).order_by("timestamp")
        )

        # Extract exposition string only if content already exists and is valid
        exposition_content_value: Optional[str] = None  # Start as None
        if lesson_content:  # Check if a record exists
            if isinstance(lesson_content.content, dict):
                # Check if it's an error structure we added in services.py
                if "error" in lesson_content.content:
                    logger.warning(
                        "Lesson content (pk=%s) contains an error marker: %s",
                        lesson_content.pk,
                        lesson_content.content.get("error"),
                    )
                    # Keep exposition_content_value as None to trigger async loading/error display
                else:
                    # Original logic: get exposition if it exists
                    exposition_value = lesson_content.content.get(
                        "exposition"
                    )  # Get value or None
                    if (
                        exposition_value
                    ):  # Check if exposition_value is not None and not empty string
                        exposition_content_value = exposition_value
                    else:
                        # Handle case where exposition key exists but value is None or empty string
                        logger.warning(
                            "Lesson content (pk=%s) has missing or empty 'exposition' value.",
                            lesson_content.pk,
                        )
                        # exposition_content_value remains None to trigger async loading
            else:
                # Log if existing content is not the expected dictionary format
                logger.warning(
                    "Existing lesson content (pk=%s) is not a dict. Type: %s, Value: %s",
                    lesson_content.pk,
                    type(lesson_content.content),
                    str(lesson_content.content)[:200] + "...",
                )
                # exposition_content_value remains None
        else:
            # Log that content needs to be generated asynchronously
            logger.info(
                "Lesson content for lesson %s does not exist yet. Will be generated asynchronously.",
                lesson.pk,
            )
            # exposition_content_value remains None


        context = {
            "syllabus": syllabus,
            "module": module,
            "lesson": lesson,
            "progress": progress,
            "title": f"Lesson: {lesson.title}",
            # 'lesson_content': lesson_content, # No longer needed directly in template context
            "exposition_content": exposition_content_value,  # Pass the extracted string value or None
            "conversation_history": conversation_history,
            "lesson_state_json": (
                json.dumps(progress.lesson_state_json)
                if progress and progress.lesson_state_json
                else "{}"
            ),
        }
        return render(request, "lessons/lesson_detail.html", context)

    except (Syllabus.DoesNotExist, Module.DoesNotExist, Lesson.DoesNotExist) as exc:
        logger.warning(
            "Lesson not found for syllabus_id=%s, module_index=%s, lesson_index=%s",
            syllabus_id,
            module_index,
            lesson_index,  # Keep args for context
            exc_info=True,
        )
        raise Http404("Lesson not found.") from exc
    except Exception as e:
        logger.error(
            "Error loading lesson detail for user %s, syllabus %s, module %s, lesson %s: %s",
            user.username,
            syllabus_id,
            module_index,
            lesson_index,
            e,
            exc_info=True,
        )
        return HttpResponse("An unexpected error occurred.", status=500)


@login_required
@require_POST  # This view only handles POST requests
def handle_lesson_interaction(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """
    Handles AJAX POST requests for lesson interactions (chat, answers, assessments).
    """
    user: "User" = request.user  # type: ignore[assignment]
    user_message_content = ""
    submission_type = "chat"  # Default
    error_message = None
    status_code = 200
    response_data = {}

    try:
        # Fetch lesson context (needed for service calls)
        syllabus = get_object_or_404(Syllabus, pk=syllabus_id)  # Add user check later
        module = get_object_or_404(Module, syllabus=syllabus, module_index=module_index)
        lesson = get_object_or_404(Lesson, module=module, lesson_index=lesson_index)

        # Get current progress and state
        progress, _, _ = services.get_lesson_state_and_history(
            user=user, syllabus=syllabus, module=module, lesson=lesson
        )

        if progress is None:
            logger.error(
                "Could not retrieve UserProgress for interaction. User %s, Lesson %s",
                user.username,
                lesson.pk,
            )
            return JsonResponse(
                {"status": "error", "message": "Could not load user progress."},
                status=500,
            )

        # Parse JSON request body
        try:
            data = json.loads(request.body)
            user_message_content = data.get("message", "").strip()
            submission_type = data.get("submission_type", "chat")  # Default to 'chat'
        except json.JSONDecodeError:
            logger.warning(
                "Received invalid JSON in AJAX request from user %s for lesson %s.",
                user.username,
                lesson.pk,
            )
            error_message = "Invalid JSON format."
            status_code = 400

        if not error_message and not user_message_content:
            logger.warning(
                "Received empty message from user %s for lesson %s.",
                user.username,
                lesson.pk,
            )
            error_message = "Message cannot be empty."
            status_code = 400

        # If no parsing errors and message is not empty, call the service
        if not error_message:
            logger.info(
                "Handling interaction (Type: %s) from user %s for lesson %s.",
                submission_type,
                user.username,
                lesson.pk,
            )
            service_response = services.handle_chat_message(
                user=user,
                progress=progress,
                user_message_content=user_message_content,
                submission_type=submission_type,
            )

            if service_response and isinstance(service_response, dict):
                logger.info(
                    "Interaction handled successfully for user %s, lesson %s.",
                    user.username,
                    lesson.pk,
                )
                # Refresh progress to get the absolute latest state after service call
                progress.refresh_from_db()
                response_data = {
                    "status": "success",
                    # Apply markdownify to the assistant message before sending
                    "assistant_message": (
                        markdownify(service_response.get("assistant_message", ""))
                        if service_response.get("assistant_message")
                        else ""
                    ),
                    # Send back the updated state from the refreshed progress object
                    "updated_state": progress.lesson_state_json,
                }
                status_code = 200
            else:
                logger.error(
                    "Service handle_chat_message did not return expected data for user %s, lesson %s. Response: %s",
                    user.username,
                    lesson.pk,
                    service_response,
                )
                error_message = "Failed to process interaction."
                status_code = 500

    # Specific exceptions first
    except (
        Syllabus.DoesNotExist,
        Module.DoesNotExist,
        Lesson.DoesNotExist,
        Http404,
    ) as exc:  # Catch Http404 here
        logger.warning(
            "Lesson context not found during interaction for syllabus %s, module %s, lesson %s: %s",
            syllabus_id,
            module_index,
            lesson_index,
            str(exc),
        )
        error_message = "Lesson context not found."
        status_code = 404
    except json.JSONDecodeError:  # Handle JSON errors specifically
        logger.warning(
            "Received invalid JSON in AJAX request from user %s for lesson %s.",
            user.username,
            f"{syllabus_id}:{module_index}:{lesson_index}",
        )
        error_message = "Invalid JSON format."
        status_code = 400
    # Generic exception last
    except Exception as e:
        logger.exception(
            "Unexpected error handling interaction for user %s, lesson %s.",
            user.username,
            f"{syllabus_id}:{module_index}:{lesson_index}",
            exc_info=e
        )
        error_message = "An unexpected error occurred."
        status_code = 500

    # --- Return JSON Response ---
    if error_message:
        return JsonResponse(
            {"status": "error", "message": error_message}, status=status_code
        )
    else:
        return JsonResponse(response_data, status=status_code)


@login_required
@require_POST  # This view only handles POST requests for triggering generation
def generate_lesson_content_async(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """
    Handles asynchronous requests to generate lesson content.

    Called via AJAX if the initial page load finds no existing content.
    Returns the generated content as HTML.
    """
    user: "User" = request.user  # type: ignore[assignment]
    logger.info(
        "Async content generation requested for lesson %s:%s:%s by user %s",
        syllabus_id,
        module_index,
        lesson_index,
        user.username,
    )

    try:
        # Fetch lesson context (reuse logic from other views)
        # No need for syllabus/module objects here, just the lesson
        lesson = get_object_or_404(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )

        # Call the service to get or create content
        lesson_content = services.get_or_create_lesson_content(lesson)

        if lesson_content and isinstance(lesson_content.content, dict):
            raw_exposition_value = lesson_content.content.get("exposition", "")

            # Check for double encoding: If the value itself is a JSON string containing 'exposition'
            exposition_markdown = raw_exposition_value
            if isinstance(
                raw_exposition_value, str
            ) and raw_exposition_value.strip().startswith('{"exposition":'):
                try:
                    logger.warning(
                        "Detected potential double encoding in async view for lesson %s. "
                        "Attempting to parse inner JSON.",
                        lesson.pk,
                    )
                    inner_data = json.loads(raw_exposition_value)
                    if isinstance(inner_data, dict):
                        exposition_markdown = inner_data.get(
                            "exposition", ""
                        )  # Get the actual markdown
                except json.JSONDecodeError:
                    logger.error(
                        "Failed to parse potentially double-encoded JSON in async view for lesson %s.",
                        lesson.pk,
                        exc_info=True,
                    )
                    # Fallback to using the raw value, though it might be wrong
                    exposition_markdown = raw_exposition_value

            if exposition_markdown:
                # Convert markdown to HTML using the same logic as the template tag
                html_content = markdown.markdown(
                    exposition_markdown,
                    extensions=[
                        "markdown.extensions.fenced_code",
                        "markdown.extensions.tables",
                        "markdown.extensions.nl2br",
                        # 'markdown.extensions.extra', # Keep disabled for now
                    ],
                )
                logger.info(
                    "Async content generation successful for lesson %s.", lesson.pk
                )
                return JsonResponse(
                    {
                        "status": "success",
                        "html_content": mark_safe(
                            html_content
                        ),  # Ensure it's marked safe
                    }
                )
            else:
                logger.error(
                    "Generated content for lesson %s is missing 'exposition' key or value.",
                    lesson.pk,
                )
                error_message = "Generated content is invalid."
        else:
            logger.error(
                "Failed to get or generate content for lesson %s via async request.",
                lesson.pk,
            )
            error_message = "Content generation failed."

        return JsonResponse({"status": "error", "error": error_message}, status=500)

    except Lesson.DoesNotExist:
        logger.warning(
            "Lesson context not found during async generation for %s:%s:%s",
            syllabus_id,
            module_index,
            lesson_index,
        )
        return JsonResponse(
            {"status": "error", "error": "Lesson not found."}, status=404
        )
    except Exception as e:
        logger.exception(
            "Unexpected error during async content generation for lesson %s:%s:%s.",
            syllabus_id,
            module_index,
            lesson_index,
            exc_info=e
        )
        return JsonResponse(
            {"status": "error", "error": "An unexpected error occurred."}, status=500
        )
