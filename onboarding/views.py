"""Views for the onboarding app."""

import json  # Import json module
import logging
import uuid
from typing import Any, Dict, Optional, cast

from django.contrib import messages  # Add messages framework
from django.contrib.auth.decorators import login_required  # Add login_required
from django.contrib.auth.models import User  # Import User directly
from django.db import transaction  # Import transaction
from django.http import (HttpRequest, HttpResponse, HttpResponseBadRequest,
                         JsonResponse)
from django.shortcuts import (  # Add redirect, get_object_or_404
    get_object_or_404, redirect, render)
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET, require_POST

# Import difficulty constants
from core.constants import (DIFFICULTY_BEGINNER, DIFFICULTY_FROM_VALUE,
                            DIFFICULTY_LEVELS)
# Import Syllabus Service and Exceptions
# Import the model for saving results
from core.models import Syllabus  # Import Syllabus model from core app
from core.models import UserAssessment
from onboarding.logic import get_ai_instance
from syllabus.services import SyllabusService
from taskqueue.models import AITask  # Import AITask
from taskqueue.tasks import process_ai_task  # Import process_ai_task

# Import AI logic and state definition
from .ai import AgentState

logger = logging.getLogger(__name__)

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
        logger.debug(
            "After get_ai_instance and initialize_state, before perform_internet_search"
        )

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
        difficulty_name = DIFFICULTY_FROM_VALUE.get(
            difficulty_value, DIFFICULTY_BEGINNER
        )
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
        return JsonResponse(
            {"error": "Invalid assessment state found. Please restart."}, status=400
        )

    # If assessment_state is provided in the request body, use it instead
    try:
        data = json.loads(request.body)
        if "assessment_state" in data and data["assessment_state"]:
            assessment_state = data["assessment_state"]
    except Exception:
        pass

    if assessment_state.get("is_complete", False):
        return JsonResponse(
            {
                "is_complete": True,
                "knowledge_level": assessment_state.get("knowledge_level"),
                "score": assessment_state.get("score"),
                "feedback": "Assessment already completed.",
            }
        )

    try:
        data = json.loads(request.body)
        answer = data.get("answer")
        is_skip = data.get("skip", False) is True
        if not answer and not is_skip:
            return JsonResponse(
                {"error": "Missing 'answer' or 'skip' flag in JSON payload."},
                status=400,
            )
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    # Save updated state back to session immediately
    request.session["assessment_state"] = assessment_state

    user_obj = request.user if request.user.is_authenticated else None

    # Enqueue background task for answer evaluation and next question generation
    # pylint: disable=no-member
    task = AITask.objects.create(
        task_type=AITask.TaskType.ONBOARDING_ASSESSMENT,
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

    return JsonResponse(
        {
            "status": "processing",
            "task_id": str(task.task_id),
            "wait_url": f"/api/tasks/status/{task.task_id}/",
            "message": "Processing your answer and generating next question.",
        }
    )


def dict_to_agent_state(d: dict) -> AgentState:
    """Helper to coerce a dict to AgentState TypedDict."""
    return cast(AgentState, d)


def finalize_assessment_and_trigger_syllabus_task(request, user, assessment_state):
    """Finalize assessment, save result, and create syllabus generation task."""
    topic = assessment_state.get("topic")
    level = assessment_state.get("knowledge_level")

    # Clear assessment state from session

    del request.session["assessment_state"]

    if not topic or not level or not user.is_authenticated:
        return {"error": "Missing topic, level, or user not authenticated."}

    # Create or get background task
    # pylint: disable=no-member
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
        process_ai_task(str(task.task_id))
        feedback_msg = "Assessment complete. Syllabus generation started..."
    else:
        feedback_msg = (
            "Assessment complete. Syllabus generation is already in progress..."
        )

    try:
        wait_url = reverse(
            "onboarding:wait_for_syllabus", kwargs={"task_id": task.task_id}
        )
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
    # This view just renders the template,
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


# --- Syllabus Initiation and Generation Views ---


@login_required
@require_POST
def initiate_syllabus_view(request: HttpRequest) -> JsonResponse:
    """
    Initiates syllabus generation after assessment completion.

    Checks for existing template syllabi, copies if found, otherwise
    creates a pending syllabus and triggers a background task.
    Returns a JSON response with a URL to redirect the user to.
    """
    user = cast(User, request.user)
    try:
        data = json.loads(request.body)
        topic = data.get("topic")
        level = data.get("level")

        if not topic or not level:
            logger.warning(
                f"Missing topic or level in initiate_syllabus request for user {user.pk}"
            )
            return JsonResponse(
                {"error": "Missing 'topic' or 'level' in request."}, status=400
            )

        logger.info(
            f"Initiating syllabus for user {user.pk}, topic='{topic}', level='{level}'"
        )

        # Clear assessment state from session if it exists
        if "assessment_state" in request.session:
            del request.session["assessment_state"]
            logger.debug(f"Cleared assessment_state from session for user {user.pk}")

        redirect_url = None
        with transaction.atomic():
            # 1. Check if user already has an active syllabus for this topic/level
            existing_user_syllabus = Syllabus.objects.filter(
                user=user,
                topic=topic,
                level=level,
                status__in=[
                    Syllabus.StatusChoices.PENDING,
                    Syllabus.StatusChoices.GENERATING,
                    Syllabus.StatusChoices.COMPLETED,
                ],
            ).first()

            if existing_user_syllabus:
                logger.info(
                    f"User {user.pk} already has syllabus {existing_user_syllabus.syllabus_id} for topic='{topic}', "
                    f"level='{level}'. Status: {existing_user_syllabus.status}"
                )
                if existing_user_syllabus.status == Syllabus.StatusChoices.COMPLETED:
                    redirect_url = reverse(
                        "syllabus:detail", args=[existing_user_syllabus.pk]
                    )
                else:  # Pending or Processing
                    redirect_url = reverse(
                        "onboarding:generating_syllabus",
                        kwargs={"syllabus_id": existing_user_syllabus.syllabus_id},
                    )
                return JsonResponse({"redirect_url": redirect_url})

            # 2. Check for a template syllabus (user=None) for this topic/level
            template_syllabus = Syllabus.objects.filter(
                user=None,
                topic=topic,
                level=level,
                status=Syllabus.StatusChoices.COMPLETED,  # Only copy completed templates
            ).first()

            if template_syllabus:
                # 3a. Copy template syllabus
                logger.info(
                    f"Found template syllabus {template_syllabus.syllabus_id} for topic='{topic}', "
                    f"level='{level}'. Copying for user {user.pk}."
                )
                new_syllabus = Syllabus.objects.create(
                    user=user,
                    topic=template_syllabus.topic,
                    level=template_syllabus.level,
                    user_entered_topic=template_syllabus.user_entered_topic,
                    status=Syllabus.StatusChoices.COMPLETED,  # Mark as completed immediately
                )
                logger.info(
                    f"Created syllabus {new_syllabus.syllabus_id} for user {user.pk} by copying template."
                )
                redirect_url = reverse("syllabus:detail", args=[new_syllabus.pk])

            else:
                # 3b. Create new pending syllabus and trigger generation task
                logger.info(
                    f"No template syllabus found for topic='{topic}', level='{level}'. "
                    f"Creating new pending syllabus for user {user.pk}."
                )
                new_syllabus = Syllabus.objects.create(
                    user=user,
                    topic=topic,
                    level=level,
                    status=Syllabus.StatusChoices.PENDING,
                )
                logger.info(
                    f"Created pending syllabus {new_syllabus.syllabus_id} for user {user.pk}."
                )

                # Create and enqueue the background task
                # pylint: disable=no-member
                task = AITask.objects.create(
                    user=user,
                    task_type=AITask.TaskType.SYLLABUS_GENERATION,
                    input_data={
                        "topic": topic,
                        "level": level,
                        "knowledge_level": level,
                        "user_id": user.pk,
                        "syllabus_id": str(
                            new_syllabus.syllabus_id
                        ),  # Pass syllabus ID to task
                    },
                )
                process_ai_task(str(task.task_id))
                logger.info(
                    f"Enqueued SYLLABUS_GENERATION task {task.task_id} for syllabus {new_syllabus.syllabus_id}."
                )
                redirect_url = reverse(
                    "onboarding:generating_syllabus",
                    kwargs={"syllabus_id": new_syllabus.syllabus_id},
                )

        return JsonResponse({"redirect_url": redirect_url})

    except json.JSONDecodeError:
        logger.error(
            f"Invalid JSON received in initiate_syllabus request for user {user.pk}"
        )
        return JsonResponse({"error": "Invalid JSON format."}, status=400)
    except NoReverseMatch as e:
        logger.error(
            f"Could not reverse URL during syllabus initiation for user {user.pk}: {e}",
            exc_info=True,
        )
        return JsonResponse({"error": "Failed to generate redirect URL."}, status=500)
    except Exception as e:
        logger.error(
            f"Error initiating syllabus for user {user.pk}: {e}", exc_info=True
        )
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


@login_required
@require_GET
def generating_syllabus_view(
    request: HttpRequest, syllabus_id: uuid.UUID
) -> HttpResponse:
    """Renders the page indicating syllabus generation is in progress."""
    logger.info(f"Displaying generating syllabus page for syllabus_id='{syllabus_id}'")
    # This view is synchronous, so direct DB access is okay here.
    # Use select_related to potentially optimize if user is accessed in template.
    syllabus = get_object_or_404(
        Syllabus.objects.select_related("user"), syllabus_id=syllabus_id
    )

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
        poll_url = reverse(
            "onboarding:poll_syllabus_status", kwargs={"syllabus_id": syllabus_id}
        )
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


@login_required
@require_GET  # Or POST if CSRF protection is strictly needed for polling
def poll_syllabus_status_view(
    request: HttpRequest, syllabus_id: uuid.UUID
) -> JsonResponse:
    """Poll endpoint to check the status of syllabus generation using its ID."""
    user = request.user
    if not user.is_authenticated:
        logger.warning("Unauthenticated user attempted to poll syllabus status.")
        return JsonResponse(
            {"status": "error", "message": "Authentication required."}, status=401
        )

    syllabus = get_object_or_404(
        Syllabus.objects.select_related("user"), syllabus_id=syllabus_id
    )

    if syllabus.user != user:
        owner_pk = cast(User, syllabus.user).pk if syllabus.user else "Unknown"  # type: ignore[attr-defined]
        logger.warning(
            f"User {user.pk} attempted to poll status for syllabus {syllabus_id} owned by {owner_pk}"
        )
        return JsonResponse(
            {"status": "error", "message": "Permission denied."}, status=403
        )

    logger.info(f"Syllabus {syllabus_id} status for user {user.pk}: {syllabus.status}")

    response_data = {"status": syllabus.status}

    if syllabus.status == Syllabus.StatusChoices.COMPLETED.value:
        try:
            syllabus_url = reverse("syllabus:detail", args=[syllabus.pk])
            response_data["syllabus_url"] = syllabus_url
            logger.info(
                f"Syllabus {syllabus_id} completed. Providing URL: {syllabus_url}"
            )
        except NoReverseMatch:
            logger.error(f"Could not reverse syllabus detail URL for ID {syllabus.pk}")
            response_data["message"] = "Syllabus ready but URL generation failed."
    elif syllabus.status == Syllabus.StatusChoices.FAILED.value:
        logger.warning(f"Syllabus {syllabus_id} generation failed.")
        response_data["message"] = "Syllabus generation failed."

    return JsonResponse(response_data)
