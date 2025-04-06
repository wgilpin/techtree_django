"""Views for the onboarding app."""

import json  # Import json module
import logging
from typing import Optional, cast

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages  # Add messages framework
from django.contrib.auth.decorators import login_required  # Add login_required
from django.contrib.auth.models import User  # Import User for type casting
from django.http import (HttpRequest, HttpResponse, HttpResponseBadRequest,
                         JsonResponse)
from django.shortcuts import redirect, render  # Add redirect
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET, require_POST

from core.exceptions import ApplicationError
# Import the model for saving results
from core.models import UserAssessment
# Import Syllabus Service and Exceptions
from syllabus.services import SyllabusService

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
async def start_assessment_view(request: HttpRequest, topic: str) -> JsonResponse:
    """Start a new onboarding assessment for a given topic. (Async)"""
    logger.info(f"Async starting assessment view for topic: {topic}")
    user = await request.auser()  # Use auser() for async user fetch
    user_id: Optional[int] = None
    if user.is_authenticated:
        user_id = user.pk

    try:
        ai_instance = get_ai_instance()
        assessment_state = ai_instance.initialize_state(topic)
        assessment_state["user_id"] = user_id

        search_results = await ai_instance.perform_internet_search(assessment_state)
        assessment_state["wikipedia_content"] = search_results.get(
            "wikipedia_content", ""
        )
        assessment_state["google_results"] = search_results.get("google_results", [])
        assessment_state["search_completed"] = search_results.get(
            "search_completed", False
        )

        question_results = await ai_instance.generate_question(assessment_state)
        assessment_state["current_question"] = question_results.get(
            "current_question", "Error"
        )
        assessment_state["current_question_difficulty"] = question_results.get(
            "current_question_difficulty",
            settings.ONBOARDING_DEFAULT_DIFFICULTY,  # Use setting
        )
        assessment_state["questions_asked"] = question_results.get(
            "questions_asked", []
        )
        assessment_state["question_difficulties"] = question_results.get(
            "question_difficulties", []
        )

        # Save initial state to session asynchronously
        await set_session_value(request.session, "assessment_state", assessment_state)
        logger.info(
            f"Assessment state initialized in session for user: {user_id}, topic: {topic}"
        )

        return JsonResponse(
            {
                "search_status": assessment_state.get("search_completed", False),
                "question": assessment_state.get("current_question"),
                "difficulty": assessment_state.get("current_question_difficulty"),
                "is_complete": False,
            }
        )

    except Exception as e:
        logger.error(f"Error starting assessment: {str(e)}", exc_info=True)
        # Clear session key asynchronously
        await del_session_key(request.session, "assessment_state")
        return JsonResponse(
            {"error": f"Failed to start assessment: {str(e)}"}, status=500
        )


# @require_POST # Removed decorator - body access happens below
async def submit_answer_view(
    request: HttpRequest,
) -> HttpResponse:  # Change return type hint
    """Process a user's submitted answer during an assessment. (Async)"""
    logger.info("Async submit answer view called.")

    # Get session data asynchronously
    assessment_state_data = await get_session_value(request.session, "assessment_state")
    if assessment_state_data is None:
        return JsonResponse({"error": "No active assessment found."}, status=400)

    try:
        assessment_state: AgentState = cast(AgentState, assessment_state_data)
    except (TypeError, KeyError):
        logger.error("Session data does not match expected AgentState structure.")
        await del_session_key(
            request.session, "assessment_state"
        )  # Clear invalid state
        return JsonResponse(
            {"error": "Invalid assessment state found. Please restart."}, status=400
        )

    if assessment_state.get("is_complete", False):
        logger.warning("Attempt to submit answer to completed assessment.")
        return JsonResponse(
            {
                "is_complete": True,
                "knowledge_level": assessment_state.get("knowledge_level"),
                "score": assessment_state.get("score"),
                "feedback": "Assessment already completed.",
            }
        )

    # Parse JSON body instead of POST form data
    try:
        data = json.loads(request.body)
        answer = data.get("answer")
        if not answer:
            return JsonResponse(
                {"error": "Missing answer in JSON payload."}, status=400
            )
    except json.JSONDecodeError:
        logger.warning("Received invalid JSON in submit_answer request.")
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    logger.info(f"Received answer: {answer[:100]}...")

    try:
        ai_instance = get_ai_instance()

        # Pass a copy of the state to evaluate_answer to avoid in-place modification issues
        eval_results = await ai_instance.evaluate_answer(
            assessment_state.copy(), answer
        )
        assessment_state["answers"] = eval_results.get(
            "answers", assessment_state["answers"]
        )
        assessment_state["answer_evaluations"] = eval_results.get(
            "answer_evaluations", assessment_state["answer_evaluations"]
        )
        # Update state with results from evaluate_answer (using new/updated keys)
        assessment_state["consecutive_wrong_at_current_difficulty"] = eval_results.get(
            "consecutive_wrong_at_current_difficulty",
            assessment_state.get("consecutive_wrong_at_current_difficulty", 0),
        )
        assessment_state["current_target_difficulty"] = eval_results.get(
            "current_target_difficulty",
            assessment_state.get(
                "current_target_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
            ),
        )
        # Note: consecutive_hard_correct_or_partial is also updated in eval_results now
        assessment_state["consecutive_hard_correct_or_partial"] = eval_results.get(
            "consecutive_hard_correct_or_partial",
            assessment_state["consecutive_hard_correct_or_partial"],
        )
        assessment_state["feedback"] = eval_results.get("feedback")

        # Pass a copy to should_continue to check the state *after* evaluation updates
        should_continue = ai_instance.should_continue(assessment_state.copy())

        if should_continue:
            # Pass a copy of the state to generate_question
            question_results = await ai_instance.generate_question(
                assessment_state.copy()
            )
            # Manually update assessment_state keys for type safety
            assessment_state["current_question"] = question_results.get(
                "current_question", "Error"
            )
            assessment_state["current_question_difficulty"] = question_results.get(
                "current_question_difficulty", settings.ONBOARDING_DEFAULT_DIFFICULTY
            )
            assessment_state["questions_asked"] = question_results.get(
                "questions_asked", assessment_state.get("questions_asked", [])
            )
            assessment_state["question_difficulties"] = question_results.get(
                "question_difficulties",
                assessment_state.get("question_difficulties", []),
            )
            # Update step if returned by generate_question
            if "step" in question_results:
                assessment_state["step"] = question_results["step"]

            # Save updated state back to session asynchronously
            await set_session_value(
                request.session, "assessment_state", assessment_state
            )

            response_data = {
                "is_complete": False,
                "question": assessment_state.get("current_question"),
                "difficulty": assessment_state.get("current_question_difficulty"),
                # Explicitly handle None feedback
                "feedback": assessment_state.get("feedback") or "",
            }
            return JsonResponse(response_data)
        else:  # Assessment is complete
            logger.info(
                "Assessment determined to be complete. Calculating final results."
            )  # Added log
            # Calculate final assessment results
            final_state = ai_instance.calculate_final_assessment(
                assessment_state.copy()
            )
            final_assessment_data = final_state.get("final_assessment", {})
            assessment_state["knowledge_level"] = final_assessment_data.get(
                "knowledge_level", "Unknown"
            )
            assessment_state["score"] = final_assessment_data.get("overall_score")
            assessment_state["is_complete"] = final_state.get("is_complete", True)
            assessment_state["final_assessment"] = final_assessment_data

            logger.info(
                f"Assessment complete. Level: {assessment_state['knowledge_level']}, Score: {assessment_state['score']}"
            )

            user = await request.auser()
            user_id = assessment_state.get("user_id")

            # Attempt to save the assessment result (optional, proceed even if fails)
            if user_id and user.is_authenticated and user.pk == user_id:
                logger.info(f"Attempting to save assessment for user ID: {user_id}")
                try:
                    await create_user_assessment(
                        user=user,
                        topic=assessment_state.get("topic", "Unknown Topic"),
                        knowledge_level=assessment_state.get(
                            "knowledge_level", "Unknown"
                        ),
                        score=assessment_state.get("score", 0.0),
                        question_history=assessment_state.get("questions_asked", []),
                        response_history=assessment_state.get("answers", []),
                    )
                    logger.info("Assessment saved to DB.")
                except Exception as db_err:
                    logger.error(f"Failed to save assessment: {db_err}", exc_info=True)
            else:
                logger.warning(
                    "Assessment completed but not saved. User ID mismatch or missing. "
                    f"Session User ID: {user_id}, Request User PK: {user.pk if user.is_authenticated else None}"
                )

            # --- NEW: Trigger Syllabus Generation ---
            topic = assessment_state.get("topic")
            level = assessment_state.get("knowledge_level")
            logger.info(
                f"Preparing for syllabus generation. Topic: {topic}, Level: {level}"
            )  # Added log

            # Clear assessment state from session *before* potentially long syllabus generation
            await del_session_key(request.session, "assessment_state")
            logger.info("Assessment state cleared from session.")

            if not topic or not level:
                logger.error(
                    "Cannot generate syllabus: Topic or Level missing from final assessment state. "
                    "Redirecting to dashboard."
                )  # Added log
                messages.error(
                    request,
                    "Assessment complete, but failed to determine topic or level for syllabus generation.",
                )
                return redirect(reverse("dashboard"))  # Redirect to dashboard on error

            if not user.is_authenticated:
                logger.error(
                    "Cannot generate syllabus: User is not authenticated. Redirecting to login."
                )  # Added log
                messages.error(
                    request,
                    "Assessment complete, but you must be logged in to generate a syllabus.",
                )
                return redirect(reverse("login"))  # Redirect to login

            try:
                logger.info(
                    f"Requesting syllabus generation for user {user.pk}: Topic='{topic}', Level='{level}'"
                )
                # Call the async service method directly
                syllabus_data = await syllabus_service.get_or_generate_syllabus(
                    topic=topic, level=level, user=user
                )
                syllabus_id = syllabus_data.get("syllabus_id")
                logger.info(f"Syllabus service returned: {syllabus_data}")  # Added log

                if syllabus_id:
                    logger.info(
                        f"Syllabus generated/found (ID: {syllabus_id}). Returning JSON with redirect URL."
                    )  # Updated log
                    messages.success(
                        request,
                        f"Assessment complete! Your syllabus for '{topic}' ({level}) is ready.",
                    )  # Keep the message for next page load
                    syllabus_url = reverse("syllabus:detail", args=[syllabus_id])
                    # Return JSON instead of redirecting directly
                    return JsonResponse(
                        {
                            "is_complete": True,
                            "knowledge_level": assessment_state.get("knowledge_level"),
                            "score": assessment_state.get("score"),
                            "syllabus_url": syllabus_url,  # Provide URL for frontend redirect
                            "feedback": "Assessment complete. Syllabus generated.",  # Optional feedback
                        }
                    )
                else:
                    logger.error(
                        "Syllabus generation/retrieval finished but no syllabus_id returned. Redirecting to dashboard."
                    )  # Added log
                    messages.error(
                        request,
                        "Assessment complete, but there was an issue retrieving your syllabus.",
                    )
                    return redirect(reverse("dashboard"))

            except ApplicationError as e:
                logger.error(
                    f"Syllabus generation failed (ApplicationError) for user {user.pk}: "
                    f"{e}. Redirecting to dashboard.",
                    exc_info=True,
                )  # Added log
                messages.error(
                    request, f"Assessment complete, but syllabus generation failed: {e}"
                )
                return redirect(reverse("dashboard"))
            except Exception as e:  # Catch any other unexpected errors
                logger.exception(
                    "Unexpected error during syllabus generation call for user "
                    f"{user.pk}: {e}. Redirecting to dashboard."
                )  # Added log
                messages.error(
                    request,
                    "An unexpected error occurred after completing the assessment.",
                )
                return redirect(reverse("dashboard"))
            # --- End NEW ---

    except Exception as e:
        logger.error(f"Error submitting answer: {str(e)}", exc_info=True)
        # Ensure state is cleared on general error too
        await del_session_key(request.session, "assessment_state")
        # Return JSON error for frontend handling if it's not a completion redirect
        return JsonResponse(
            {"error": f"Failed to process answer: {str(e)}"}, status=500
        )


@require_GET
def assessment_page_view(request: HttpRequest, topic: str) -> HttpResponse:
    """
    Renders the main assessment page, passing the topic and start URL. (Sync)
    """
    # This view just renders the template, no async operations needed here
    try:
        start_url = reverse("onboarding_start", kwargs={"topic": topic})
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
    and sets the knowledge level to 'beginner'. Redirects to the dashboard.
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
            knowledge_level="beginner",
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
