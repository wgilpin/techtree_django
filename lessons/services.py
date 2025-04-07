"""
Service layer for the lessons app.

This module will contain the business logic for fetching lesson content,
handling user interactions, managing progress, and coordinating with AI components.
It adapts logic originally found in lesson_exposition_service.py and
lesson_interaction_service.py from the Flask version.
"""

# pylint: disable=no-member

import json
import re
import logging
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone  # Use Django's timezone utilities
from langchain_google_genai import ChatGoogleGenerativeAI
from google.api_core.exceptions import GoogleAPIError

# Import necessary models - ensure UserProgress and ConversationHistory are included
from core.models import (
    Lesson,
    LessonContent,
    Module,
    Syllabus,
    UserProgress,
    ConversationHistory,
)
from core.constants import DIFFICULTY_VALUES
from syllabus.ai.utils import call_with_retry  # Re-use retry logic
from .ai.prompts import GENERATE_LESSON_CONTENT_PROMPT, LATEX_FORMATTING_INSTRUCTIONS
from .ai.lesson_graph import LessonInteractionGraph  # Import the graph
from .ai.state import LessonState  # Import the state definition

# For type checking ForeignKey relations to Django's User model
if TYPE_CHECKING:
    from django.contrib.auth.models import User  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def _get_llm() -> Optional[ChatGoogleGenerativeAI]:
    """Initializes and returns the LangChain LLM model based on settings."""
    api_key = settings.GEMINI_API_KEY
    # Use the LARGE_MODEL for content generation as per original logic indication
    model_name = settings.LARGE_MODEL

    if not api_key:
        logger.error("GEMINI_API_KEY not found in settings.")
        return None
    if not model_name:
        logger.error("LARGE_MODEL not found in settings.")
        return None

    try:
        # Adjust temperature/top_p as needed for generation tasks
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.7,  # Adjust as needed
            convert_system_message_to_human=True,  # Often needed for Gemini
        )  # type: ignore[call-arg]
    except Exception as e:
        logger.error(
            "Failed to initialize ChatGoogleGenerativeAI: %s", e, exc_info=True
        )
        return None


def _fetch_syllabus_structure(syllabus: Syllabus) -> List[Dict[str, Any]]:
    """Fetches and formats the syllabus structure for the prompt."""
    structure = []
    # Use prefetch_related for efficiency if called frequently or for large syllabi
    modules = syllabus.modules.prefetch_related("lessons").order_by("module_index")  # type: ignore[attr-defined]
    for module in modules:
        module_data = {
            "module_index": module.module_index,
            "title": module.title,
            "summary": module.summary,
            "lessons": [
                {
                    "lesson_index": lesson.lesson_index,
                    "title": lesson.title,
                    "summary": lesson.summary,
                    "duration": lesson.duration,
                }
                for lesson in module.lessons.order_by("lesson_index")
            ],
        }
        structure.append(module_data)
    return structure


# Add functions here to handle:
# - Fetching formatted lesson content for display
# - Processing user chat messages
# - Handling exercise submissions
# - Updating user progress and state
# - Calling the AI graph for responses/content generation


def get_or_create_lesson_content(lesson: Lesson) -> Optional[LessonContent]:
    """
    Retrieves the LessonContent for a given Lesson, generating it if necessary.

    Args:
        lesson: The Lesson object for which to get content.

    Returns:
        The existing or newly created LessonContent object, or None if generation fails.
    """
    existing_content = LessonContent.objects.filter(lesson=lesson).first()

    if existing_content:
        logger.info("Found existing content for Lesson ID: %s", lesson.pk)
        return existing_content
    else:
        logger.info(
            "No existing content found for Lesson ID: %s (%s). Generating...",
            lesson.pk,
            lesson.title,
        )
        try:
            # 1. Gather context
            module = lesson.module
            syllabus = module.syllabus  # type: ignore[attr-defined]
            topic = syllabus.topic
            level = syllabus.level
            lesson_title = lesson.title
            syllabus_structure = _fetch_syllabus_structure(syllabus)
            # Ensure syllabus_structure is serializable before dumping
            try:
                syllabus_structure_json = json.dumps(syllabus_structure, indent=2)
            except TypeError as json_err:
                logger.error(
                    "Failed to serialize syllabus structure: %s",
                    json_err,
                    exc_info=True,
                )
                return None  # Cannot proceed without serializable structure

            # 2. Initialize LLM
            llm = _get_llm()
            if not llm:
                logger.error("LLM could not be initialized. Cannot generate content.")
                return None
            logger.info("LLM initialized successfully.")

            # 3. Format Prompt
            # Calculate target word count based on difficulty level
            difficulty_value = DIFFICULTY_VALUES.get(level)
            if difficulty_value is None:
                logger.warning(
                    "Difficulty level '%s' not found in DIFFICULTY_VALUES. Using default word count.",
                    level
                )
                # Default to ~400 words (similar to Early Learner) if level is unknown
                word_count = 400
            else:
                word_count = (difficulty_value + 1) * 200

            prompt_input = {
                "topic": topic,
                "level_name": level, # Use the original level value as the name
                "word_count": word_count,
                "lesson_title": lesson_title,
                "syllabus_structure_json": syllabus_structure_json,
                "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
            }
            formatted_prompt = GENERATE_LESSON_CONTENT_PROMPT.format(**prompt_input)

            # 4. Call LLM with retry
            logger.info("Calling LLM to generate content for lesson %s...", lesson.pk)
            try:
                response = call_with_retry(llm.invoke, formatted_prompt)
                # Ensure response content is a string before stripping
                generated_text = (
                    str(response.content).strip()
                    if hasattr(response, "content")
                    else ""
                )
            except Exception as llm_err:
                logger.error(
                    "LLM invocation failed for lesson %s: %s",
                    lesson.pk,
                    llm_err,
                    exc_info=True,
                )
                return None

            if not generated_text:
                logger.warning("LLM returned empty content for lesson %s.", lesson.pk)
                return None

            logger.debug(
                "LLM call successful for lesson %s. Content length: %d",
                lesson.pk,
                len(generated_text),
            )

            # 5. Create and save LessonContent object atomically
            with transaction.atomic():
                # Attempt to parse the generated text as JSON
                try:
                    # Clean potential markdown code fences using removeprefix/removesuffix
                    cleaned_text = generated_text
                    if cleaned_text.startswith("```json"):
                        cleaned_text = (
                            cleaned_text.removeprefix("```json")
                            .removesuffix("```")
                            .strip()
                        )
                    elif cleaned_text.startswith("```"):
                        cleaned_text = (
                            cleaned_text.removeprefix("```").removesuffix("```").strip()
                        )

                    # Escape backslashes that are not part of valid JSON escapes
                    # This specifically targets single backslashes followed by characters
                    # --- Use Regex to Extract Exposition Content ---
                    # Avoids parsing potentially invalid JSON from LLM.
                    # Assumes "exposition" is the primary key and its value is a string.
                    # Use non-greedy match and look for comma or closing brace after value.
                    # --- Use JSON Parsing to Extract Exposition Content ---
                    exposition_content = ""  # Default value
                    try:
                        # First try to parse as JSON
                        parsed_data = json.loads(cleaned_text)
                        if isinstance(parsed_data, dict):
                            exposition_content = parsed_data.get("exposition", "")
                            # Ensure content_data is always defined within the scope
                            content_data = {"exposition": exposition_content}
                            logger.info(
                                "Successfully extracted exposition content via JSON parsing for lesson %s.",
                                lesson.pk,
                            )
                        else:
                            # Handle cases where the parsed data is not a dictionary
                            logger.warning(
                                "LLM output parsed as JSON but is not a dictionary for lesson %s. Raw: %s",
                                lesson.pk,
                                cleaned_text,
                            )
                            content_data = {
                                "error": "LLM output parsed but not a dictionary.",
                                "raw_response": cleaned_text,
                            }

                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to parse LLM output as JSON for lesson %s. Raw Content: %s",
                            lesson.pk,
                            cleaned_text,
                        )
                        
                        # Try to extract exposition content using regex if it looks like JSON
                        # This handles cases where LaTeX commands cause JSON parsing to fail
                        exposition_match = re.search(r'"exposition"\s*:\s*"(.*?)"\s*}', cleaned_text, re.DOTALL)
                        if exposition_match:
                            exposition_content = exposition_match.group(1)
                            # Unescape any escaped quotes within the content
                            exposition_content = exposition_content.replace('\\"', '"')
                            content_data = {"exposition": exposition_content}
                            logger.info(
                                "Successfully extracted exposition content via regex for lesson %s.",
                                lesson.pk,
                            )
                        else:
                            # Fallback if regex extraction fails
                            content_data = {
                                "error": "Failed to parse LLM output as JSON.",
                                "raw_response": cleaned_text,
                            }
                            logger.info(
                                "Storing error structure due to JSON parsing failure for lesson %s.",
                                lesson.pk,
                            )
                except Exception as e:  # Add a general except block
                    logger.error(
                        "Error processing LLM response (regex/dict creation) for lesson %s: %s",
                        lesson.pk,
                        e,
                        exc_info=True,
                    )
                    content_data = {
                        "error": "Failed to process LLM response after generation.",
                        "raw_response": generated_text,  # Use generated_text as it's guaranteed to exist
                    }
                    logger.info(
                        "Storing error structure due to post-generation processing error for lesson %s.",
                        lesson.pk,
                    )

                new_content = LessonContent.objects.create(
                    lesson=lesson,
                    content=content_data,  # Use the parsed (or fallback) data
                )
                logger.info(
                    "Successfully created and saved LessonContent (ID: %s) for Lesson ID: %s",
                    new_content.pk,
                    lesson.pk,
                )
                return new_content

        except GoogleAPIError as e:
            logger.error(
                "Google API error during LLM call for lesson %s: %s",
                lesson.pk,
                e,
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to generate or save lesson content for Lesson ID %s: %s",
                lesson.pk,
                e,
                exc_info=True,
            )
            return None


def _initialize_lesson_state(
    user: "User", lesson: Lesson, lesson_content: LessonContent
) -> Dict[str, Any]:
    """
    Creates the initial state dictionary for a user starting a lesson.

    Args:
        user: The user starting the lesson.
        lesson: The Lesson object.
        lesson_content: The generated LessonContent object.

    Returns:
        A dictionary representing the initial lesson state.
    """
    module = lesson.module
    assert isinstance(module, Module)  # Help mypy with type inference
    syllabus = module.syllabus  # type: ignore[attr-defined]
    assert isinstance(syllabus, Syllabus)  # Help mypy with type inference
    now_iso = django_timezone.now().isoformat()  # Use Django's timezone

    # Extract exposition safely from content JSON
    exposition_text = ""
    if isinstance(lesson_content.content, dict):
        exposition_text = lesson_content.content.get("exposition", "")
    elif isinstance(
        lesson_content.content, str
    ):  # Handle case where content might be just a string
        exposition_text = lesson_content.content

    # Basic initial state structure, mirroring the original service where possible
    # We might skip the AI call for the initial welcome message for now to simplify
    initial_state = {
        "topic": syllabus.topic,  # Keep 'topic' as is, seems used correctly elsewhere
        "user_knowledge_level": syllabus.level,  # Align with node expectation
        "lesson_title": lesson.title,
        "module_title": module.title,  # Correctly access title from module
        # Convert syllabus.pk to string
        "lesson_uid": f"{str(syllabus.pk)}_{module.module_index}_{lesson.lesson_index}",
        "user_id": str(user.pk),  # Store user ID as string
        "lesson_db_id": lesson.pk,  # lesson.pk is likely an int, which is fine
        "content_db_id": str(
            lesson_content.pk
        ),  # Convert content_db_id (UUID) to string
        "created_at": now_iso,
        "updated_at": now_iso,
        "current_interaction_mode": "chatting",  # Default mode
        "current_exercise_index": None,
        "current_quiz_question_index": None,
        "generated_exercises": [],
        "generated_assessment_questions": [],
        "user_responses": [],  # History of user inputs/actions within the state
        "user_performance": {},  # Track performance metrics
        "error_message": None,
        "active_exercise": None,
        "active_assessment": None,
        # Add a placeholder for the initial system/welcome message if not calling AI yet
        # "initial_message": "Welcome to the lesson!"
        # Store the full exposition text, nodes will handle truncation if needed
        "lesson_exposition": exposition_text,  # Align with node expectation
    }
    logger.info(
        "Initialized state dictionary for lesson %s, user %s", lesson.pk, user.pk
    )
    return initial_state


def get_lesson_state_and_history(
    user: "User",
    syllabus: Syllabus,
    module: Module,
    lesson: Lesson,
) -> Tuple[Optional[UserProgress], Optional[LessonContent], List[ConversationHistory]]:
    """
    Fetches or initializes the user's progress state, lesson content, and conversation history.

    Args:
        user: The authenticated user.
        syllabus: The relevant Syllabus object.
        module: The relevant Module object.
        lesson: The relevant Lesson object.

    Returns:
        A tuple containing:
            - The UserProgress object (with potentially initialized state).
            - The LessonContent object (or None if fetch/generation fails).
            - A list of ConversationHistory messages for this progress record.
        Returns (None, None, []) if essential components like lesson content fail.
    """
    logger.info(
        "Fetching state/history for user %s, lesson %s (%s)",
        user.username,
        lesson.pk,
        lesson.title,
    )

    # 1. Get or Create Lesson Content (required for state initialization)
    lesson_content = get_or_create_lesson_content(lesson)
    if not lesson_content:
        logger.error(
            "Failed to get or create lesson content for lesson %s. Cannot proceed.",
            lesson.pk,
        )
        return None, None, []  # Cannot proceed without content

    # 2. Get or Create User Progress record
    progress, created = UserProgress.objects.get_or_create(
        user=user,
        syllabus=syllabus,
        lesson=lesson,
        defaults={
            "module_index": module.module_index,
            "lesson_index": lesson.lesson_index,
            "status": "not_started",  # Initial status
        },
    )

    conversation_history: List[ConversationHistory] = []
    lesson_state: Optional[Dict[str, Any]] = None

    if created:
        logger.info(
            "Created new UserProgress (ID: %s) for user %s, lesson %s.",
            progress.pk,
            user.username,
            lesson.pk,
        )
        # Initialize state only if progress was just created
        try:
            lesson_state = _initialize_lesson_state(user, lesson, lesson_content)
            progress.lesson_state_json = lesson_state  # Store initial state
            progress.status = "in_progress"  # Update status
            progress.save(update_fields=["lesson_state_json", "status", "updated_at"])
            logger.info(
                "Initialized and saved state for new UserProgress %s.", progress.pk
            )
            # Optionally, add the initial welcome message to history here if needed
            # ConversationHistory.objects.create(...)
        except Exception as e:
            logger.error(
                "Failed to initialize or save state for new UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )
            # Proceed without state, but log the error
            progress.lesson_state_json = {"error": "Initialization failed"}
            progress.save(update_fields=["lesson_state_json", "updated_at"])

    else:
        logger.info(
            "Found existing UserProgress (ID: %s) for user %s, lesson %s.",
            progress.pk,
            user.username,
            lesson.pk,
        )
        # Load existing state
        if isinstance(progress.lesson_state_json, dict):
            lesson_state = progress.lesson_state_json
            # Basic validation/update: ensure essential keys exist?
            if not lesson_state.get("lesson_db_id") == lesson.pk:
                logger.warning(
                    "State lesson ID (%s) mismatch for UserProgress %s. Updating.",
                    lesson_state.get("lesson_db_id"),
                    progress.pk,
                )
                lesson_state["lesson_db_id"] = lesson.pk
                lesson_state["updated_at"] = django_timezone.now().isoformat()
                progress.lesson_state_json = lesson_state  # Save corrected state
                progress.save(update_fields=["lesson_state_json", "updated_at"])

        elif progress.lesson_state_json is not None:
            logger.warning(
                "UserProgress %s has non-dict lesson_state_json (%s). Re-initializing.",
                progress.pk,
                type(progress.lesson_state_json),
            )
            # Re-initialize if state is corrupt/unexpected type
            try:
                lesson_state = _initialize_lesson_state(user, lesson, lesson_content)
                progress.lesson_state_json = lesson_state
                progress.save(update_fields=["lesson_state_json", "updated_at"])
            except Exception as e:
                logger.error(
                    "Failed to re-initialize state for UserProgress %s: %s",
                    progress.pk,
                    e,
                    exc_info=True,
                )
                progress.lesson_state_json = {"error": "Re-initialization failed"}
                progress.save(update_fields=["lesson_state_json", "updated_at"])
                lesson_state = None  # Indicate failure
        else:
            logger.warning(
                "UserProgress %s has NULL lesson_state_json. Initializing.", progress.pk
            )
            # Initialize if state is NULL
            try:
                lesson_state = _initialize_lesson_state(user, lesson, lesson_content)
                progress.lesson_state_json = lesson_state
                progress.save(update_fields=["lesson_state_json", "updated_at"])
            except Exception as e:
                logger.error(
                    "Failed to initialize NULL state for UserProgress %s: %s",
                    progress.pk,
                    e,
                    exc_info=True,
                )
                progress.lesson_state_json = {"error": "Initialization failed"}
                progress.save(update_fields=["lesson_state_json", "updated_at"])
                lesson_state = None  # Indicate failure

        # Update status if 'not_started'
        if progress.status == "not_started":
            progress.status = "in_progress"
            progress.save(update_fields=["status", "updated_at"])
            logger.info("Updated UserProgress %s status to 'in_progress'.", progress.pk)

        # Fetch conversation history associated with this progress record (moved here)
        try:
            # Order by timestamp ascending
            conversation_history = list(
                ConversationHistory.objects.filter(progress=progress).order_by(
                    "timestamp"
                )
            )
            logger.info(
                "Fetched %d history messages for UserProgress %s.",
                len(conversation_history),
                progress.pk,
            )
        except Exception as e:
            logger.error(
                "Failed to fetch conversation history for UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )
            # Return empty list, but progress/content might still be valid

    # Ensure the state dictionary is updated in the progress object before returning
    if lesson_state is not None:
        progress.lesson_state_json = (
            lesson_state  # Make sure the object has the latest dict
        )

    return progress, lesson_content, conversation_history


def handle_chat_message(
    user: "User",
    progress: UserProgress,
    user_message_content: str,
    submission_type: str = "chat",  # Add submission_type, default to 'chat'
) -> Optional[Dict[str, Any]]:  # Return a dict with message and potentially state info
    """
    Handles a user's message or submission during a lesson using the AI graph.

    1. Saves the user message to history.
    2. Loads the current lesson state from UserProgress.
    3. Prepares the input state for the LessonInteractionGraph.
    4. Invokes the LessonInteractionGraph to process the message/submission.
    5. Extracts the assistant's response and updated state from the graph output.
    6. Saves the assistant's response to history (if any).
    7. Updates and saves the UserProgress with the new state.
    8. Returns the assistant message and the final updated state.
    """
    logger.info(
        "Handling chat message for UserProgress %s, user %s", progress.pk, user.username
    )

    # 1. Save user message
    try:
        # Determine message type based on submission type
        if submission_type == "answer":
            user_message_type = "exercise_response"
        elif submission_type == "assessment":
            user_message_type = "assessment_response"
        else:
            user_message_type = "chat"

        ConversationHistory.objects.create(
            progress=progress,
            role="user",
            message_type=user_message_type,
            content=user_message_content,
        )
    except Exception as e:
        logger.error(
            "Failed to save user message for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Decide if we should proceed without saving the user message? For now, let's return error.
        return None  # Or return {'error': 'Failed to save user message.'} ?

    # 2. Load current state
    if not isinstance(progress.lesson_state_json, dict):
        logger.error(
            "Invalid or missing lesson state for UserProgress %s. Cannot process message.",
            progress.pk,
        )
        # Attempt to re-initialize? For now, return error.
        # Consider calling get_lesson_state_and_history again or raising specific error
        return None  # Or return {'error': 'Lesson state missing or invalid.'} ?
    current_state: LessonState = cast(LessonState, progress.lesson_state_json.copy())

    # 3. Prepare input state for the graph
    # Fetch recent conversation history to provide context to the graph
    try:
        history_limit = 10  # Limit context window
        recent_history_qs = ConversationHistory.objects.filter(
            progress=progress
        ).order_by("-timestamp")[:history_limit]
        # Format for the graph state (role/content dicts, newest first)
        formatted_history = [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(recent_history_qs)  # Reverse to get oldest first
        ]
        # Nodes expect history under 'history_context' key
        current_state["history_context"] = formatted_history
        # Remove the other key if it exists from previous state loads
        current_state.pop("conversation_history", None)
    except Exception as e:
        logger.error(
            "Failed to fetch conversation history for graph state (UserProgress %s): %s",
            progress.pk,
            e,
            exc_info=True,
        )
        current_state["conversation_history"] = []  # Proceed without history context

    # Set the message being processed and the interaction mode
    current_state["last_user_message"] = user_message_content
    # Map submission_type to interaction_mode expected by the graph
    if submission_type in ["answer", "assessment"]:
        current_state["current_interaction_mode"] = "submit_answer"
    else:  # Default to chatting
        current_state["current_interaction_mode"] = "chatting"
    # Clear previous outputs before calling graph
    current_state.pop("new_assistant_message", None)
    current_state.pop("evaluation_feedback", None)
    current_state.pop("error_message", None)

    # 4. Invoke the LessonInteractionGraph
    graph = LessonInteractionGraph()
    output_state: Optional[LessonState] = None
    assistant_response_content: Optional[str] = None

    try:
        logger.info(
            "Invoking LessonInteractionGraph for UserProgress %s (mode: %s)",
            progress.pk,
            current_state["current_interaction_mode"],
        )
        # The graph execution should be synchronous here
        # Access the compiled graph via the 'graph' attribute of the instance
        output_state_dict = graph.graph.invoke(
            current_state, {"recursion_limit": 10}
        )  # Use invoke for sync call
        if not output_state_dict:
            raise ValueError("Graph invocation returned None.")

        logger.info("Graph invocation successful for UserProgress %s.", progress.pk)

        # Extract potential messages and errors *from the dictionary* before casting
        graph_error_message = output_state_dict.get("error_message")
        new_msg = output_state_dict.get("new_assistant_message")
        feedback_msg = output_state_dict.get("evaluation_feedback")

        # assistant_response_content is already defined outside the try block
        if isinstance(new_msg, str):
            assistant_response_content = new_msg
        elif isinstance(feedback_msg, str):
            assistant_response_content = feedback_msg

        # Log any errors reported by the graph itself
        if graph_error_message:  # Check the extracted error message
            logger.error(
                "Graph reported an error for UserProgress %s: %s",
                progress.pk,
                graph_error_message,
            )
            # Decide if this error should halt processing or just be logged

        # Now cast the dictionary to the TypedDict for type checking elsewhere if needed
        output_state = cast(LessonState, output_state_dict)

    except Exception as e:
        logger.error(
            "Error invoking LessonInteractionGraph for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Save a minimal state update indicating the error?
        current_state["error_message"] = f"Graph invocation failed: {e}"
        progress.lesson_state_json = current_state  # Save state with error
        progress.save(update_fields=["lesson_state_json", "updated_at"])
        return None  # Indicate failure

    # 5. Save assistant response (if any)
    if assistant_response_content:
        try:
            # Determine message type for assistant response
            assistant_message_type = "chat"  # Default
            if output_state and output_state.get("evaluation_feedback"):
                assistant_message_type = (
                    "exercise_feedback"
                    if output_state.get("active_exercise")
                    else "assessment_feedback"
                )
            elif output_state and output_state.get("active_exercise"):
                assistant_message_type = "exercise_prompt"
            elif output_state and output_state.get("active_assessment"):
                assistant_message_type = "assessment_prompt"

            ConversationHistory.objects.create(
                progress=progress,
                role="assistant",
                message_type=assistant_message_type,
                # Ensure we save the string content
                content=str(assistant_response_content),
            )
        except Exception as e:
            logger.error(
                "Failed to save assistant message for UserProgress %s: %s",
                progress.pk,
                e,
                exc_info=True,
            )
            # Continue processing state update even if saving message fails?

    # 6. Update and save UserProgress with the full new state from the graph
    try:
        # Remove temporary context keys before saving if they exist
        # Need to operate on the dictionary before saving
        final_state_dict = dict(output_state) if output_state else {}
        final_state_dict.pop("history_context", None)
        final_state_dict.pop(
            "last_user_message", None
        )  # Don't persist the trigger message in state
        # Also remove transient message/feedback keys before saving
        final_state_dict.pop("new_assistant_message", None)
        final_state_dict.pop("evaluation_feedback", None)

        # Ensure we are saving a plain dict, not a mock or cast object
        progress.lesson_state_json = final_state_dict
        progress.updated_at = django_timezone.now()  # Ensure updated_at is set
        # Check if lesson is completed based on state (e.g., a 'completed' flag set by graph)
        # if output_state.get('lesson_completed'): # Hypothetical flag
        #     progress.status = 'completed'
        #     progress.completed_at = django_timezone.now()
        #     progress.save(update_fields=["lesson_state_json", "status", "completed_at", "updated_at"])
        # else:
        progress.save(update_fields=["lesson_state_json", "updated_at"])

        logger.info("Successfully updated state for UserProgress %s.", progress.pk)

    except Exception as e:
        logger.error(
            "Failed to save updated state for UserProgress %s: %s",
            progress.pk,
            e,
            exc_info=True,
        )
        # Return the message content, but state saving failed
        return (
            {"assistant_message": assistant_response_content}
            if assistant_response_content
            else None
        )

    # Return the assistant message and the final state upon successful completion
    return {
        "assistant_message": assistant_response_content,
        "updated_state": final_state_dict,  # Return the final state dict
    }
