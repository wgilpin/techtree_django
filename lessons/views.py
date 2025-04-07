"""Views for the lessons app."""

# pylint: disable=no-member

import json  # Move json import up
import logging
import re
import uuid
from typing import TYPE_CHECKING, Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe  # For async view
from django.views.decorators.http import require_GET, require_POST  # Import require_GET

from core.constants import get_lower_difficulty
from core.models import (
    ConversationHistory,
    Lesson,
    LessonContent,
    Module,
    Syllabus,
    UserProgress,
)
from syllabus.services import SyllabusService  # Import syllabus service

from . import services  # Import the services module
from .templatetags.markdown_extras import markdownify  # Import markdownify

if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)  # Ensure logger is initialized

syllabus_service = SyllabusService()  # Instantiate service


def clean_exposition_string(text: Optional[str]) -> Optional[str]:
    """Decodes unicode escapes and fixes specific known issues in exposition text."""
    if not text:
        return text

    cleaned_text = text
    try:
        # Decode standard Python unicode escapes (\uXXXX, \xXX)
        # Using 'latin-1' to handle potential byte values mixed with unicode escapes
        # and 'ignore' errors to skip problematic sequences.
        # Use 'raw_unicode_escape' which only handles \uXXXX and \UXXXXXXXX, leaving other backslashes alone.
        cleaned_text = cleaned_text.encode("latin-1", errors="ignore").decode(
            "raw_unicode_escape", errors="ignore"
        )
        # Alternative: cleaned_text = bytes(text, "utf-8").decode("unicode_escape")
    except Exception as e:
        logger.warning("Failed to decode unicode escapes in exposition: %s", e)
        # Continue with the original text if decoding fails, specific fixes might still apply

    # --- Specific known fixes (apply AFTER unicode decoding) ---

    # Fix: \u0007pprox -> \approx (where \u0007 might be a bell char or similar artifact)
    # This handles the case where the unicode decoding might not have fixed it.
    cleaned_text = cleaned_text.replace(
        "\u0007pprox", r"\approx"
    )  # Use raw string for \approx

    # Fix: \x08egin{ -> \begin{ (Backspace artifact)
    cleaned_text = cleaned_text.replace("\x08egin{", r"\begin{")  # Use raw string

    # Fix: â€“ -> – (common Mojibake for en-dash)
    cleaned_text = cleaned_text.replace("â€“", "–")
    # Fix: Ã¶ -> ö (common Mojibake for o-umlaut, e.g., Eötvös)
    cleaned_text = cleaned_text.replace("Ã¶", "ö")
    # Fix: \\, -> \, (Extra backslash before LaTeX space)
    cleaned_text = cleaned_text.replace("\\\\,", r"\,")
    # Fix: \\mu -> \mu, \\alpha -> \alpha, etc. (Extra backslash before greek letters)
    # Using regex to be more general for common LaTeX commands
    cleaned_text = re.sub(r"\\\\([a-zA-Z]+)", r"\\\1", cleaned_text)

    # Add other specific replacements if needed based on observed errors

    return cleaned_text


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

        # --- Calculate Absolute Lesson Number ---
        absolute_lesson_number: Optional[int] = None
        try:
            all_lesson_pks = list(
                Lesson.objects.filter(module__syllabus=syllabus)
                .order_by("module__module_index", "lesson_index")
                .values_list("pk", flat=True)
            )
            absolute_lesson_number = all_lesson_pks.index(lesson.pk) + 1
        except (ValueError, Exception) as e:
            logger.error(
                "Failed to calculate absolute_lesson_number for lesson %s in syllabus %s: %s",
                lesson.pk,
                syllabus.pk,
                e,
                exc_info=True,
            )
            # Proceed without absolute number if calculation fails

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

        # --- Add Welcome Message if History is Empty ---
        if not conversation_history:
            welcome_message_content = (
                "Is there anything I can explain more? Ask me any questions, or we can do "
                "exercises to help to think about it all. Once you're happy with this "
                "lesson, ask me to start a quiz"
            )
            # Create an unsaved ConversationHistory instance for the welcome message.
            # This satisfies type checking and provides the necessary attributes for the template.
            welcome_message_instance = ConversationHistory(
                role="assistant",
                content=welcome_message_content,
                # No need to set progress or timestamp as it's not saved and template doesn't use them here.
            )
            conversation_history.insert(0, welcome_message_instance)
            logger.info(
                "Prepended initial welcome message to empty conversation history for lesson %s.",
                lesson.pk,
            )
        # --- End Welcome Message ---

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
                        exposition_value  # Restore the condition check
                    ):  # Check if exposition_value is not None and not empty string
                        # Clean the extracted exposition string
                        exposition_content_value = clean_exposition_string(
                            exposition_value
                        )
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
            "absolute_lesson_number": absolute_lesson_number,  # Add absolute index calculated above
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
            exc_info=e,
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
                # Clean the markdown string before passing to markdownify
                cleaned_exposition_markdown = clean_exposition_string(
                    exposition_markdown
                )
                # Use the markdownify function from templatetags for consistent processing
                html_content = markdownify(cleaned_exposition_markdown)
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
            exc_info=e,
        )
        return JsonResponse(
            {"status": "error", "error": "An unexpected error occurred."}, status=500
        )


# @login_required # Cannot use with async view, check manually
@require_GET  # Use GET as it's triggered by a link click
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
        # Use the new synchronous service method
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
            # Fallback for non-AJAX requests (though unlikely with the JS approach)
            return redirect(new_syllabus_url)
            
    except Exception as e:
        logger.error(f"Error during difficulty change process: {e}", exc_info=True)
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': str(e) # Provide a generic error or specific if safe
            }, status=500)
        messages.error(request, "An unexpected error occurred while changing the difficulty.")
        # Redirect to dashboard or a relevant error page for non-AJAX
        return redirect(reverse("dashboard"))
