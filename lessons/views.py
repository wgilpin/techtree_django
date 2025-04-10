"""Views for the lessons app."""

# pylint: disable=no-member

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Optional, cast

from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
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

from . import services, state_service, content_service, interaction_service # Import the services modules
from .templatetags.markdown_extras import markdownify  # Import markdownify

if TYPE_CHECKING:
    # Restore User type hint for sync view
    from django.contrib.auth.models import User as AuthUserType #pylint: disable=reimported

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

    user: "AuthUserType" = request.user  # type: ignore[assignment] # Use type alias

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
        lesson_content: Optional[LessonContent] = LessonContent.objects.filter(
            lesson=lesson
        ).first()  # Type hint

        # --- Determine Content Status ---
        content_status: str = "NOT_FOUND"  # Default if no record
        if lesson_content:
            content_status = lesson_content.status  # Get status from the model field
            
            # If status is FAILED, trigger regeneration
            if content_status == LessonContent.StatusChoices.FAILED:
                logger.info(
                    f"Found FAILED content for lesson {lesson.pk}. Triggering regeneration."
                )
                # Create a task to regenerate content in the background
                # We'll use the async view's URL to trigger regeneration
                regen_url = reverse('lessons:generate_content_async', args=[
                    syllabus_id, module_index, lesson_index
                ])
                # Add a message to inform the user
                messages.info(request, "Lesson content generation failed previously. Retrying...")
                
            # Handle legacy cases where status might not be set yet
            if not content_status:
                # If content exists but status is empty, assume it's completed (legacy)
                if (
                    lesson_content.content
                    and isinstance(lesson_content.content, dict)
                    and "exposition" in lesson_content.content
                ):
                    
                    content_status = LessonContent.StatusChoices.COMPLETED
                    logger.info(
                        "Lesson content %s has no status, assuming COMPLETED (legacy).",
                        lesson_content.pk,
                    )
                    # Optionally save the status back if you want to fix legacy data here
                    # lesson_content.status = LessonContentStatus.COMPLETED
                    # lesson_content.save(update_fields=['status'])
                else:
                    # If content exists but is invalid/empty and no status, mark as PENDING.
                    content_status = LessonContent.StatusChoices.PENDING
                    logger.warning(
                        "Lesson content %s has no status and invalid content, setting to PENDING.",
                        lesson_content.pk,
                    )
                    # Optionally save status back
                    # lesson_content.status = LessonContentStatus.PENDING
                    # lesson_content.save(update_fields=['status'])
        else:
            # If no LessonContent record exists, it's PENDING generation
            content_status = LessonContent.StatusChoices.PENDING
            logger.info(
                "No LessonContent found for lesson %s, status is PENDING.", lesson.pk
            )

        # --- Extract Exposition Content (if available and valid) ---
        exposition_content_value: Optional[str] = None
        # Prioritize showing content if it exists and looks valid, unless explicitly failed/generating
        if lesson_content and content_status not in [
            LessonContent.StatusChoices.FAILED,
            LessonContent.StatusChoices.GENERATING,
        ]:
            if isinstance(lesson_content.content, dict):
                exposition_value = lesson_content.content.get("exposition")
                if exposition_value:
                    exposition_content_value = clean_exposition_string(exposition_value)
                    # If we found valid exposition, ensure status reflects completion if it was PENDING/None
                    if (
                        content_status == LessonContent.StatusChoices.PENDING
                        or not content_status
                    ):
                        logger.info(
                            "Found valid exposition for lesson content %s with status %s, "
                            "treating as COMPLETED for display.",
                            lesson_content.pk,
                            content_status,
                        )
                        content_status = (
                            LessonContent.StatusChoices.COMPLETED
                        )  # Update status for context
                elif content_status == LessonContent.StatusChoices.COMPLETED:
                    # If status was COMPLETED but exposition is missing, mark as FAILED
                    logger.warning(
                        "Lesson content (pk=%s) status is COMPLETED but 'exposition' is missing or empty. "
                        "Marking as FAILED.",
                        lesson_content.pk,
                    )
                    content_status = LessonContent.StatusChoices.FAILED
                    # Optionally save status back
                    # lesson_content.status = LessonContent.StatusChoices.FAILED
                    # lesson_content.save(update_fields=['status'])
            elif content_status == LessonContent.StatusChoices.COMPLETED:
                # If status was COMPLETED but content isn't a dict, mark as FAILED
                logger.warning(
                    "Lesson content (pk=%s) status is COMPLETED but content is not a dict (Type: %s)."
                    "Marking as FAILED.",
                    lesson_content.pk,
                    type(lesson_content.content),
                )
                content_status = LessonContent.StatusChoices.FAILED
                # Optionally save status back
                # lesson_content.status = LessonContent.StatusChoices.FAILED
                # lesson_content.save(update_fields=['status'])
        # --- Conversation History ---
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
            welcome_message_instance = ConversationHistory(
                role="assistant",
                content=welcome_message_content,
            )
            conversation_history.insert(0, welcome_message_instance)
            logger.info(
                "Prepended initial welcome message to empty conversation history for lesson %s.",
                lesson.pk,
            )
        # --- End Welcome Message ---

        # If content status is FAILED, automatically trigger regeneration
        trigger_regeneration = False
        regeneration_url = None
        if content_status == LessonContent.StatusChoices.FAILED:
            trigger_regeneration = True
            regeneration_url = reverse('lessons:generate_content_async', args=[
                syllabus_id, module_index, lesson_index
            ])
            messages.info(request, "Lesson content generation failed previously. Automatically retrying...")
        
        context = {
            "syllabus": syllabus,
            "module": module,
            "lesson": lesson,
            "progress": progress,
            "title": f"Lesson: {lesson.title}",
            # 'lesson_content': lesson_content, # No longer needed directly
            "exposition_content": exposition_content_value,  # Now only set if COMPLETED
            "content_status": content_status,  # Pass the determined status
            "absolute_lesson_number": absolute_lesson_number,
            "conversation_history": conversation_history,
            "lesson_state_json": (
                json.dumps(progress.lesson_state_json)
                if progress and progress.lesson_state_json
                else "{}"
            ),
            # Add status constants for easy use in template if needed (optional but helpful)
            "LessonContentStatus": {
                "COMPLETED": LessonContent.StatusChoices.COMPLETED,
                "GENERATING": LessonContent.StatusChoices.GENERATING,
                "FAILED": LessonContent.StatusChoices.FAILED,
                "PENDING": LessonContent.StatusChoices.PENDING,
                # NOT_FOUND is effectively handled by PENDING now
            },
            # Add regeneration flags
            "trigger_regeneration": trigger_regeneration,
            "regeneration_url": regeneration_url,
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


@require_POST  # This view only handles POST requests
async def handle_lesson_interaction(  # Make async
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """
    Handles AJAX POST requests for lesson interactions (chat, answers, assessments).
    """
    # Explicitly type hint before check
    user = await request.auser()  # type: ignore[assignment]
    if not user.is_authenticated:
        # Handle unauthenticated user for AJAX request
        return JsonResponse(
            {"status": "error", "message": "Authentication required."}, status=401
        )
    # After this check, user cannot be AnonymousUser
    user = cast(User, user)  # Explicit cast using imported User
    user_message_content: str = ""
    submission_type: str = "chat"  # Default
    progress: Optional[UserProgress] = None

    try:
        # 1. Fetch lesson context first
        # Use sync_to_async for get_object_or_404 in async view
        get_syllabus = sync_to_async(get_object_or_404)
        get_module = sync_to_async(get_object_or_404)
        get_lesson = sync_to_async(get_object_or_404)

        syllabus = await get_syllabus(Syllabus, pk=syllabus_id)
        module = await get_module(Module, syllabus=syllabus, module_index=module_index)
        lesson = await get_lesson(Lesson, module=module, lesson_index=lesson_index)

        # 2. Get current progress and state
        state_result = await state_service.get_lesson_state_and_history(
            user=user, syllabus=syllabus, module=module, lesson=lesson  # type: ignore[arg-type]
        )
        progress = state_result[0]  # Unpack and type hint

        if progress is None:
            logger.error(
                "Could not retrieve UserProgress for interaction. User %s, Lesson %s",
                user.username,
                lesson.pk,
            )
            return JsonResponse(
                {"status": "error", "message": "Could not load user progress."},
                status=404,
            )

        # 3. Parse JSON request body
        try:
            data = json.loads(request.body)
            user_message_content = data.get("message", "").strip()
            submission_type = data.get("submission_type", "chat")
        except json.JSONDecodeError:
            logger.warning(
                "Received invalid JSON in AJAX request from user %s for lesson %s.",
                user.username,
                lesson.pk,
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON format."}, status=400
            )

        # 4. Validate input
        if not user_message_content:
            logger.warning(
                "Received empty message from user %s for lesson %s.",
                user.username,
                lesson.pk,
            )
            return JsonResponse(
                {"status": "error", "message": "Message cannot be empty."}, status=400
            )

        # 5. Call the interaction service
        logger.info(
            "Handling interaction (Type: %s) from user %s for lesson %s.",
            submission_type,
            user.username,
            lesson.pk,
        )
        try:
            service_response = interaction_service.handle_chat_message(
                user=user,  # type: ignore[arg-type]
                progress=progress,
                user_message_content=user_message_content,
                submission_type=submission_type,
            )

            if not service_response or not isinstance(service_response, dict):
                logger.error(
                    "Service handle_chat_message did not return expected data for user %s, lesson %s. Response: %s",
                    user.username,
                    lesson.pk,
                    service_response,
                )
                return JsonResponse(
                    {"status": "error", "message": "Failed to process interaction."},
                    status=500,
                )

            logger.info(
                "Interaction handled successfully for user %s, lesson %s.",
                user.username,
                lesson.pk,
            )
            # Refresh progress to get the absolute latest state after service call
            # Use sync_to_async for refresh_from_db
            await sync_to_async(progress.refresh_from_db)()

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
            return JsonResponse(response_data, status=200)

        except Exception as service_exc:
            logger.exception(
                "Service handle_chat_message raised an error for user %s, lesson %s.",
                user.username,
                lesson.pk,
                exc_info=service_exc,
            )
            return JsonResponse(
                {"status": "error", "message": "Failed to process interaction."},
                status=500,
            )

    # Handle context fetching errors (DoesNotExist -> Http404 -> 404)
    except Http404 as exc:
        logger.warning(
            "Lesson context not found during interaction for syllabus %s, module %s, lesson %s: %s",
            syllabus_id,
            module_index,
            lesson_index,
            str(exc),
        )
        return JsonResponse(
            {"status": "error", "message": "Lesson context not found."}, status=404
        )
    # Handle any other unexpected errors
    except Exception as e:
        # Log the specific user if available, otherwise use 'anonymous' or similar
        username = user.username if user and user.is_authenticated else "unknown"
        logger.exception(
            "Unexpected error handling interaction for user %s, lesson %s.",
            username,
            f"{syllabus_id}:{module_index}:{lesson_index}",
            exc_info=e,
        )
        return JsonResponse(
            {"status": "error", "message": "An unexpected error occurred."}, status=500
        )


@require_POST  # This view only handles POST requests for triggering generation
async def generate_lesson_content_async(  # Make async
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """
    Handles asynchronous requests to generate lesson content.

    Called via AJAX if the initial page load finds no existing content.
    Returns the generated content as HTML.
    """
    # Explicitly type hint before check
    user = await request.auser()  # type: ignore[assignment]
    if not user.is_authenticated:
        # Handle unauthenticated user for AJAX request
        return JsonResponse(
            {"status": "error", "message": "Authentication required."}, status=401
        )
    # After this check, user cannot be AnonymousUser
    user = cast(User, user)  # Explicit cast using imported User
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
        get_lesson_async = sync_to_async(get_object_or_404)
        lesson = await get_lesson_async(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )

        # Call the service to get or create content
        lesson_content = await content_service.get_or_create_lesson_content(
            lesson
        )  # Add await

        # Add isinstance check to help mypy with the awaited result type
        if isinstance(lesson_content, LessonContent) and isinstance(
            lesson_content.content, dict
        ):
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


@login_required
@require_GET
def check_lesson_content_status(
    _: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """Check the current status of lesson content generation."""
    try:
        lesson = get_object_or_404(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )

        lesson_content = LessonContent.objects.filter(lesson=lesson).first()

        if not lesson_content:
            # If no content exists, it's effectively not found from the client's perspective
            return JsonResponse(
                {"status": "error", "message": "Lesson content not found."}, status=404
            )

        status = lesson_content.status or LessonContent.StatusChoices.PENDING

        # Defensive: handle legacy empty status
        if not status:
            status = LessonContent.StatusChoices.PENDING

        response_data = {"status": status}

        if status == LessonContent.StatusChoices.COMPLETED:
            content = lesson_content.content
            exposition_value = None
            if isinstance(content, dict):
                exposition_value = content.get("exposition")
            if exposition_value:
                cleaned = clean_exposition_string(exposition_value)
                html_content = markdownify(cleaned)
                response_data["html_content"] = mark_safe(html_content)
            else:
                response_data["status"] = LessonContent.StatusChoices.FAILED
                response_data["error"] = (
                    "Lesson content is marked complete but missing exposition."
                )
        elif (
            status == LessonContent.StatusChoices.FAILED
        ):  # ERROR is not a valid status
            response_data["error"] = "Lesson content generation failed."

        return JsonResponse(response_data)

    except Lesson.DoesNotExist:
        # If the lesson itself doesn't exist, return 404
        return JsonResponse(
            {"status": "error", "message": "Lesson not found."}, status=404
        )
    except Exception as e:
        return JsonResponse({"status": "ERROR", "error": str(e)})


# @login_required # Cannot use with async view, check manually
@require_GET  # Use GET as it's triggered by a link click
async def change_difficulty_view(
    request: HttpRequest, syllabus_id: uuid.UUID
) -> HttpResponse:
    """Handles the request to switch to a lower difficulty syllabus."""
    user = await request.auser()
    if not user.is_authenticated:
        # Handle unauthenticated user
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": "Authentication required"}, status=401
            )
        messages.error(request, "You must be logged in to change syllabus difficulty.")
        return redirect(settings.LOGIN_URL + "?next=" + request.path)

    # Check if this is an AJAX request
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        # Fetch the current syllabus
        current_syllabus = await sync_to_async(Syllabus.objects.get)(
            pk=syllabus_id, user=user
        )
        current_level = current_syllabus.level
        topic = current_syllabus.topic

        # Determine the next lower level
        new_level = get_lower_difficulty(current_level)
        if new_level is None:
            if is_ajax:
                return JsonResponse(
                    {"success": False, "error": "Already at lowest difficulty level"}
                )
            messages.info(request, "You are already at the lowest difficulty level.")
            return redirect(reverse("syllabus:detail", args=[syllabus_id]))

        # Log the change
        logger.info(
            f"Changing difficulty for syllabus {syllabus_id} (User: {user.pk}) from '{current_level}' to "
            f"'{new_level}' for topic '{topic}'"
        )

        # Generate the syllabus synchronously (no background tasks)
        # Use the new synchronous service method
        new_syllabus_id = await syllabus_service.get_or_generate_syllabus_sync(
            topic=topic, level=new_level, user=user
        )

        # Get the URL for the new syllabus
        new_syllabus_url = reverse("syllabus:detail", args=[new_syllabus_id])

        if is_ajax:
            return JsonResponse({"success": True, "redirect_url": new_syllabus_url})
        else:
            # Fallback for non-AJAX requests (though unlikely with the JS approach)
            return redirect(new_syllabus_url)

    except Exception as e:
        logger.error(f"Error during difficulty change process: {e}", exc_info=True)
        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "error": str(e),  # Provide a generic error or specific if safe
                },
                status=500,
            )
        messages.error(
            request, "An unexpected error occurred while changing the difficulty."
        )
        # Redirect to dashboard or a relevant error page for non-AJAX
        return redirect(reverse("dashboard"))
