"""Implements the node functions for the syllabus generation LangGraph."""

# pylint: disable=broad-exception-caught

import inspect
import json
import logging
import re
import asyncio

from typing import Any, Dict, List, Optional

import google.generativeai as genai

# Project specific imports
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from tavily import AsyncTavilyClient  # type: ignore # Changed to Async

from core.constants import DIFFICULTY_BEGINNER, DIFFICULTY_KEY_TO_DISPLAY

from core.models import Lesson, Module, Syllabus

from .prompts import GENERATION_PROMPT_TEMPLATE, UPDATE_PROMPT_TEMPLATE
from .state import SyllabusState
from .utils import call_with_retry

logger = logging.getLogger(__name__)
User = get_user_model()


# --- Node Functions ---


def initialize_state(
    _: Optional[SyllabusState],
    topic: str = "",
    knowledge_level: str = "beginner",  # Default to the key
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Initializes the graph state with topic, knowledge level, and user ID."""
    if not topic:
        raise ValueError("Topic is required")

    # Validate the input knowledge_level key and get the display value
    knowledge_level_key = knowledge_level.lower()  # Ensure lowercase for lookup
    knowledge_level_display = DIFFICULTY_KEY_TO_DISPLAY.get(knowledge_level_key)

    if not knowledge_level_display:
        logger.warning(
            f"Invalid knowledge level key '{knowledge_level_key}', defaulting to {DIFFICULTY_BEGINNER}"
        )
        knowledge_level_display = DIFFICULTY_BEGINNER  # Default to the display value

    # Ensure return matches Dict[str, Any]
    initial_state: Dict[str, Any] = {
        "topic": topic,
        "user_knowledge_level": knowledge_level_display,  # Store the display value in state
        "existing_syllabus": None,
        "search_results": [],
        "generated_syllabus": None,
        "user_feedback": None,
        "syllabus_accepted": False,
        "iteration_count": 0,
        "user_entered_topic": topic,
        "user_id": user_id,
        "uid": None,
        "is_master": user_id is None,  # Set based on user_id presence
        "parent_uid": None,
        "created_at": None,
        "updated_at": None,
        "error_message": None,  # Initialize error message
        "search_queries": [],  # Initialize search queries
        "error_generating": False,  # Initialize error flag
    }
    return initial_state


def search_database(state: SyllabusState) -> Dict[str, Any]:
    logger.debug("Starting search_database")
    try:
        """Searches the database for an existing syllabus matching the criteria using Django ORM."""
        # db_service parameter removed
        topic = state["topic"]
        knowledge_level = state[
            "user_knowledge_level"
        ]  # Should hold the display value (e.g., "Beginner")
        user_id = state.get("user_id")
        logger.info(
            f"DB Search: Topic='{topic}', Level='{knowledge_level}', User={user_id}"
        )

        try:
            user = User.objects.get(pk=user_id) if user_id else None
        except User.DoesNotExist:
            logger.warning(
                f"User with ID {user_id} not found. Searching for master syllabus."
            )
            user = None  # Search for master syllabus if user not found
        except ValueError as e:  # Catch invalid PK format
            error_msg = f"Invalid User ID format '{user_id}': {e}"
            logger.error(error_msg)
            return {"existing_syllabus": None, "uid": None, "error_message": error_msg}

        try:
            # Use filter instead of get to handle potential duplicates
            syllabi = (
                Syllabus.objects.prefetch_related(  # pylint: disable=no-member
                    "modules__lessons"  # Prefetch modules and their lessons
                )
                .select_related("user")
                .filter(
                    topic=topic,
                    level=knowledge_level,  # Query DB using the value from state
                    user=user,  # This handles user=None correctly for master syllabi
                )
                .order_by("-updated_at") # Order by most recent first
            )

            syllabus_obj: Optional[Syllabus] = None # Explicit type hint
            if syllabi.exists():
                # Prioritize COMPLETED status if multiple exist
                completed_syllabus = syllabi.filter(status=Syllabus.StatusChoices.COMPLETED).first()
                if completed_syllabus:
                    syllabus_obj = completed_syllabus
                    logger.info(f"Found {syllabi.count()} matching syllabi. Prioritizing COMPLETED one: ID {syllabus_obj.syllabus_id}")
                else:
                    # If no COMPLETED one, take the most recent non-completed one
                    # We know syllabi.exists() is True, so .first() should return a Syllabus
                    syllabus_obj = syllabi.first()
                    if syllabus_obj: # Check if first() returned something (should always)
                         logger.info(f"Found {syllabi.count()} matching syllabi, none COMPLETED. Using most recent: ID {syllabus_obj.syllabus_id}, Status: {syllabus_obj.status}")
                    # else: # This case should theoretically not happen if syllabi.exists() is true
                    #     logger.warning("Syllabi existed but first() returned None.")
                    #     # syllabus_obj remains None

            # Explicitly check if we failed to find/select a suitable syllabus_obj
            if syllabus_obj is None:
                logger.info("No suitable syllabus found after filtering.")
                raise ObjectDoesNotExist("No suitable syllabus found in DB.")

            # --- Existing logic continues below, now operating on the selected syllabus_obj ---

            # logger.info(f"Found existing syllabus in DB. ID: {syllabus_obj.syllabus_id}, Status: {syllabus_obj.status}") # Logging moved up

            # --- Check status of the selected syllabus_obj ---
            if syllabus_obj.status != Syllabus.StatusChoices.COMPLETED:
                logger.info(
                    f"Selected syllabus {syllabus_obj.syllabus_id} is not COMPLETED (status: {syllabus_obj.status}). Proceeding with generation."
                )
                # Treat as not found for the purpose of skipping generation, but keep UID
                logger.debug("Finished search_database")
                return {
                    "existing_syllabus": None,
                    "uid": str(syllabus_obj.syllabus_id), # Keep UID to allow update later
                    "error_message": None,
                }
            # --- End status check ---
            # If we reach here, syllabus_obj is COMPLETED and we proceed to format it
            logger.info(f"Using COMPLETED syllabus {syllabus_obj.syllabus_id} found in DB.")

            # Reconstruct the nested dictionary structure expected by the graph state
            modules_list = []
            for module in syllabus_obj.modules.all():  # type: ignore[attr-defined] # Mypy struggles with reverse relations
                lessons_list = [
                    {
                        "title": lesson.title,
                        "summary": lesson.summary,
                        "duration": lesson.duration,
                        # Add other relevant lesson fields if needed
                    }
                    for lesson in module.lessons.all()
                ]
                modules_list.append(
                    {
                        "title": module.title,
                        "summary": module.summary,
                        "lessons": lessons_list,
                        # Add other relevant module fields if needed
                    }
                )

            # Create the syllabus_data dictionary matching the old structure as closely as possible
            syllabus_data = {
                "syllabus_id": str(syllabus_obj.syllabus_id),  # Use the actual PK name
                "uid": str(
                    syllabus_obj.syllabus_id
                ),  # Map uid to syllabus_id for compatibility
                "topic": syllabus_obj.topic,
                "level": syllabus_obj.level,
                "user_entered_topic": syllabus_obj.user_entered_topic
                or state.get("user_entered_topic", topic),
                "user_id": (
                    str(syllabus_obj.user.pk)
                    if isinstance(syllabus_obj.user, User)
                    else None
                ),  # Added isinstance check for Mypy
                "is_master": syllabus_obj.user is None,  # Master if no user linked
                "parent_uid": None,  # Django models don't have parent_uid concept directly
                "created_at": (
                    syllabus_obj.created_at.isoformat() if syllabus_obj.created_at else None
                ),
                "updated_at": (
                    syllabus_obj.updated_at.isoformat() if syllabus_obj.updated_at else None
                ),
                "modules": modules_list,
                "duration": (
                    syllabus_obj.duration if hasattr(syllabus_obj, "duration") else "N/A"
                ),  # Placeholder if not on model
                "learning_objectives": (
                    syllabus_obj.learning_objectives
                    if hasattr(syllabus_obj, "learning_objectives")
                    else []
                ),  # Placeholder if not on model
            }

            # Return the COMPLETED syllabus data
            logger.debug("Finished search_database")
            return {
                "existing_syllabus": syllabus_data,
                "uid": syllabus_data["uid"],
                "is_master": syllabus_data["is_master"],
                "parent_uid": syllabus_data["parent_uid"],
                "created_at": syllabus_data["created_at"],
                "updated_at": syllabus_data["updated_at"],
                "user_entered_topic": syllabus_data["user_entered_topic"],
                "topic": syllabus_data["topic"],
                "user_knowledge_level": syllabus_data["level"],
                "error_message": None,  # Explicitly None on success
            }

        except ObjectDoesNotExist:
            logger.info("No matching syllabus found in DB.")
            logger.debug("Finished search_database")
            return {
                "existing_syllabus": None,
                "uid": None,
                "error_message": None,
            }  # Return uid: None when not found, no error message here
        except Exception as e:
            error_msg = f"DB search error: {e}"
            logger.error(f"Error searching database for syllabus: {e}", exc_info=True)
            logger.debug("Finished search_database")
            return {
                "existing_syllabus": None,
                "uid": None,
                "error_message": error_msg,
            }  # Return None on error and message
    except Exception as e:
        logger.error("Unexpected error in search_database", exc_info=True)
        raise






def _parse_llm_json_response(response: Any) -> Optional[Dict[str, Any]]:
    """Attempts to parse a JSON object from the LLM response text."""
    json_str = None
    try:
        # Handle both string responses and response objects with a 'content' or 'text' attribute
        if isinstance(response, str):
            response_text = response
        elif hasattr(response, "content") and isinstance(response.content, str):
            response_text = response.content
        elif hasattr(response, "text") and isinstance(response.text, str):
            response_text = response.text
        else:
            logger.error(f"Unexpected response type for JSON parsing: {type(response)}")
            return None

        # Try to find JSON within markdown code blocks first
        match = re.search(r"```(?:json)?\s*({.*?})\s*```", response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
            logger.info("Found JSON within markdown block.")
        else:
            # If no markdown block, assume the whole text is JSON (after stripping)
            json_str = response_text.strip()
            # Basic check if it looks like JSON before attempting parse
            if not (json_str.startswith("{") and json_str.endswith("}")):
                logger.warning("Response does not appear to be JSON or markdown block.")
                return None
            logger.info("Attempting to parse response text directly as JSON.")

        # Clean up common escape issues before parsing
        json_str = re.sub(r"\\n", "", json_str)  # Remove escaped newlines
        json_str = re.sub(
            r"\\(?![\"\\/bfnrtu])", "", json_str
        )  # Remove invalid escapes

        # Parse the extracted JSON string
        parsed_json = json.loads(json_str)
        if not isinstance(parsed_json, dict):
            logger.warning(f"Parsed JSON is not a dictionary: {type(parsed_json)}")
            return None

        logger.info("Successfully parsed JSON from LLM response.")
        return parsed_json

    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse JSON from response: {e}. String was: {json_str}..."
        )  # Removed slicing
        return None
    except Exception as e:
        logger.error(f"Unexpected error during JSON parsing: {e}", exc_info=True)
        return None


# pylint: disable=too-many-return-statements
def _validate_syllabus_structure(
    syllabus: Dict[str, Any], context: str = "Generated"
) -> bool:  # Added type hint
    """Performs basic validation on the syllabus dictionary structure."""
    required_keys = ["topic", "level", "duration", "learning_objectives", "modules"]
    if not all(key in syllabus for key in required_keys):
        logger.error(f"Error: {context} JSON missing required keys ({required_keys}).")
        return False
    if not isinstance(syllabus.get("modules"), list):  # Allow empty modules list here
        logger.error(f"Error: {context} JSON 'modules' must be a list.")
        return False
    # if not isinstance(syllabus.get("modules"), list) or not syllabus.get("modules"):
    #     logger.error(f"Error: {context} JSON 'modules' must be a non-empty list.")
    #     return False
    for i, module in enumerate(syllabus["modules"]):
        if not isinstance(module, dict):
            logger.error(f"Error: {context} JSON module {i} is not a dictionary.")
            return False
        if not all(key in module for key in ["title", "lessons"]):
            logger.error(
                f"Error: {context} JSON module {i} missing 'title' or 'lessons'."
            )
            return False
        # Allow empty lessons list during validation, save node can handle it
        if not isinstance(
            module.get("lessons"), list
        ):  # Check it's a list, even if empty
            logger.error(f"Error: {context} JSON module {i} 'lessons' must be a list.")
            return False
        # if not isinstance(module.get("lessons"), list) or not module.get("lessons"):
        #     logger.error(
        #         f"Error: {context} JSON module {i} 'lessons' must be a non-empty list."
        #     )
        #     return False
        for j, lesson in enumerate(module["lessons"]):
            if not isinstance(lesson, dict):
                logger.error(
                    f"Error: {context} JSON lesson {j} in module {i} is not a dictionary."
                )
                return False
            if "title" not in lesson or not lesson["title"]:
                logger.error(
                    f"Error: {context} JSON lesson {j} in module {i} missing 'title'."
                )
                return False
    logger.info(f"{context} JSON passed basic validation.")
    return True






# pylint: disable=too-many-return-statements, too-many-locals, too-many-branches
def save_syllabus(state: SyllabusState) -> Dict[str, Any]:
    logger.debug("Starting save_syllabus")
    try:
        """Saves the current syllabus (generated or existing) to the database using Django ORM."""
        syllabus_to_save = state.get("generated_syllabus")
        if not syllabus_to_save:
            logger.warning("No generated syllabus found in state to save.")
            logger.debug("Finished save_syllabus")
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": "No generated syllabus content found in state.",
            }

        if not isinstance(syllabus_to_save, dict):
            error_msg = f"Invalid format for syllabus_to_save: Expected dict, got {type(syllabus_to_save)}."
            logger.error(error_msg)
            logger.debug("Finished save_syllabus")
            return {"syllabus_saved": False, "saved_uid": None, "error_message": error_msg}

        original_topic = state.get("topic")
        if not original_topic or not isinstance(original_topic, str):
            error_msg = f"Invalid or missing 'topic' in state: {original_topic}"
            logger.error(error_msg)
            logger.debug("Finished save_syllabus")
            return {"syllabus_saved": False, "saved_uid": None, "error_message": error_msg}

        user_entered_topic_from_state = state.get("user_entered_topic")
        if not user_entered_topic_from_state or not isinstance(user_entered_topic_from_state, str):
            error_msg = f"Missing or invalid user_entered_topic in state for saving: '{user_entered_topic_from_state}'"
            logger.error(error_msg)
            raise ValueError(error_msg)
        user_id = state.get("user_id")
        level_str = state.get("user_knowledge_level")

        if not level_str or not isinstance(level_str, str):
            error_msg = f"Invalid or missing 'user_knowledge_level' in state: {level_str}"
            logger.error(error_msg)
            logger.debug("Finished save_syllabus")
            return {"syllabus_saved": False, "saved_uid": None, "error_message": error_msg}

        logger.info(
            f"Save Attempt: User={user_id}, Topic='{original_topic}', Level='{level_str}'"
        )

        try:
            syllabus_dict = syllabus_to_save.copy()
            modules_data = syllabus_dict.get("modules", [])

            required_keys = ["topic", "level", "duration", "learning_objectives", "modules"]
            missing_keys = [k for k in required_keys if k not in syllabus_dict]
            if missing_keys:
                error_msg = f"Syllabus data missing required keys: {', '.join(missing_keys)}."
                logger.error(error_msg)
                logger.debug("Finished save_syllabus")
                return {
                    "syllabus_saved": False,
                    "saved_uid": None,
                    "error_message": error_msg,
                }

            if not isinstance(modules_data, list):
                error_msg = f"Syllabus 'modules' is not a list: {syllabus_dict}"
                logger.error(error_msg)
                logger.debug("Finished save_syllabus")
                return {
                    "syllabus_saved": False,
                    "saved_uid": None,
                    "error_message": error_msg,
                }

            user_obj = None
            if user_id:
                try:
                    user_obj = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    error_msg = f"User with ID {user_id} not found. Cannot save syllabus for this user."
                    logger.error(error_msg)
                    logger.debug("Finished save_syllabus")
                    return {
                        "syllabus_saved": False,
                        "saved_uid": None,
                        "error_message": error_msg,
                    }
                except ValueError as e:
                    error_msg = f"Invalid User ID format '{user_id}': {e}"
                    logger.error(error_msg)
                    logger.debug("Finished save_syllabus")
                    return {
                        "syllabus_saved": False,
                        "saved_uid": None,
                        "error_message": error_msg,
                    }

            defaults = {
                "topic": syllabus_dict.get("topic", original_topic),
                "level": syllabus_dict.get("level", level_str),
                "user_entered_topic": user_entered_topic_from_state,
                "status": Syllabus.StatusChoices.COMPLETED,
            }

            uid_to_update = state.get("uid")
            if uid_to_update:
                logger.info(
                    f"Attempting to update existing syllabus with UID: {uid_to_update}"
                )
                syllabus_instance, created = (
                    Syllabus.objects.update_or_create(
                        syllabus_id=uid_to_update,
                        defaults=defaults,
                    )
                )
                if created:
                    logger.warning(
                        f"Created syllabus with ID {uid_to_update} during an update attempt?"
                    )
            else:
                logger.info(
                    f"Attempting to find or create syllabus with Topic='{original_topic}', Level='{level_str}', User={user_obj}"
                )
                syllabus_instance, created = (
                    Syllabus.objects.update_or_create(
                        topic=original_topic,
                        level=level_str,
                        user=user_obj,
                        defaults=defaults,
                    )
                )
            action = "Created" if created else "Updated"
            logger.info(f"{action} syllabus record ID: {syllabus_instance.syllabus_id}")

            syllabus_instance.modules.all().delete()

            for module_index, module_data in enumerate(modules_data):
                if not isinstance(module_data, dict):
                    logger.warning(
                        f"Skipping invalid module data (not a dict) at index {module_index}"
                    )
                    continue

                module_title = module_data.get("title", f"Untitled Module {module_index+1}")
                module_summary = module_data.get("summary", "")
                lessons_data = module_data.get("lessons", [])

                module_instance = Module.objects.create(
                    syllabus=syllabus_instance,
                    module_index=module_index,
                    title=module_title,
                    summary=module_summary,
                )

                if not isinstance(lessons_data, list):
                    logger.warning(
                        f"Skipping invalid lessons data (not a list) in module '{module_title}'"
                    )
                    continue

                for lesson_index, lesson_data in enumerate(lessons_data):
                    if not isinstance(lesson_data, dict):
                        logger.warning(
                            f"Skipping invalid lesson data (not a dict) at index {lesson_index} in module '{module_title}'"
                        )
                        continue

                    lesson_title = lesson_data.get(
                        "title", f"Untitled Lesson {lesson_index+1}"
                    )
                    lesson_summary = lesson_data.get("summary", "")
                    lesson_duration = lesson_data.get("duration")

                    Lesson.objects.create(
                        module=module_instance,
                        lesson_index=lesson_index,
                        title=lesson_title,
                        summary=lesson_summary,
                        duration=lesson_duration,
                    )

            saved_uid = str(syllabus_instance.syllabus_id)
            logger.debug("Finished save_syllabus")
            return {
                "syllabus_saved": True,
                "saved_uid": saved_uid,
                "uid": saved_uid,
                "error_message": None,
            }
        except Exception as e:
            logger.error(f"Error saving syllabus to database: {e}", exc_info=True)
            uid_to_fail = state.get("uid")
            if uid_to_fail:
                try:
                    Syllabus.objects.filter(syllabus_id=uid_to_fail).update(status=Syllabus.StatusChoices.FAILED)
                    logger.info(f"Set status to FAILED for syllabus {uid_to_fail} due to save error.")
                except Exception as update_err:
                    logger.error(f"Could not update status to FAILED for syllabus {uid_to_fail}: {update_err}")

            logger.debug("Finished save_syllabus")
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": f"DB save error: {e}",
            }
    except Exception:
        logger.error("Unexpected error in save_syllabus", exc_info=True)
        raise


def end_node(state: SyllabusState) -> SyllabusState:
    logger.debug("Starting end_node")
    try:
        """End node for the graph, simply returns the final state."""
        logger.info("Workflow ended.")
        logger.debug("Finished end_node")
        return state
    except Exception:
        logger.error("Unexpected error in end_node", exc_info=True)
        raise
