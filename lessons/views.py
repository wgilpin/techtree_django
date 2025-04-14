"""Views for the lessons app."""

# pylint: disable=no-member

import json
import logging
import re
from typing import Any, Dict, Optional, cast

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.models import (
    ConversationHistory,
    Lesson,
    LessonContent,
    Module,
    Syllabus,
    UserProgress,
)
from lessons.state_service import initialize_lesson_state
from syllabus.services import SyllabusService
from taskqueue.models import AITask
from taskqueue.tasks import process_ai_task

User = get_user_model()
logger = logging.getLogger(__name__)

# Type alias for auth user to avoid mypy errors
AuthUserType = Any  # Replace with actual type when available


@require_GET
@login_required
def lesson_wait(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Show waiting page while lesson content is being generated.
    """
    return render(
        request,
        "lessons/wait.html",
        {
            "syllabus_id": syllabus_id,
            "module_index": module_index,
            "lesson_index": lesson_index,
        },
    )


@require_GET
@login_required
def poll_lesson_ready(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> JsonResponse:
    """
    Minimal endpoint for polling if lesson content is ready.
    Returns JSON: {status: "COMPLETED"|"GENERATING"|"FAILED"|...}
    """
    try:
        lesson = get_object_or_404(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )
        lesson_content = LessonContent.objects.filter(lesson=lesson).first()
        if (
            lesson_content
            and lesson_content.status == LessonContent.StatusChoices.COMPLETED
        ):
            return JsonResponse({"status": "COMPLETED"})
        elif (
            lesson_content
            and lesson_content.status == LessonContent.StatusChoices.FAILED
        ):
            return JsonResponse({"status": "FAILED"})
        else:
            return JsonResponse({"status": "GENERATING"})
    except Exception as e:
        logger.error(f"Error in poll_lesson_ready: {e}", exc_info=True)
        return JsonResponse({"status": "ERROR", "error": str(e)}, status=500)


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

    # Fix: â€" -> – (common Mojibake for en-dash)
    cleaned_text = cleaned_text.replace("â€“", "\u2013")
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

        current_lesson_content: Optional[LessonContent] = LessonContent.objects.filter(
            lesson=lesson
        ).first()  # Type hint

        # --- Determine Content Status ---
        content_status: str = "NOT_FOUND"  # Default if no record
        if current_lesson_content:
            content_status = (
                current_lesson_content.status
            )  # Get status from the model field
        else:
            # No content exists: create a LessonContent record and trigger generation

            current_lesson_content = LessonContent.objects.create(
                lesson=lesson,
                content={},
                status=LessonContent.StatusChoices.PENDING,
            )
            content_status = LessonContent.StatusChoices.PENDING

            # Only create a task if one is not already pending/processing for this lesson
            existing_task = (
                AITask.objects.filter(
                    lesson=lesson,
                    task_type=AITask.TaskType.LESSON_CONTENT,
                    status__in=[
                        AITask.TaskStatus.PENDING,
                        AITask.TaskStatus.PROCESSING,
                    ],
                )
                .order_by("-created_at")
                .first()
            )
            if not existing_task:
                user_obj = cast(AuthUserType, request.user)
                task = AITask.objects.create(
                    task_type=AITask.TaskType.LESSON_CONTENT,
                    input_data={"lesson_id": str(lesson.pk)},
                    user=user_obj,
                    lesson=lesson,
                )
                process_ai_task(str(task.task_id))

        # If content is not ready, redirect to wait page
        if content_status in [
            LessonContent.StatusChoices.PENDING,
            LessonContent.StatusChoices.GENERATING,
            "NOT_FOUND",
        ]:
            return redirect(
                "lessons:lesson_wait",
                syllabus_id=syllabus_id,
                module_index=module_index,
                lesson_index=lesson_index,
            )

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

        if created:
            initial_lesson_content = LessonContent.objects.filter(
                lesson=lesson, status=LessonContent.StatusChoices.COMPLETED
            ).first()

            progress.lesson_state_json = initialize_lesson_state(
                user, lesson, initial_lesson_content
            )
            progress.save()
        if created or progress.status == "not_started":
            progress.status = "in_progress"
            progress.save(update_fields=["status", "updated_at"])
            logger.info(
                "Set/updated UserProgress %s status to 'in_progress'.", progress.pk
            )

        # --- Extract Exposition Content (defensively handle malformed content) ---
        exposition_content_value: Optional[str] = None
        try:
            if current_lesson_content and content_status not in [
                LessonContent.StatusChoices.FAILED,
                LessonContent.StatusChoices.GENERATING,
            ]:
                content_data = current_lesson_content.content
                if isinstance(content_data, dict):
                    exposition_value = content_data.get("exposition")
                    if exposition_value:
                        exposition_content_value = clean_exposition_string(
                            exposition_value
                        )
                # If content is not a dict or missing exposition, exposition_content_value remains None
        except Exception as e:
            logger.error(
                "Error extracting exposition content for lesson %s: %s",
                lesson.pk,
                e,
                exc_info=True,
            )
            exposition_content_value = None

        # After defensive extraction, adjust content_status if needed
        if exposition_content_value and (
            content_status == LessonContent.StatusChoices.PENDING or not content_status
        ):
            if current_lesson_content:
                logger.info(
                    "Found valid exposition for lesson content %s with status %s, "
                    "treating as COMPLETED for display.",
                    current_lesson_content.pk,  # type: ignore[union-attr]
                    content_status,
                )
            content_status = LessonContent.StatusChoices.COMPLETED
        elif content_status == LessonContent.StatusChoices.COMPLETED:
            if current_lesson_content and not isinstance(
                current_lesson_content.content, dict
            ):
                # If status was COMPLETED but content isn't a dict, mark as FAILED
                logger.warning(
                    "Lesson content (pk=%s) status is COMPLETED but content is not a dict (Type: %s). "
                    "Marking as FAILED.",
                    current_lesson_content.pk,
                    type(current_lesson_content.content),
                )
                content_status = LessonContent.StatusChoices.FAILED
            elif not exposition_content_value:
                # If status was COMPLETED but exposition is missing, mark as FAILED
                logger.warning(
                    "Lesson content (pk=%s) status is COMPLETED but 'exposition' is missing or empty. "
                    "Marking as FAILED.",
                    current_lesson_content.pk,  # type: ignore[union-attr]
                )
                content_status = LessonContent.StatusChoices.FAILED

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
            regeneration_url = reverse(
                "lessons:generate_lesson_content",
                args=[syllabus_id, module_index, lesson_index],
            )
            messages.info(
                request,
                "Lesson content generation failed previously. Automatically retrying...",
            )

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
            "Resource not found in lesson_detail view: %s:%s:%s - %s",
            syllabus_id,
            module_index,
            lesson_index,
            exc,
        )
        return HttpResponse("Lesson not found", status=404)
    except Exception as e:
        logger.error(
            "Error in lesson_detail view for %s:%s:%s: %s",
            syllabus_id,
            module_index,
            lesson_index,
            e,
            exc_info=True,
        )

        class Dummy:
            """dummy class so pk field is present"""

            def __init__(self, pk):
                self.pk = pk
                self.module_index = 0
                self.lesson_index = 0
                self.title = ""
                self.summary = ""

        dummy_uuid = "00000000-0000-0000-0000-000000000000"
        dummy_syllabus = Dummy(dummy_uuid)
        dummy_module = Dummy(dummy_uuid)
        dummy_lesson = Dummy(dummy_uuid)

        # Type annotation for fallback_context

        fallback_context: Dict[str, Any] = {
            "syllabus": dummy_syllabus,
            "module": dummy_module,
            "lesson": dummy_lesson,
            "progress": None,
            "title": "Lesson",
            "exposition_content": None,
            "content_status": "ERROR",
            "absolute_lesson_number": None,
            "conversation_history": [],
            "lesson_state_json": "{}",
            "LessonContentStatus": {
                "COMPLETED": "COMPLETED",
                "GENERATING": "GENERATING",
                "FAILED": "FAILED",
                "PENDING": "PENDING",
            },
            "trigger_regeneration": False,
            "regeneration_url": None,
        }
        return render(
            request, "lessons/lesson_detail.html", fallback_context, status=200
        )


@require_POST  # This view only handles POST requests
def handle_lesson_interaction(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Handle user interactions with a lesson (POST requests).

    This includes submitting questions, answers, and other interactions.
    """
    if not request.user.is_authenticated:
        # For AJAX requests, return 401 Unauthorized instead of redirect
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"status": "error", "message": "Authentication required"}, status=401
            )
        # For non-AJAX, redirect to login
        return redirect_to_login(request.get_full_path())

    user: "AuthUserType" = request.user  # type: ignore[assignment] # Use type alias
    try:
        # Parse JSON body explicitly
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload"}, status=400
            )

        user_message = data.get("message", "").strip()
        data.get("submission_type", "chat").strip()

        if not user_message:
            return JsonResponse(
                {"status": "error", "message": "No message provided"}, status=400
            )

        # Fetch required objects
        try:
            syllabus = get_object_or_404(
                Syllabus, pk=syllabus_id
            )  # Add user check later
            module = get_object_or_404(
                Module, syllabus=syllabus, module_index=module_index
            )
            lesson = get_object_or_404(Lesson, module=module, lesson_index=lesson_index)
            progress = get_object_or_404(
                UserProgress, user=user, syllabus=syllabus, lesson=lesson
            )

            lesson_content = LessonContent.objects.filter(
                lesson=lesson,
                status=LessonContent.StatusChoices.COMPLETED,
            ).first()
            if not lesson_content:
                return JsonResponse(
                    {"status": "error", "message": "Lesson content not available yet"},
                    status=400,
                )
        except Exception as e:
            logger.error(f"Error fetching objects for interaction: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=404)

        # Create a new conversation history entry for the user's message
        ConversationHistory.objects.create(
            progress=progress, role="user", content=user_message
        )

        # Create a task to process the interaction
        user_obj = cast(AuthUserType, request.user)
        task = AITask.objects.create(
            task_type=AITask.TaskType.LESSON_INTERACTION,
            input_data={
                "user_message": user_message,
                "lesson_id": str(lesson.pk),
                "progress_id": str(progress.pk),
            },
            user=user_obj,
            lesson=lesson,
        )

        # Process the task
        process_ai_task(str(task.task_id))

        # Return a success response with the task ID for polling
        return JsonResponse({"task_id": str(task.task_id), "status": "pending"})

    except Exception as e:
        logger.error(f"Error in handle_lesson_interaction: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_POST  # This view only handles POST requests for triggering generation
@login_required
def generate_lesson_content(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Trigger generation of lesson content.

    This is used when content is missing or needs to be regenerated.
    """
    try:
        # Fetch required objects
        lesson = get_object_or_404(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )

        # Create a task to generate the content
        user_obj = cast(AuthUserType, request.user)
        task = AITask.objects.create(  # type: ignore[attr-defined]
            task_type=AITask.TaskType.LESSON_CONTENT,
            input_data={
                "lesson_id": str(lesson.pk),
            },
            user=user_obj,
            lesson=lesson,
        )

        # Process the task
        process_ai_task(str(task.task_id))

        # Return a success response with the task ID for polling
        return JsonResponse(
            {
                "task_id": str(task.task_id),
                "status": "processing",
                "message": "Lesson content generation started",
            }
        )

    except Exception as e:
        logger.error(f"Error in generate_lesson_content: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def check_lesson_content_status(
    _: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Check the status of lesson content generation.

    This is used for polling the status of a generation task.
    """
    try:
        # Fetch required objects
        lesson = get_object_or_404(
            Lesson,
            module__syllabus__pk=syllabus_id,
            module__module_index=module_index,
            lesson_index=lesson_index,
        )

        # Check if there's a task for this lesson
        task = (
            AITask.objects.filter(
                lesson=lesson,
                task_type=AITask.TaskType.LESSON_CONTENT,
            )
            .order_by("-created_at")
            .first()
        )

        if not task:
            return JsonResponse(
                {"status": "unknown", "message": "No generation task found"}
            )

        # Check if there's content for this lesson
        lesson_content = LessonContent.objects.filter(lesson=lesson).first()
        content_status = lesson_content.status if lesson_content else "NOT_FOUND"

        # Return the status
        return JsonResponse(
            {
                "task_status": task.status,
                "content_status": content_status,
                "task_id": str(task.pk),
                "message": f"Task status: {task.status}, Content status: {content_status}",
            }
        )

    except Exception as e:
        logger.error(f"Error in check_lesson_content_status: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@require_GET
@login_required
def check_interaction_status(
    request: HttpRequest,
    syllabus_id: str,
    module_index: int,
    lesson_index: int,
) -> JsonResponse:
    """
    Poll the status of a lesson interaction (chat/answer) by task_id.
    Returns assistant message and lesson state if ready.
    Always returns JSON, even on error.
    """

    task_id = request.GET.get("task_id")
    if not task_id:
        return JsonResponse({"status": "error", "error": "Missing task_id"}, status=400)
    try:
        task = AITask.objects.get(pk=task_id)
    except Exception as e:
        # Always return JSON, never HTML
        return JsonResponse(
            {"status": "error", "error": f"Task not found: {str(e)}"}, status=200
        )

    # Get progress_id from task
    progress_id = task.input_data.get("progress_id")
    if not progress_id:
        return JsonResponse(
            {"status": "error", "error": "No progress_id in task"}, status=500
        )
    try:
        progress = UserProgress.objects.get(pk=progress_id)
    except UserProgress.DoesNotExist:
        return JsonResponse(
            {"status": "error", "error": "Progress not found"}, status=404
        )

    # Get the latest assistant message for this progress
    assistant_message = (
        ConversationHistory.objects.filter(progress=progress, role="assistant")
        .order_by("-timestamp")
        .first()
    )
    assistant_content = assistant_message.content if assistant_message else None

    # If no assistant message yet, keep polling (pending)
    if not assistant_message:
        # Optionally, check if the task failed
        if task.status == AITask.TaskStatus.FAILED:
            # Defensive: some AITask models may not have an 'error' field
            error_msg = getattr(task, "error", None) or "Task failed"
            return JsonResponse({"status": "failed", "error": error_msg})
        return JsonResponse({"status": "pending"})

    # Return lesson state and assistant message
    return JsonResponse(
        {
            "status": "completed",
            "assistant_message": assistant_content,
            "lesson_state": progress.lesson_state_json,
        }
    )


@require_GET  # Use GET as it's triggered by a link click
@login_required  # type: ignore
def change_difficulty_view(request: HttpRequest, syllabus_id: str) -> HttpResponse:
    """
    Change the difficulty of a syllabus.

    This creates a new syllabus with the same topic but different difficulty.
    The difficulty is passed as a query parameter.
    """
    # Get difficulty from query parameter
    difficulty = request.GET.get("difficulty", "beginner")
    try:
        # Validate difficulty
        valid_difficulties = ["beginner", "intermediate", "advanced"]
        if difficulty not in valid_difficulties:
            messages.error(request, f"Invalid difficulty: {difficulty}")
            if hasattr(request, "htmx") and request.htmx:

                response = HttpResponse()
                response["HX-Redirect"] = reverse("syllabus:detail", args=[syllabus_id])
                return response
            return redirect("syllabus:detail", syllabus_id=syllabus_id)

        # Get the original syllabus
        original_syllabus = Syllabus.objects.get(pk=syllabus_id)

        # Check if a syllabus with this topic and difficulty already exists
        existing_syllabus = SyllabusService.get_syllabus_by_topic_and_level(  # type: ignore[attr-defined]
            original_syllabus.topic, difficulty
        )

        if existing_syllabus:
            # If it exists, redirect to it
            messages.info(
                request,
                f"A {difficulty} syllabus for '{original_syllabus.topic}' already exists.",
            )
            if hasattr(request, "htmx") and request.htmx:

                response = HttpResponse()
                response["HX-Redirect"] = reverse(
                    "syllabus:detail", args=[str(existing_syllabus.pk)]
                )
                return response
            return redirect("syllabus:detail", syllabus_id=str(existing_syllabus.pk))

        # Otherwise, create a new syllabus with the new difficulty
        user_obj = cast(AuthUserType, request.user)
        logger.info(
            f"Creating new {difficulty} syllabus for topic: {original_syllabus.topic}"
        )

        # Use the service to generate a new syllabus
        new_syllabus_id = SyllabusService.get_or_generate_syllabus(  # type: ignore[attr-defined]
            topic=original_syllabus.topic,
            level=difficulty,
            user=user_obj,
        )

        # If this is an HTMX request, return HX-Redirect header
        if hasattr(request, "htmx") and request.htmx:

            response = HttpResponse()
            response["HX-Redirect"] = reverse(
                "syllabus:detail", args=[str(new_syllabus_id)]
            )
            return response

        # For non-AJAX requests, redirect to the syllabus detail page
        messages.success(
            request,
            f"Created a new {difficulty} syllabus for '{original_syllabus.topic}'.",
        )
        return redirect("syllabus:detail", syllabus_id=str(new_syllabus_id))

    except ObjectDoesNotExist:
        logger.error(
            f"Syllabus with ID {syllabus_id} not found in change_difficulty_view"
        )
        messages.error(request, "The requested syllabus was not found.")
        return redirect("dashboard")
    except Exception as e:
        logger.error(f"Error in change_difficulty_view: {e}", exc_info=True)
        messages.error(request, "An error occurred while changing difficulty.")
        return redirect("syllabus:detail", syllabus_id=syllabus_id)
