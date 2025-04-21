"""Views for the lessons app."""

# pylint: disable=no-member

import json
import logging
from typing import Optional, cast

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.models import (ConversationHistory, Lesson, LessonContent, Module,
                         Syllabus, UserProgress)
from lessons.state_service import initialize_lesson_state
from lessons.view_helpers.content_helpers import (
    _extract_and_validate_exposition, _handle_failed_content,
    _handle_lesson_content_creation)
from lessons.view_helpers.error_handlers import _handle_lesson_detail_error
from lessons.view_helpers.general_helpers import (_build_lesson_context,
                                                  _get_lesson_objects)
from syllabus.services import SyllabusService
from taskqueue.models import AITask
from taskqueue.tasks import process_ai_task as schedule_ai_task

# Get the actual user model class
UserModel = get_user_model()
logger = logging.getLogger(__name__)

# Define the type alias using the actual user model
AuthUserType = UserModel # Use the retrieved UserModel


@require_POST
@login_required
def wipe_chat(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Wipes the chat history for a given lesson and adds a new initial message.
    """
    user: AuthUserType = request.user # type: ignore[assignment,valid-type]
    try:
        syllabus = get_object_or_404(Syllabus, pk=syllabus_id)
        module = get_object_or_404(Module, syllabus=syllabus, module_index=module_index)
        lesson = get_object_or_404(Lesson, module=module, lesson_index=lesson_index)
        progress = get_object_or_404(
            UserProgress, user=user, syllabus=syllabus, lesson=lesson
        )

        # Delete all conversation history for this progress
        ConversationHistory.objects.filter(progress=progress).delete()

        # Add the "lesson started again" message
        ConversationHistory.objects.create(
            progress=progress,
            role="assistant",
            content="Ok, we've started this lesson again.",
        )

        # Add the standard welcome message
        welcome_message_content = (
            "Is there anything I can explain more? Ask me any questions, or we can do "
            "exercises to help to think about it all. Once you're happy with this "
            "lesson, ask me to start a quiz"
        )
        ConversationHistory.objects.create(
            progress=progress, role="assistant", content=welcome_message_content
        )

        # Fetch the updated conversation history
        conversation_history = list(
            ConversationHistory.objects.filter(progress=progress).order_by("timestamp")
        )

        # Render the partial template with the new history
        context = {"conversation_history": conversation_history}
        return render(request, "lessons/partials/chat_history.html", context)

    except Exception as e:
        logger.error(f"Error in wipe_chat view: {e}", exc_info=True)
        # Return an error message within the chat history div for HTMX
        # You might want a more specific error template or message handling
        return HttpResponse(
            '<p class="text-danger">An error occurred while wiping the chat.</p>',
            status=500,
        )


# UserModel already defined above
# logger already defined above

# AuthUserType already defined above


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
    _: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
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


@login_required
def lesson_detail(
    request: HttpRequest, syllabus_id: str, module_index: int, lesson_index: int
) -> HttpResponse:
    """
    Display a specific lesson within a syllabus module (GET request).

    Handles fetching lesson content, user progress, and history for display.
    POST interactions are handled by the 'handle_lesson_interaction' view.
    """

    user: AuthUserType = request.user # type: ignore[assignment,valid-type]

    if request.method == "POST":
        # Redirect POST requests intended for the detail page (e.g., non-JS form fallback)
        logger.warning(
            "Received standard POST on lesson_detail view for lesson %s:%s:%s. Redirecting.",
            syllabus_id,
            module_index,
            lesson_index,
        )
        return redirect(request.path_info)

    # --- GET Request Logic ---
    try:
        syllabus, module, lesson, progress, created = _get_lesson_objects(
            user, syllabus_id, module_index, lesson_index
        )

        # Pass the actual user object
        current_lesson_content, content_status = _handle_lesson_content_creation(
            lesson, user
        )

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

        _update_progress_if_needed(progress, user, lesson, created)

        exposition_content_value, content_status = _extract_and_validate_exposition(
            current_lesson_content, content_status
        )

        conversation_history = _prepare_conversation_history(progress, lesson)

        trigger_regeneration, regeneration_url = _handle_failed_content(
            content_status, syllabus_id, module_index, lesson_index, request
        )

        context = _build_lesson_context(
            syllabus,
            module,
            lesson,
            progress,
            exposition_content_value,
            content_status,
            absolute_lesson_number,
            conversation_history,
            trigger_regeneration,
            regeneration_url,
        )
        return render(request, "lessons/lesson_detail.html", context)
    except (Syllabus.DoesNotExist, Module.DoesNotExist, Lesson.DoesNotExist) as exc:
        return _handle_lesson_detail_error(
            exc, syllabus_id, module_index, lesson_index, request, status=404
        )
    except Exception as e:
        return _handle_lesson_detail_error(
            e, syllabus_id, module_index, lesson_index, request
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

    user: AuthUserType = request.user # type: ignore[assignment,valid-type]
    try:
        # Parse JSON body explicitly
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload"}, status=400
            )

        user_message = data.get("message", "").strip()
        # submission_type = data.get("submission_type", "chat").strip() # Variable not used

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
        user_obj = cast(AuthUserType, request.user) # type: ignore[valid-type]
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
        schedule_ai_task(task_id=task.task_id)  # Pass task_id

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
        user_obj = cast(AuthUserType, request.user) # type: ignore[valid-type]
        task = AITask.objects.create(  # type: ignore[attr-defined]
            task_type=AITask.TaskType.LESSON_CONTENT,
            input_data={
                "lesson_id": str(lesson.pk),
            },
            user=user_obj,
            lesson=lesson,
        )

        # Process the task
        schedule_ai_task(task_id=task.task_id)  # Pass task_id

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
        user_obj = cast(AuthUserType, request.user) # type: ignore[valid-type]
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
        return redirect("dashboard")  # type: ignore
    except Exception as e:
        logger.error(f"Error in change_difficulty_view: {e}", exc_info=True)
        messages.error(request, "An error occurred while changing difficulty.")
        # Redirect to dashboard as syllabus_id might not be available
        return redirect("dashboard")  # type: ignore


def _prepare_conversation_history(progress, lesson):
    """Prepare conversation history with initial welcome message if empty."""
    history = list(
        ConversationHistory.objects.filter(progress=progress).order_by("timestamp")
    )

    if not history:
        welcome_content = (
            "Is there anything I can explain more? Ask me any questions, or we can do "
            "exercises to help to think about it all. Once you're happy with this "
            "lesson, ask me to start a quiz"
        )
        history.insert(
            0,
            ConversationHistory(
                role="assistant",
                content=welcome_content,
            ),
        )
        logger.info(
            "Prepended welcome message to empty history for lesson %s", lesson.pk
        )
    return history


def _update_progress_if_needed(progress, user, lesson, created):
    """Initialize and update user progress status as needed."""
    if created:
        initial_lesson_content = LessonContent.objects.filter(
            lesson=lesson, status=LessonContent.StatusChoices.COMPLETED
        ).first()

        # Pass the correctly typed user object
        progress.lesson_state_json = initialize_lesson_state(
            user, lesson, initial_lesson_content
        )
        progress.save()

    if created or progress.status == "not_started":
        progress.status = "in_progress"
        progress.save(update_fields=["status", "updated_at"])
        logger.info("Set/updated UserProgress %s status to 'in_progress'.", progress.pk)


# --- Quiz Views ---


@login_required
@require_POST # Keep POST as the button uses hx-post
async def start_quiz_view(request: HttpRequest, lesson_id: str) -> HttpResponse:
    """
    Initiates the quiz for a lesson by updating user progress state,
    scheduling an AI task to generate the first question, and notifying the user via chat.
    """
    user: AuthUserType = request.user # type: ignore[assignment,valid-type]
    try:
        lesson = await database_sync_to_async(get_object_or_404)(Lesson, pk=lesson_id)
        progress = await database_sync_to_async(get_object_or_404)(
            UserProgress, user=user, lesson=lesson
        )
        syllabus_level = await database_sync_to_async(lambda: lesson.module.syllabus.level)() # type: ignore

        # Update lesson state to indicate quiz started
        # Assuming lesson_state_json is a JSONField
        current_state = progress.lesson_state_json or {}
        # Ensure we don't overwrite other state, just add/update quiz_state
        updated_state = {**current_state, "quiz_state": {"step": "start"}}
        progress.lesson_state_json = updated_state # Update the field directly

        await database_sync_to_async(progress.save)(update_fields=["lesson_state_json", "updated_at"])

        # Create and trigger background task for quiz processing
        task = await database_sync_to_async(AITask.objects.create)(
            task_type=AITask.TaskType.PROCESS_QUIZ_INTERACTION,
            input_data={
                "lesson_id": str(lesson.pk),
                "user_id": str(user.pk),
                "difficulty": syllabus_level,
                "state": {"step": "start"}, # Initial state marker for quiz processor
            },
            user=user,
            lesson=lesson,
            # progress=progress, # Link task to progress if needed for easier lookup
        )
        await sync_to_async(schedule_ai_task)(str(task.task_id))

        logger.info(f"Initiated quiz for lesson {lesson_id} and user {user.pk}. Scheduled AITask {task.task_id}.")

        # Send a confirmation message to the chat via WebSocket
        channel_layer = get_channel_layer()
        group_name = f"lesson_chat_{lesson_id}"

        # Create a simple assistant message object (mimicking ConversationHistory)
        # In a real scenario, you might want to save this to the DB as well
        start_message_obj = ConversationHistory(
            role="assistant",
            content="Okay, let's start the quiz! Here comes the first question...",
            message_type="chat", # Or a new type like 'quiz_status'
            progress=progress # Associate with progress if saving
        )
        # await database_sync_to_async(start_message_obj.save)() # Optional: save to DB

        start_message_html = render_to_string(
            "lessons/_chat_message.html", {"message": start_message_obj}
        )
        scroll_script = (
            '<script>var chatHistory = document.getElementById("chat-history"); '
            "chatHistory.scrollTop = chatHistory.scrollHeight;</script>"
        )
        oob_chat_message = (
            f'<div id="chat-history" hx-swap-oob="beforeend">{start_message_html}{scroll_script}</div>'
        )

        await channel_layer.group_send(
            group_name,
            {
                "type": "chat.message", # Use the existing chat message handler
                "message": oob_chat_message,
            },
        )

        # Return 204 No Content to indicate success without changing the page
        # The button remains, but the quiz starts in the chat.
        return HttpResponse(status=204)

    except Lesson.DoesNotExist:
        logger.error(f"Lesson with ID {lesson_id} not found in start_quiz_view.")
        # Return an HTMX-friendly error message that replaces the button
        return HttpResponse(
            '<div class="alert alert-danger">Error: Lesson not found.</div>',
            status=404,
            headers={'HX-Reswap': 'outerHTML', 'HX-Retarget': '#quiz-trigger-area'} # Tell HTMX where to put the error
        )
    except UserProgress.DoesNotExist:
        logger.error(f"UserProgress not found for user {user.pk} and lesson {lesson_id} in start_quiz_view.")
        return HttpResponse(
            '<div class="alert alert-danger">Error: Could not find your progress for this lesson.</div>',
            status=404,
            headers={'HX-Reswap': 'outerHTML', 'HX-Retarget': '#quiz-trigger-area'}
        )
    except Exception as e:
        logger.error(f"Error in start_quiz_view: {e}", exc_info=True)
        return HttpResponse(
            '<div class="alert alert-danger">An error occurred initiating the quiz.</div>',
            status=500,
            headers={'HX-Reswap': 'outerHTML', 'HX-Retarget': '#quiz-trigger-area'}
        )
