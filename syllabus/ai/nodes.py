"""Implements the node functions for the syllabus generation LangGraph."""

# pylint: disable=broad-exception-caught

import json
import re
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional  # Added List, Any, cast

import google.generativeai as genai
from requests import RequestException
from tavily import AsyncTavilyClient  # type: ignore # Changed to Async

import logging  # Use standard logging or Django's

# from backend.logger import logger # Replace with standard/Django logging if needed
# Project specific imports
# from backend.services.sqlite_db import SQLiteDatabaseService # Replaced with Django ORM
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from core.models import Syllabus, Module, Lesson

from .prompts import GENERATION_PROMPT_TEMPLATE, UPDATE_PROMPT_TEMPLATE
from .state import SyllabusState
from .utils import call_with_retry

# Get logger instance (using standard logging for now)
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

    # No level validation for now, accept any string
    # Ensure return matches Dict[str, Any]
    initial_state: Dict[str, Any] = {
        "topic": topic,
        "user_knowledge_level": knowledge_level,
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
    """Searches the database for an existing syllabus matching the criteria using Django ORM."""
    # db_service parameter removed
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
        syllabus_obj = (
            Syllabus.objects.prefetch_related(  # pylint: disable=no-member
                "modules__lessons"  # Prefetch modules and their lessons
            )
            .select_related("user")
            .get(
                topic=topic,
                level=knowledge_level,
                user=user,  # This handles user=None correctly for master syllabi
            )
        )

        logger.info(f"Found existing syllabus in DB. ID: {syllabus_obj.syllabus_id}")

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
        return {
            "existing_syllabus": None,
            "uid": None,
            "error_message": None,
        }  # Return uid: None when not found, no error message here
    except Exception as e:
        error_msg = f"DB search error: {e}"
        logger.error(f"Error searching database for syllabus: {e}", exc_info=True)
        return {
            "existing_syllabus": None,
            "uid": None,
            "error_message": error_msg,
        }  # Return None on error and message


import asyncio  # Added
from typing import Any, Dict, List, Optional

from tavily import AsyncTavilyClient  # Changed from TavilyClient


from .state import SyllabusState


async def search_internet(  # Changed to async def
    state: SyllabusState,
    tavily_client: Optional[AsyncTavilyClient],  # Changed type hint
) -> Dict[str, Any]:
    """Performs a web search using Tavily to gather context concurrently."""
    if not tavily_client:
        logger.warning("AsyncTavily client not configured. Skipping internet search.")
        return {
            "search_results": [],
            "search_queries": [],
            "error_message": "Tavily client not configured.",
        }

    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    logger.info(f"Internet Search (Async): Topic='{topic}', Level='{knowledge_level}'")

    # Define queries and their specific parameters
    queries_with_params = [
        (
            f"{topic} overview",
            {
                "include_domains": ["en.wikipedia.org"],
                "max_results": 2,
                "search_depth": "advanced",
            },
        ),
        (
            f"{topic} syllabus curriculum outline learning objectives",
            {"include_domains": ["edu"], "max_results": 3, "search_depth": "advanced"},
        ),
        (
            f"{topic} course syllabus curriculum for {knowledge_level} students",
            {"max_results": 3, "search_depth": "advanced"},
        ),
    ]

    # Create awaitable tasks for each search query and its parameters
    search_tasks = [
        tavily_client.search(query=query, **params)
        for query, params in queries_with_params
    ]

    search_results_content: List[str] = []
    executed_queries = [
        q[0] for q in queries_with_params
    ]  # Keep track of attempted queries
    error_message = None

    try:
        # Run searches concurrently, return exceptions for failed ones
        logger.info(f"Starting {len(search_tasks)} Tavily searches concurrently...")
        responses = await asyncio.gather(*search_tasks, return_exceptions=True)
        logger.info("Tavily searches completed.")

        for i, response in enumerate(responses):
            query_attempted = executed_queries[i]
            if isinstance(response, Exception):
                logger.error(
                    f"Tavily search failed for query '{query_attempted}': {response}"
                )
                # Accumulate error messages including exception details
                err_detail = f"Search failed for '{query_attempted}': {response}"
                if error_message is None:
                    error_message = err_detail
                else:
                    error_message += f"; {err_detail}"
            elif isinstance(response, dict) and "results" in response:
                # Extract the actual search result content
                # Assuming response structure is like {'results': [{'content': ...}, ...]}
                processed_results = [
                    res.get("content", "")
                    for res in response.get("results", [])
                    if res.get("content")  # Ensure content is not None or empty
                ]
                search_results_content.extend(processed_results)
                logger.debug(
                    f"Successfully processed results for query: '{query_attempted}'"
                )
            else:
                logger.warning(
                    f"Unexpected response type or structure for query '{query_attempted}': {type(response)}"
                )
                if error_message is None:
                    error_message = f"Unexpected response for '{query_attempted}'"
                else:
                    error_message += f"; Unexpected response for '{query_attempted}'"

    except Exception as e:
        # Catch potential errors in gather itself
        logger.error(f"Critical error during asyncio.gather for Tavily searches: {e}")
        # Return an error state immediately
        return {
            "search_results": [],
            "search_queries": executed_queries,
            "error_message": f"Core search execution error: {e}",
        }

    logger.info(
        f"Aggregated {len(search_results_content)} search results from {len(executed_queries)} queries."
    )
    return {
        "search_results": search_results_content,
        "search_queries": executed_queries,
        "error_message": error_message,
    }


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
                "duration": "N/A",  # Keep consistent keys
                "learning_objectives": ["Generation failed"],
                "modules": [
                    {
                        "title": "Generation Failed",
                        "summary": "Fallback due to error.",
                        "lessons": [],
                    }
                ],
            },
            "error_message": "LLM model not configured.",
            "error_generating": True,
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
    response = None  # Initialize response
    try:
        logger.info("Sending generation request to LLM...")
        response = call_with_retry(llm_model.generate_content, prompt)
        response_text = response.text
        logger.info("LLM response received.")
    except Exception as e:
        logger.error(f"LLM call failed during syllabus generation: {e}", exc_info=True)
        response_text = (
            f"LLM Error: {e}"  # Store error in response_text for fallback message
        )

    syllabus = _parse_llm_json_response(response)  # Pass the raw response object

    if syllabus and _validate_syllabus_structure(syllabus, "Generated"):
        return {
            "generated_syllabus": syllabus,
            "error_message": None,
            "error_generating": False,
        }
    else:
        logger.warning(
            "Using fallback syllabus structure due to generation/parsing/validation error."
        )
        # Construct fallback syllabus
        fallback_syllabus = {
            "topic": topic,
            "level": knowledge_level,  # Use level from state
            "duration": "4 weeks (estimated)",
            "learning_objectives": [
                f"Understand basic concepts of {topic}.",
                "Identify key components or principles.",
            ],
            "modules": [
                {
                    # "unit": 1, # Remove unit if not standard
                    "title": f"Introduction to {topic}",
                    "summary": "Basic concepts and overview.",  # Add summary
                    "lessons": [
                        {
                            "title": "What is " + topic + "?",
                            "summary": "Definition and scope.",
                            "duration": 10,
                        },
                        {
                            "title": "Core Terminology",
                            "summary": "Key terms explained.",
                            "duration": 15,
                        },
                        {
                            "title": "Real-world Examples",
                            "summary": "Applications in practice.",
                            "duration": 10,
                        },
                    ],
                },
                {
                    # "unit": 2,
                    "title": f"Fundamental Principles of {topic}",
                    "summary": "Underlying rules and concepts.",  # Add summary
                    "lessons": [
                        {
                            "title": "Principle A",
                            "summary": "Explanation of Principle A.",
                            "duration": 20,
                        },
                        {
                            "title": "Principle B",
                            "summary": "Explanation of Principle B.",
                            "duration": 15,
                        },
                        {
                            "title": "How Principles Interact",
                            "summary": "Combining principles.",
                            "duration": 10,
                        },
                    ],
                },
            ],
        }
        return {
            "generated_syllabus": fallback_syllabus,
            "error_message": (
                f"LLM call failed or returned empty/invalid JSON: {response_text[:200]}..."
                if response_text
                else "LLM call failed or returned empty."
            ),
            "error_generating": True,
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
            # Return original syllabus on error
            "generated_syllabus": state.get("generated_syllabus")
            or state.get("existing_syllabus"),
            "user_feedback": feedback,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "error_message": "LLM model not configured.",
            "error_generating": True,  # Indicate error occurred
        }

    iteration = state.get("iteration_count", 0) + 1
    logger.info(f"Updating syllabus based on feedback (Iteration {iteration})")
    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    current_syllabus = state.get("generated_syllabus") or state.get("existing_syllabus")

    if not current_syllabus:
        logger.error("Error: Cannot update syllabus as none exists in state.")
        return {
            "generated_syllabus": current_syllabus,  # Return original (None)
            "iteration_count": iteration,
            "error_message": "No syllabus content found in state to update.",
            "error_generating": True,
        }

    try:
        if not isinstance(current_syllabus, dict):
            raise TypeError(
                f"Expected dict for current_syllabus, got {type(current_syllabus)}"
            )
        syllabus_json = json.dumps(current_syllabus, indent=2)
    except TypeError as e:
        logger.error(f"Error serializing current syllabus to JSON for update: {e}")
        return {
            "generated_syllabus": current_syllabus,  # Return original
            "iteration_count": iteration,
            "error_message": f"Error serializing current syllabus: {e}",
            "error_generating": True,
        }

    prompt = UPDATE_PROMPT_TEMPLATE.format(
        topic=topic,
        knowledge_level=knowledge_level,
        syllabus_json=syllabus_json,
        feedback=feedback,
    )

    response_text = ""
    response = None  # Initialize response
    try:
        logger.info("Sending update request to LLM...")
        response = call_with_retry(llm_model.generate_content, prompt)
        response_text = response.text
        logger.info("LLM update response received.")
    except Exception as e:
        logger.error(f"LLM call failed during syllabus update: {e}", exc_info=True)
        response_text = (
            f"LLM Error: {e}"  # Store error in response_text for fallback message
        )

    updated_syllabus = _parse_llm_json_response(response)  # Pass raw response

    if updated_syllabus and _validate_syllabus_structure(updated_syllabus, "Updated"):
        return {
            "generated_syllabus": updated_syllabus,
            "user_feedback": feedback,
            "iteration_count": iteration,
            "error_message": None,  # Clear previous error on success
            "error_generating": False,  # Clear error flag
        }
    else:
        error_msg = f"Update failed (parsing/validation error). LLM Response: {response_text[:200]}..."
        logger.warning(error_msg)
        return {
            "generated_syllabus": current_syllabus,  # Return original on failure
            "user_feedback": feedback,
            "iteration_count": iteration,
            "error_message": error_msg,
            "error_generating": True,  # Set error flag
        }


# pylint: disable=too-many-return-statements, too-many-locals, too-many-branches
def save_syllabus(state: SyllabusState) -> Dict[str, Any]:
    """Saves the current syllabus (generated or existing) to the database using Django ORM."""
    # db_service parameter removed
    syllabus_to_save = state.get(
        "generated_syllabus"
    )  # Prioritize generated for saving/updating
    if not syllabus_to_save:
        # If no generated, check if existing should be saved (e.g., after cloning, though cloning should use save node ideally)
        # For now, primarily save generated content.
        logger.warning("No generated syllabus found in state to save.")
        return {
            "syllabus_saved": False,
            "saved_uid": None,
            "error_message": "No generated syllabus content found in state.",
        }

    # Ensure syllabus_to_save is a dictionary before proceeding
    if not isinstance(syllabus_to_save, dict):
        error_msg = f"Invalid format for syllabus_to_save: Expected dict, got {type(syllabus_to_save)}."
        logger.error(error_msg)
        return {"syllabus_saved": False, "saved_uid": None, "error_message": error_msg}

    user_entered_topic = state.get("user_entered_topic", syllabus_to_save.get("topic"))
    user_id = state.get("user_id")
    logger.info(f"Save Attempt: User={user_id}, Topic='{user_entered_topic}'")

    try:
        syllabus_dict = syllabus_to_save.copy()  # Already checked it's a dict

        topic_str = syllabus_dict.get("topic")
        level_str = syllabus_dict.get("level")
        modules_data = syllabus_dict.get("modules", [])

        # Validate required keys before proceeding (using keys from _validate_syllabus_structure)
        required_keys = ["topic", "level", "duration", "learning_objectives", "modules"]
        missing_keys = [k for k in required_keys if k not in syllabus_dict]
        if missing_keys:
            error_msg = (
                f"Syllabus data missing required keys: {', '.join(missing_keys)}."
            )
            logger.error(error_msg)
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }

        if not isinstance(topic_str, str) or not isinstance(level_str, str):
            error_msg = f"Syllabus 'topic' or 'level' is not a string: {syllabus_dict}"
            logger.error(error_msg)
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }
        if not isinstance(modules_data, list):
            error_msg = f"Syllabus 'modules' is not a list: {syllabus_dict}"
            logger.error(error_msg)
            return {
                "syllabus_saved": False,
                "saved_uid": None,
                "error_message": error_msg,
            }

        # Get user object
        user_obj = None
        if user_id:
            try:
                user_obj = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                error_msg = f"User with ID {user_id} not found. Cannot save syllabus for this user."
                logger.error(error_msg)
                # Don't save as master, return error
                return {
                    "syllabus_saved": False,
                    "saved_uid": None,
                    "error_message": error_msg,
                }
            except ValueError as e:  # Catch invalid PK format during User.objects.get
                error_msg = f"Invalid User ID format '{user_id}': {e}"
                logger.error(error_msg)
                return {
                    "syllabus_saved": False,
                    "saved_uid": None,
                    "error_message": error_msg,
                }

        # Prepare defaults for update_or_create
        defaults = {
            "user_entered_topic": user_entered_topic,
            # Add other fields from syllabus_dict that map directly to Syllabus model fields
            # 'duration': syllabus_dict.get('duration'), # Removed: Not on Syllabus model
            # 'learning_objectives': syllabus_dict.get('learning_objectives', []), # Removed: Not on Syllabus model
        }

        # Use UID from state if available for update, otherwise create based on topic/level/user
        uid_to_update = state.get("uid")
        if uid_to_update:
            logger.info(
                f"Attempting to update existing syllabus with UID: {uid_to_update}"
            )
            syllabus_instance, created = (
                Syllabus.objects.update_or_create(  # pylint: disable=no-member
                    syllabus_id=uid_to_update,  # Use UID for lookup
                    defaults={
                        "topic": topic_str,
                        "level": level_str,
                        "user": user_obj,
                        **defaults,  # Include other defaults
                    },
                )
            )
        else:
            logger.info("Attempting to create new syllabus.")
            syllabus_instance, created = (
                Syllabus.objects.update_or_create(  # pylint: disable=no-member
                    topic=topic_str, level=level_str, user=user_obj, defaults=defaults
                )
            )
        action = "Created" if created else "Updated"
        logger.info(f"{action} syllabus record ID: {syllabus_instance.syllabus_id}")

        # Clear existing modules/lessons before adding new ones
        syllabus_instance.modules.all().delete()  # type: ignore[attr-defined] # Mypy struggles with reverse relations

        # Create Module and Lesson objects
        for module_index, module_data in enumerate(modules_data):
            if not isinstance(module_data, dict):
                logger.warning(
                    f"Skipping invalid module data (not a dict) at index {module_index}"
                )
                continue

            module_title = module_data.get("title", f"Untitled Module {module_index+1}")
            module_summary = module_data.get("summary", "")
            lessons_data = module_data.get("lessons", [])

            module_instance = Module.objects.create(  # pylint: disable=no-member
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
                lesson_duration = lesson_data.get("duration")  # Can be None

                Lesson.objects.create(  # pylint: disable=no-member
                    module=module_instance,
                    lesson_index=lesson_index,
                    title=lesson_title,
                    summary=lesson_summary,
                    duration=lesson_duration,
                )

        # Return success state
        saved_uid = str(syllabus_instance.syllabus_id)
        return {
            "syllabus_saved": True,
            "saved_uid": saved_uid,
            "uid": saved_uid,  # Update UID in state
            "error_message": None,  # Clear error on success
        }
    except Exception as e:
        logger.error(f"Error saving syllabus to database: {e}", exc_info=True)
        return {
            "syllabus_saved": False,
            "saved_uid": None,
            "error_message": f"DB save error: {e}",
        }


def end_node(state: SyllabusState) -> SyllabusState:
    """End node for the graph, simply returns the final state."""
    logger.info("Workflow ended.")
    return state
