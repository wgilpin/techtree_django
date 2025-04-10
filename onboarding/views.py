"""Views for the onboarding app."""

import json  # Import json module
import logging
import uuid
from typing import Optional, cast, Dict, Any

from asgiref.sync import sync_to_async
from django.contrib import messages  # Add messages framework
from django.contrib.auth.decorators import login_required  # Add login_required
from django.contrib.auth.models import User  # Import User directly
from django.http import JsonResponse
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import (  # Add redirect, get_object_or_404
    get_object_or_404,
    redirect,
    render,
)
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings # Import settings

# Import difficulty constants
from core.constants import DIFFICULTY_BEGINNER, DIFFICULTY_LEVELS, DIFFICULTY_FROM_VALUE

# Import Syllabus Service and Exceptions
# Import the model for saving results
from core.models import Syllabus  # Import Syllabus model from core app
from core.models import UserAssessment
from syllabus.services import SyllabusService
from taskqueue.models import AITask # Import AITask
from taskqueue.tasks import process_ai_task # Import process_ai_task
# Import AI logic and state definition
from .ai import AgentState, TechTreeAI

logger = logging.getLogger(__name__)

# --- Async Database/Session Wrappers ---


# Wrap synchronous session operations needed in async views
@sync_to_async
def get_session_value(session, key, default=None):
    """Asynchronously gets a value from the session."""
    return session.get(key, default)


@sync_to_async
def set_session_value(session, key, value):
    """Asynchronously sets a value in the session."""
    session[key] = value
    # Saving the session might also be needed depending on backend/settings
    # session.save()


@sync_to_async
def del_session_key(session, key):
    """Asynchronously deletes a key from the session."""
    if key in session:
        del session[key]
        # session.save()


# Wrap synchronous UserAssessment creation
@sync_to_async
def create_user_assessment(**kwargs):
    """Asynchronously creates a UserAssessment record in the database."""
    # Pass user object directly if available, or user_id if needed
    # Ensure user object is fetched synchronously if passed by ID
    return UserAssessment.objects.create(**kwargs)  # pylint: disable=no-member


# --- Helper to get/initialize AI instance ---
def get_ai_instance() -> TechTreeAI:
    """Instantiates the AI logic class."""
    # Instantiate services (consider dependency injection later)
    # Assuming TechTreeAI is the assessment AI
    # TODO: Review if these should be instantiated per request or globally
    return TechTreeAI()


syllabus_service = SyllabusService()


# --- Assessment Views ---


@require_GET
def start_assessment_view(request: HttpRequest, topic: str) -> JsonResponse:
    """Start a new onboarding assessment for a given topic."""
    logger.info(f"Starting assessment view for topic: {topic}")
    logger.debug("Before fetching user")
    user = request.user
    logger.debug("After fetching user")
    user_id: Optional[int] = None
    if user.is_authenticated:
        user_id = user.pk

    try:
        logger.debug("Before get_ai_instance and initialize_state")
        ai_instance = get_ai_instance()
        assessment_state = ai_instance.initialize_state(topic)
        assessment_state["user_id"] = user_id
        logger.debug("After get_ai_instance and initialize_state, before perform_internet_search")

        search_results = ai_instance.perform_internet_search(assessment_state)
        logger.debug("After perform_internet_search, before generate_question")
        assessment_state["wikipedia_content"] = search_results.get(
            "wikipedia_content", ""
        )
        assessment_state["google_results"] = search_results.get("google_results", [])
        assessment_state["search_completed"] = search_results.get(
            "search_completed", False
        )

        question_results = ai_instance.generate_question(assessment_state)
        logger.debug("After generate_question, before saving session")
        assessment_state["current_question"] = question_results.get(
            "current_question", "Error"
        )
        assessment_state["current_question_difficulty"] = question_results.get(
            "current_question_difficulty",
            DIFFICULTY_BEGINNER,
        )
        assessment_state["questions_asked"] = question_results.get(
            "questions_asked", []
        )
        assessment_state["question_difficulties"] = question_results.get(
            "question_difficulties", []
        )

        # Save initial state to session synchronously
        request.session["assessment_state"] = assessment_state
        logger.debug("After saving session, preparing response")
        logger.info(
            f"Assessment state initialized in session for user: {user_id}, topic: {topic}"
        )

        difficulty_value: int = assessment_state.get("current_question_difficulty", 0)
        difficulty_name = DIFFICULTY_FROM_VALUE.get(difficulty_value, DIFFICULTY_BEGINNER)
        max_difficulty = len(DIFFICULTY_LEVELS)

        return JsonResponse(
            {
                "search_status": assessment_state.get("search_completed", False),
                "question": assessment_state.get("current_question"),
                "difficulty": difficulty_name,
                "difficulty_value": difficulty_value,
                "max_difficulty": max_difficulty,
                "is_complete": False,
                "question_number": 1,
            }
        )

    except Exception as e:
        logger.error(f"Error starting assessment: {str(e)}", exc_info=True)
        # Clear session key synchronously
        request.session.pop("assessment_state", None)
        return JsonResponse(
            {"error": f"Failed to start assessment: {str(e)}"}, status=500
        )


# @require_POST # Removed decorator - body access happens below
def submit_answer_view(
    request: HttpRequest,
) -> HttpResponse:
    """Process a user's submitted answer during an assessment."""
    logger.info("Submit answer view called.")

    assessment_state_data = request.session.get("assessment_state")
    if assessment_state_data is None:
        return JsonResponse({"error": "No active assessment found."}, status=400)

    try:
        raw_state_data: Dict[str, Any] = assessment_state_data
        assessment_state: dict = cast(dict, raw_state_data)
    except (TypeError, KeyError):
        logger.error("Session data does not match expected AgentState structure.")
        if "assessment_state" in request.session:
            del request.session["assessment_state"]
        return JsonResponse({"error": "Invalid assessment state found. Please restart."}, status=400)

    if assessment_state.get("is_complete", False):
        return JsonResponse({
            "is_complete": True,
            "knowledge_level": assessment_state.get("knowledge_level"),
            "score": assessment_state.get("score"),
            "feedback": "Assessment already completed.",
        })

    try:
        data = json.loads(request.body)
        answer = data.get("answer")
        is_skip = data.get("skip", False) is True
        if not answer and not is_skip:
            return JsonResponse({"error": "Missing 'answer' or 'skip' flag in JSON payload."}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    # Save updated state back to session immediately
    request.session["assessment_state"] = assessment_state

    from taskqueue.models import AITask
    from taskqueue.tasks import process_ai_task

    user_obj = request.user if request.user.is_authenticated else None

    # Enqueue background task for answer evaluation and next question generation
    task = AITask.objects.create(
        task_type=AITask.TaskType.LESSON_INTERACTION,
        input_data={
            "assessment_state": assessment_state,
            "user_id": str(request.user.id) if request.user.is_authenticated else None,
            "answer": answer,
            "skip": is_skip,
            "action": "evaluate_and_generate_next",
        },
        user=user_obj,
    )
    process_ai_task(str(task.task_id))

    return JsonResponse({
        "status": "processing",
        "task_id": str(task.task_id),
        "wait_url": "/api/tasks/status/?task_id=" + str(task.task_id),
        "message": "Processing your answer and generating next question.",
    })



def dict_to_agent_state(d: dict) -> AgentState:
    """Helper to coerce a dict to AgentState TypedDict."""
    return cast(AgentState, d)


from typing import Awaitable

def generate_next_question(assessment_state: dict, ai_instance, settings) -> dict:
    """Generate the next question and update assessment state."""
    question_results = ai_instance.generate_question(assessment_state.copy())

    assessment_state["current_question"] = question_results.get("current_question", "Error")
    assessment_state["current_question_difficulty"] = question_results.get(
        "current_question_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
    )
    assessment_state["questions_asked"] = question_results.get(
        "questions_asked", assessment_state.get("questions_asked", [])
    )
    assessment_state["question_difficulties"] = question_results.get(
        "question_difficulties", assessment_state.get("question_difficulties", [])
    )
    if "step" in question_results:
        assessment_state["step"] = question_results["step"]

    return assessment_state




def handle_normal_answer(assessment_state: dict, ai_instance, answer: str, settings) -> dict:
    """
    Update assessment state for a normal answer submission.
    """
    eval_results = ai_instance.evaluate_answer(assessment_state.copy(), answer)

    assessment_state["answers"] = eval_results.get("answers", assessment_state.get("answers", []))
    assessment_state["answer_evaluations"] = eval_results.get("answer_evaluations", assessment_state.get("answer_evaluations", []))
    assessment_state["consecutive_wrong_at_current_difficulty"] = eval_results.get(
        "consecutive_wrong_at_current_difficulty",
        assessment_state.get("consecutive_wrong_at_current_difficulty", 0),
    )
    assessment_state["current_target_difficulty"] = eval_results.get(
        "current_target_difficulty",
        assessment_state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY),
    )
    assessment_state["consecutive_hard_correct_or_partial"] = eval_results.get(
        "consecutive_hard_correct_or_partial",
        assessment_state.get("consecutive_hard_correct_or_partial", 0),
    )
    assessment_state["feedback"] = eval_results.get("feedback")

    return assessment_state


def handle_skip_answer(assessment_state: dict, settings) -> dict:
    """Update assessment state for a skipped answer."""
    target_difficulty = assessment_state.get("current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY)
    consecutive_wrong = assessment_state.get("consecutive_wrong_at_current_difficulty", 0) + 1
    consecutive_hard_correct = 0
    min_difficulty = 0

    if consecutive_wrong >= 2 and target_difficulty > min_difficulty:
        target_difficulty -= 1
        consecutive_wrong = 0

    assessment_state["answers"] = assessment_state.get("answers", []) + ["[SKIPPED]"]
    assessment_state["answer_evaluations"] = assessment_state.get("answer_evaluations", []) + [0.0]
    assessment_state["feedback"] = "Question skipped."
    assessment_state["consecutive_wrong_at_current_difficulty"] = consecutive_wrong
    assessment_state["consecutive_hard_correct_or_partial"] = consecutive_hard_correct
    assessment_state["current_target_difficulty"] = target_difficulty

    return assessment_state


def finalize_assessment_and_trigger_syllabus_task(request, user, assessment_state):
    """Finalize assessment, save result, and create syllabus generation task."""
    topic = assessment_state.get("topic")
    level = assessment_state.get("knowledge_level")

    # Clear assessment state from session
    from asgiref.sync import async_to_sync
    async_to_sync(del_session_key)(request.session, "assessment_state")

    if not topic or not level or not user.is_authenticated:
        return {
            "error": "Missing topic, level, or user not authenticated."
        }

    # Create or get background task
    task, created = AITask.objects.get_or_create(
        user=user,
        task_type=AITask.TaskType.SYLLABUS_GENERATION,
        status__in=[AITask.TaskStatus.PENDING, AITask.TaskStatus.PROCESSING],
        defaults={
            "input_data": {
                "topic": topic,
                "knowledge_level": level,
                "user_id": user.pk,
            },
        },
    )

    if created:
        async_to_sync(process_ai_task)(str(task.task_id))
        feedback_msg = "Assessment complete. Syllabus generation started..."
    else:
        feedback_msg = "Assessment complete. Syllabus generation is already in progress..."

    try:
        wait_url = reverse("onboarding:wait_for_syllabus", kwargs={"task_id": task.task_id})
    except NoReverseMatch:
        wait_url = None

    return {
        "task_id": str(task.task_id),
        "wait_url": wait_url,
        "feedback": feedback_msg,
    }


@require_GET
def assessment_page_view(request: HttpRequest, topic: str) -> HttpResponse:
    """
    Renders the main assessment page, passing the topic and start URL. (Sync)
    """
    # This view just renders the template, no async operations needed here
    try:
        start_url = reverse("onboarding:onboarding_start", kwargs={"topic": topic})
    except NoReverseMatch:
        logger.error(f"Could not reverse URL for onboarding_start with topic: {topic}")
        return HttpResponseBadRequest("Invalid topic for assessment.")

    context = {
        "topic": topic,
        "start_url": start_url,
    }
    return render(request, "onboarding/assessment.html", context)


@login_required
@require_POST  # Ensure only POST requests are allowed
def skip_assessment_view(request: HttpRequest) -> HttpResponse:
    """Handle the request to skip the onboarding assessment.

    Creates a placeholder UserAssessment record indicating the skip
    and sets the knowledge level to the beginner constant. Redirects to the dashboard.
    """
    # Cast request.user to User as login_required guarantees authentication
    user = cast(User, request.user)
    logger.info(f"User {user.username} (ID: {user.pk}) requested to skip assessment.")

    try:
        # Create a record to signify the assessment was skipped
        # Using a specific topic to easily identify skipped assessments
        UserAssessment.objects.create(  # pylint: disable=no-member
            user=user,  # type: ignore[misc]
            topic="Assessment Skipped",
            knowledge_level=DIFFICULTY_BEGINNER,  # Use constant
            score=None,  # No score applicable
            question_history=None,
            response_history=None,
        )
        logger.info(f"Created 'Assessment Skipped' record for user {user.pk}.")
        messages.info(
            request, "Assessment skipped. You can start learning from the basics."
        )
        # Redirect to the main dashboard
        dashboard_url = reverse("dashboard")  # Use correct non-namespaced name
        return redirect(dashboard_url)

    except Exception as e:
        logger.error(
            f"Error creating skipped assessment record for user {user.pk}: {e}",
            exc_info=True,
        )
        messages.error(
            request, "There was an error processing your request. Please try again."
        )
        # Redirect back to dashboard even on error, as it's a safe fallback
        dashboard_url = reverse("dashboard")  # Use correct non-namespaced name
        return redirect(dashboard_url)


# --- Syllabus Generation Loading/Polling Views ---


@login_required
@require_GET
def generating_syllabus_view(
    request: HttpRequest, syllabus_id: uuid.UUID
) -> HttpResponse:
    """Renders the page indicating syllabus generation is in progress."""
    logger.info(f"Displaying generating syllabus page for syllabus_id='{syllabus_id}'")
    # This view is synchronous, so direct DB access is okay here.
    # Use select_related to potentially optimize if user is accessed in template.
    syllabus = get_object_or_404(Syllabus.objects.select_related('user'), syllabus_id=syllabus_id)

    # Ensure the user requesting the page is the owner of the syllabus
    # @login_required ensures request.user is authenticated User
    if syllabus.user != request.user:
        # Ensure syllabus.user is not None before accessing pk
        owner_pk = cast(User, syllabus.user).pk if syllabus.user else "Unknown"  # type: ignore[attr-defined]
        logger.warning(
            f"User {request.user.pk} attempted to access generating page for syllabus {syllabus_id} owned by {owner_pk}"
        )
        messages.error(
            request,
            "You do not have permission to view this syllabus generation status.",
        )
        return redirect(reverse("dashboard"))

    try:
        # Generate the polling URL using the syllabus_id
        poll_url = reverse("onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus_id})
    except NoReverseMatch:
        logger.error(
            f"Could not reverse URL for poll_syllabus_status with syllabus_id={syllabus_id}"
        )
        messages.error(request, "Could not prepare syllabus generation status check.")
        return redirect(reverse("dashboard"))

    context = {
        "syllabus": syllabus,  # Pass the whole syllabus object
        "poll_url": poll_url,
        "csrf_token": request.META.get(
            "CSRF_COOKIE"
        ),  # Pass CSRF token if needed by JS
    }
    return render(request, "onboarding/generating_syllabus.html", context)


# @login_required # Cannot use decorator with async view, check manually
@require_GET  # Or POST if CSRF protection is strictly needed for polling
def poll_syllabus_status_view(
    request: HttpRequest, syllabus_id: uuid.UUID
) -> JsonResponse:
    """Poll endpoint to check the status of syllabus generation using its ID."""
    user = request.user
    if not user.is_authenticated:
        logger.warning(
            "Unauthenticated user attempted to poll syllabus status."
        )
        return JsonResponse(
            {"status": "error", "message": "Authentication required."}, status=401
        )

    syllabus = get_object_or_404(
        Syllabus.objects.select_related('user'),
        syllabus_id=syllabus_id
    )

    if syllabus.user != user:
        owner_pk = syllabus.user.pk if syllabus.user else "Unknown"
        logger.warning(
            f"User {user.pk} attempted to poll status for syllabus {syllabus_id} owned by {owner_pk}"
        )
        return JsonResponse(
            {"status": "error", "message": "Permission denied."}, status=403
        )

    logger.info(
        f"Syllabus {syllabus_id} status for user {user.pk}: {syllabus.status}"
    )

    response_data = {"status": syllabus.status}

    if syllabus.status == Syllabus.StatusChoices.COMPLETED.value:
        try:
            syllabus_url = reverse("syllabus:detail", args=[syllabus.pk])
            response_data["syllabus_url"] = syllabus_url
            logger.info(
                f"Syllabus {syllabus_id} completed. Providing URL: {syllabus_url}"
            )
        except NoReverseMatch:
            logger.error(
                f"Could not reverse syllabus detail URL for ID {syllabus.pk}"
            )
            response_data["message"] = "Syllabus ready but URL generation failed."
    elif syllabus.status == Syllabus.StatusChoices.FAILED.value:
        logger.warning(f"Syllabus {syllabus_id} generation failed.")
        response_data["message"] = "Syllabus generation failed."

    return JsonResponse(response_data)
