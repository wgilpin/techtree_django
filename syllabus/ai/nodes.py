"""Implements the node functions for the syllabus generation LangGraph."""

# pylint: disable=broad-exception-caught

import json
import logging
import re
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional  # Added List, Any, cast

import google.generativeai as genai

# Project specific imports
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from requests import RequestException
from tavily import TavilyClient  # type: ignore

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
    knowledge_level: str = "beginner",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:  # Changed return type hint
    """Initializes the graph state with topic, knowledge level, and user ID."""
    if not topic:
        raise ValueError("Topic is required")

    # Map the key to the display value using DIFFICULTY_KEY_TO_DISPLAY
    knowledge_level_key = knowledge_level.lower()

    knowledge_level_display = DIFFICULTY_KEY_TO_DISPLAY.get(knowledge_level_key)
    if not knowledge_level_display:
        logger.warning(
            f"Invalid knowledge level key '{knowledge_level_key}', defaulting to {DIFFICULTY_BEGINNER}"
        )
        knowledge_level_display = DIFFICULTY_BEGINNER

    # Ensure return matches Dict[str, Any]
    initial_state: Dict[str, Any] = {
        "topic": topic,
        "user_knowledge_level": knowledge_level_display,
        "existing_syllabus": None,
        "search_results": [],
        "generated_syllabus": None,
        "user_feedback": None,
        "syllabus_accepted": False,
        "iteration_count": 0,
        "user_entered_topic": topic,
        "user_id": user_id,
        "uid": None,
        "is_master": user_id is None,
        "parent_uid": None,
        "created_at": None,
        "updated_at": None,
        "search_queries": [],
        "error_message": None,  # Initialize error message
    }
    return initial_state


def search_database(state: SyllabusState) -> Dict[str, Any]:
    """Searches the database for an existing syllabus matching the criteria using Django ORM."""
    logger.debug("Starting search_database")
    try:
        topic = state["topic"]
        knowledge_level = state["user_knowledge_level"]
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
                .order_by("-updated_at")  # Order by most recent first
            )

            syllabus_obj: Optional[Syllabus] = None  # Explicit type hint
            if syllabi.exists():
                # Prioritize COMPLETED status if multiple exist
                completed_syllabus = syllabi.filter(
                    status=Syllabus.StatusChoices.COMPLETED
                ).first()
                if completed_syllabus:
                    syllabus_obj = completed_syllabus
                    logger.info(
                        f"Found {syllabi.count()} matching syllabi. Prioritizing COMPLETED one: "
                        f"ID {syllabus_obj.syllabus_id}"
                    )
                else:
                    # If no COMPLETED one, take the most recent non-completed one
                    syllabus_obj = syllabi.first()
                    if (
                        syllabus_obj
                    ):  # Check if first() returned something (should always)
                        logger.info(
                            f"Found {syllabi.count()} matching syllabi, none COMPLETED."
                            f" Using most recent: ID {syllabus_obj.syllabus_id}, Status: {syllabus_obj.status}"
                        )

            # Explicitly check if we failed to find/select a suitable syllabus_obj
            if syllabus_obj is None:
                logger.info("No suitable syllabus found after filtering.")
                raise ObjectDoesNotExist("No suitable syllabus found in DB.")

            # --- Check status of the selected syllabus_obj ---
            if syllabus_obj.status != Syllabus.StatusChoices.COMPLETED:
                logger.info(
                    f"Selected syllabus {syllabus_obj.syllabus_id} is not COMPLETED "
                    f"(status: {syllabus_obj.status}). Proceeding with generation."
                )
                # Treat as not found for the purpose of skipping generation, but keep UID
                logger.debug("Finished search_database")
                return {
                    "existing_syllabus": None,
                    "uid": str(
                        syllabus_obj.syllabus_id
                    ),  # Keep UID to allow update later
                    "error_message": None,
                }
            # --- End status check ---
            # If we reach here, syllabus_obj is COMPLETED and we proceed to format it
            logger.info(
                f"Using COMPLETED syllabus {syllabus_obj.syllabus_id} found in DB."
            )

            # Reconstruct the nested dictionary structure expected by the graph state
            modules_list = []
            for module in syllabus_obj.modules.all():  # type: ignore[attr-defined]
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
                    syllabus_obj.created_at.isoformat()
                    if syllabus_obj.created_at
                    else None
                ),
                "updated_at": (
                    syllabus_obj.updated_at.isoformat()
                    if syllabus_obj.updated_at
                    else None
                ),
                "modules": modules_list,
                "duration": (
                    syllabus_obj.duration
                    if hasattr(syllabus_obj, "duration")
                    else "N/A"
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


def search_internet(
    state: SyllabusState, tavily_client: Optional[TavilyClient]
) -> Dict[str, List[str]]:
    """Performs a web search using Tavily to gather context."""
    if not tavily_client:
        logger.warning("Tavily client not configured. Skipping internet search.")
        return {"search_results": ["Tavily client not available."]}

    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    logger.info(f"Internet Search: Topic='{topic}', Level='{knowledge_level}'")

    search_results: List[str] = []
    queries = [
        (
            f"{topic} syllabus curriculum outline learning objectives",
            {"include_domains": ["en.wikipedia.org", "edu"], "max_results": 2},
        ),
        (
            f"{topic} course syllabus curriculum for {knowledge_level} students",
            {"max_results": 3},
        ),
    ]

    for query, params in queries:
        try:
            logger.info(f"Tavily Query: {query} (Params: {params})")
            search = tavily_client.search(
                query=query, search_depth="advanced", **params
            )
            content = [
                r.get("content", "")
                for r in search.get("results", [])
                if r.get("content")
            ]
            search_results.extend(content)
            logger.info(f"Found {len(content)} results.")
        except RequestException as e:
            logger.warning(f"Tavily request error for query '{query}': {e}")
            search_results.append(f"Error during web search: {str(e)}")
        except Exception as e:
            logger.error(
                f"Unexpected error during Tavily search for query '{query}': {e}",
                exc_info=True,
            )
            search_results.append(f"Unexpected error during web search: {str(e)}")

    logger.info(f"Total search results gathered: {len(search_results)}")
    return {"search_results": search_results}


def _parse_llm_json_response(
    response_text: str,
) -> Optional[Dict[str, Any]]:  # Changed return type hint
    """Attempts to parse a JSON object from the LLM response text."""
    json_str = None
    try:
        match = re.search(r"```(?:json)?\s*({.*?})\s*```", response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            json_str = response_text.strip()
            if not (json_str.startswith("{") and json_str.endswith("}")):
                logger.warning("Response does not appear to be JSON or markdown block.")
                return None

        json_str = re.sub(r"\\n", "", json_str)
        json_str = re.sub(r"\\(?![\"\\/bfnrtu])", "", json_str)

        parsed_json = json.loads(json_str)
        if not isinstance(parsed_json, dict):
            logger.warning(f"Parsed JSON is not a dictionary: {type(parsed_json)}")
            return None
        return parsed_json  # Returns Dict[str, Any]
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from response: {e}")
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
    if not isinstance(syllabus.get("modules"), list) or not syllabus.get("modules"):
        logger.error(f"Error: {context} JSON 'modules' must be a non-empty list.")
        return False
    for i, module in enumerate(syllabus["modules"]):
        if not isinstance(module, dict):
            logger.error(f"Error: {context} JSON module {i} is not a dictionary.")
            return False
        if not all(key in module for key in ["title", "lessons"]):
            logger.error(
                f"Error: {context} JSON module {i} missing 'title' or 'lessons'."
            )
            return False
        if not isinstance(module.get("lessons"), list) or not module.get("lessons"):
            logger.error(
                f"Error: {context} JSON module {i} 'lessons' must be a non-empty list."
            )
            return False
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


def generate_syllabus(
    state: SyllabusState, llm_model: Optional[genai.GenerativeModel]  # type: ignore[name-defined]
) -> Dict[str, Any]:  # Changed return type hint
    """Generates a new syllabus using the LLM based on search results."""
    if not llm_model:
        logger.warning("LLM model not configured. Cannot generate syllabus.")
        return {
            "generated_syllabus": {
                "topic": state["topic"],
                "level": state["user_knowledge_level"],
                "duration": "N/A",
                "learning_objectives": ["Generation failed"],
                "modules": [{"title": "Generation Failed", "lessons": []}],
                "error_generating": True,
            }
        }

    logger.info("Generating syllabus with AI...")
    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    search_results = state["search_results"]

    search_context = "\n\n---\n\n".join(
        [
            f"Source {i+1}:\n{result}"
            for i, result in enumerate(search_results)
            if result and isinstance(result, str)
        ]
    )
    if not search_context:
        search_context = (
            "No specific search results found. Generate based on general knowledge."
        )

    prompt = GENERATION_PROMPT_TEMPLATE.format(
        topic=topic, knowledge_level=knowledge_level, search_context=search_context
    )

    response_text = ""
    try:
        logger.info("Sending generation request to LLM...")
        response = call_with_retry(llm_model.generate_content, prompt)
        response_text = response.text
        logger.info("LLM response received.")
    except Exception as e:
        logger.error(f"LLM call failed during syllabus generation: {e}", exc_info=True)

    syllabus = _parse_llm_json_response(response_text)

    if syllabus and _validate_syllabus_structure(syllabus, "Generated"):
        return {"generated_syllabus": syllabus}
    else:
        logger.warning(
            "Using fallback syllabus structure due to generation/parsing/validation error."
        )
        return {
            "generated_syllabus": {
                "topic": topic,
                "level": knowledge_level.capitalize(),
                "duration": "4 weeks (estimated)",
                "learning_objectives": [
                    f"Understand basic concepts of {topic}.",
                    "Identify key components or principles.",
                ],
                "modules": [
                    {
                        "unit": 1,
                        "title": f"Introduction to {topic}",
                        "lessons": [
                            {"title": "What is " + topic + "?"},
                            {"title": "Core Terminology"},
                            {"title": "Real-world Examples"},
                        ],
                    },
                    {
                        "unit": 2,
                        "title": f"Fundamental Principles of {topic}",
                        "lessons": [
                            {"title": "Principle A"},
                            {"title": "Principle B"},
                            {"title": "How Principles Interact"},
                        ],
                    },
                ],
                "error_generating": True,
            }
        }


def update_syllabus(
    state: SyllabusState,
    feedback: str,
    llm_model: Optional[genai.GenerativeModel],  # type: ignore[name-defined]
) -> Dict[str, Any]:  # Changed return type hint
    """Updates the current syllabus based on user feedback using the LLM."""
    if not llm_model:
        logger.warning("LLM model not configured. Cannot update syllabus.")
        return {
            "user_feedback": feedback,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    iteration = state.get("iteration_count", 0) + 1
    logger.info(f"Updating syllabus based on feedback (Iteration {iteration})")
    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    current_syllabus = state.get("generated_syllabus") or state.get("existing_syllabus")

    if not current_syllabus:
        logger.error("Error: Cannot update syllabus as none exists in state.")
        return {"iteration_count": iteration}

    try:
        if not isinstance(current_syllabus, dict):
            raise TypeError(
                f"Expected dict for current_syllabus, got {type(current_syllabus)}"
            )
        syllabus_json = json.dumps(current_syllabus, indent=2)
    except TypeError as e:
        logger.error(f"Error serializing current syllabus to JSON for update: {e}")
        return {"iteration_count": iteration}

    prompt = UPDATE_PROMPT_TEMPLATE.format(
        topic=topic,
        knowledge_level=knowledge_level,
        syllabus_json=syllabus_json,
        feedback=feedback,
    )

    response_text = ""
    try:
        logger.info("Sending update request to LLM...")
        response = call_with_retry(llm_model.generate_content, prompt)
        response_text = response.text
        logger.info("LLM update response received.")
    except Exception as e:
        logger.error(f"LLM call failed during syllabus update: {e}", exc_info=True)

    updated_syllabus = _parse_llm_json_response(response_text)

    if updated_syllabus and _validate_syllabus_structure(updated_syllabus, "Updated"):
        return {
            "generated_syllabus": updated_syllabus,
            "user_feedback": feedback,
            "iteration_count": iteration,
        }
    else:
        logger.warning("Update failed (parsing/validation), keeping original syllabus.")
        return {
            "user_feedback": feedback,
            "iteration_count": iteration,
        }


# --- Refactored save_syllabus and helpers ---


def _validate_syllabus_dict(syllabus_dict: Dict[str, Any]) -> Optional[str]:
    required_keys = [
        "topic",
        "level",
        "duration",
        "learning_objectives",
        "modules",
    ]
    missing_keys = [k for k in required_keys if k not in syllabus_dict]
    if missing_keys:
        return f"Syllabus data missing required keys: {', '.join(missing_keys)}."
    if not isinstance(syllabus_dict.get("modules"), list):
        return f"Syllabus 'modules' is not a list: {syllabus_dict}"
    return None


def _get_user_obj(user_id: Optional[str]):
    if not user_id:
        return None, None
    try:
        return User.objects.get(pk=user_id), None
    except User.DoesNotExist:
        return (
            None,
            f"User with ID {user_id} not found. Cannot save syllabus for this user.",
        )
    except ValueError as e:
        return None, f"Invalid User ID format '{user_id}': {e}"


def _get_or_create_syllabus_instance(
    state: SyllabusState,
    syllabus_dict: Dict[str, Any],
    user_obj: Any,
    original_topic: str,
    level_str: str,
    user_entered_topic_from_state: str,
):
    defaults = {
        "topic": original_topic,
        "level": level_str,
        "user_entered_topic": user_entered_topic_from_state,
        "status": Syllabus.StatusChoices.COMPLETED,
    }
    uid_to_update = state.get("uid") or syllabus_dict.get("uid")
    if uid_to_update:
        try:
            syllabus_instance = Syllabus.objects.get(syllabus_id=uid_to_update)
            syllabus_instance.topic = syllabus_dict.get("topic", defaults["topic"])
            syllabus_instance.level = syllabus_dict.get("level", defaults["level"])
            syllabus_instance.user_entered_topic = syllabus_dict.get(
                "user_entered_topic", defaults["user_entered_topic"]
            )
            syllabus_instance.status = str(Syllabus.StatusChoices.COMPLETED)
            syllabus_instance.save()
            created = False
        except Exception as e:
            syllabus_instance = Syllabus.objects.create(
                syllabus_id=uid_to_update,
                user=user_obj,
                topic=defaults["topic"],
                level=defaults["level"],
                user_entered_topic=defaults["user_entered_topic"],
                status=Syllabus.StatusChoices.COMPLETED,
            )
            created = True
            return (
                None,
                None,
                f"Error during update_or_create for UID {uid_to_update}: {e}",
            )
    else:
        try:
            syllabus_instance, created = Syllabus.objects.update_or_create(
                topic=original_topic,
                level=level_str,
                user=user_obj,
                defaults=defaults,
            )
        except Exception as e:
            return (
                None,
                None,
                f"Error during update_or_create for Topic/Level/User: {e}",
            )
    return syllabus_instance, created, None


def _save_modules_and_lessons(syllabus_instance, modules_data):
    syllabus_instance.modules.all().delete()  # type: ignore[attr-defined]
    for module_index, module_data in enumerate(modules_data):
        if not isinstance(module_data, dict):
            continue
        module_title = module_data.get("title", f"Untitled Module {module_index+1}")
        module_summary = module_data.get("summary", "")
        lessons_data = module_data.get("lessons", [])
        # pylint: disable=no-member
        module_instance = Module.objects.create(
            syllabus=syllabus_instance,
            module_index=module_index,
            title=module_title,
            summary=module_summary,
        )
        if not isinstance(lessons_data, list):
            continue
        for lesson_index, lesson_data in enumerate(lessons_data):
            if not isinstance(lesson_data, dict):
                continue
            lesson_title = lesson_data.get("title", f"Untitled Lesson {lesson_index+1}")
            lesson_summary = lesson_data.get("summary", "")
            lesson_duration = lesson_data.get("duration")
            # pylint: disable=no-member
            Lesson.objects.create(
                module=module_instance,
                lesson_index=lesson_index,
                title=lesson_title,
                summary=lesson_summary,
                duration=lesson_duration,
            )


def save_syllabus(state: SyllabusState) -> Dict[str, Any]:
    try:
        syllabus_to_save = state.get("generated_syllabus")
        if not syllabus_to_save:
            syllabus_to_save = state.get("existing_syllabus")
            if not syllabus_to_save:
                return {
                    "syllabus_saved": False,
                    "saved_uid": None,
                    "error_message": "No generated syllabus content found in state",
                }
        if not isinstance(syllabus_to_save, dict):
            error_msg = f"Invalid format for syllabus_to_save: Expected dict, got {type(syllabus_to_save)}."
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }
        original_topic = state.get("topic")
        if not original_topic or not isinstance(original_topic, str):
            error_msg = f"Invalid or missing 'topic' in state: {original_topic}"
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }
        user_entered_topic_from_state = state.get("user_entered_topic")
        if not user_entered_topic_from_state or not isinstance(
            user_entered_topic_from_state, str
        ):
            user_entered_topic_from_state = original_topic
        user_id = state.get("user_id")
        level_str = state.get("user_knowledge_level")
        if not level_str or not isinstance(level_str, str):
            error_msg = (
                f"Invalid or missing 'user_knowledge_level' in state: {level_str}"
            )
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }
        syllabus_dict = syllabus_to_save.copy()
        modules_data = syllabus_dict.get("modules", [])
        validation_error = _validate_syllabus_dict(syllabus_dict)
        if validation_error:
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": validation_error,
            }
        user_obj, user_error = _get_user_obj(user_id)
        if user_error:
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": user_error,
            }
        syllabus_instance, created, db_error = _get_or_create_syllabus_instance(
            state,
            syllabus_dict,
            user_obj,
            original_topic,
            level_str,
            user_entered_topic_from_state,
        )
        if db_error or syllabus_instance is None:
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": db_error or "Unknown error during syllabus save",
            }
        _save_modules_and_lessons(syllabus_instance, modules_data)
        saved_uid = str(syllabus_instance.syllabus_id)
        return {
            "syllabus_saved": True,
            "saved_uid": saved_uid,
            "uid": saved_uid,
            "created_at": (
                syllabus_instance.created_at.isoformat()
                if syllabus_instance.created_at
                else None
            ),
            "updated_at": (
                syllabus_instance.updated_at.isoformat()
                if syllabus_instance.updated_at
                else None
            ),
            "is_master": syllabus_instance.user is None,
            "error_message": None,
        }
    except Exception as e:
        syllabus_dict = (
            state.get("generated_syllabus") or state.get("existing_syllabus") or {}
        )
        uid_to_fail = state.get("uid") or syllabus_dict.get("uid")
        if uid_to_fail:
            try:
                Syllabus.objects.filter(syllabus_id=uid_to_fail).update(
                    status=Syllabus.StatusChoices.FAILED
                )  # pylint: disable=no-member
            except Exception:
                pass
        return {
            "syllabus_saved": False,
            "saved_uid": None,
            "error_message": f"DB save error: {e}",
        }


def end_node(state: SyllabusState) -> SyllabusState:
    """Terminal node for the graph. Returns the state unchanged."""
    logger.info("Workflow ended.")
    return state
