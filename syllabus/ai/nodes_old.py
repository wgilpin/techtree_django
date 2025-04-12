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
from tavily import TavilyClient  # type: ignore

from backend.logger import logger  # Import logger
# Project specific imports
from backend.services.sqlite_db import SQLiteDatabaseService

from .prompts import GENERATION_PROMPT_TEMPLATE, UPDATE_PROMPT_TEMPLATE
from .state import SyllabusState
from .utils import call_with_retry

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

    valid_levels = ["beginner", "early learner", "good knowledge", "advanced"]
    if knowledge_level not in valid_levels:
        logger.warning(f"Invalid level '{knowledge_level}'. Defaulting to 'beginner'.")
        knowledge_level = "beginner"

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
        "is_master": None,
        "parent_uid": None,
        "created_at": None,
        "updated_at": None,
    }
    return initial_state


def search_database(
    state: SyllabusState, db_service: SQLiteDatabaseService
) -> Dict[str, Any]:  # Changed return type hint
    """Searches the database for an existing syllabus matching the criteria."""
    topic = state["topic"]
    knowledge_level = state["user_knowledge_level"]
    user_id = state.get("user_id")
    logger.info(
        f"DB Search: Topic='{topic}', Level='{knowledge_level}', User={user_id}"
    )

    found_syllabus = db_service.get_syllabus(topic, knowledge_level, user_id)

    if found_syllabus:
        # Ensure found_syllabus is treated as a dictionary
        syllabus_data = dict(found_syllabus)
        logger.info(f"Found existing syllabus in DB. UID: {syllabus_data.get('uid')}")
        # Ensure return matches Dict[str, Any]
        return {
            "existing_syllabus": syllabus_data,
            "uid": syllabus_data.get("uid"),
            "is_master": syllabus_data.get("is_master"),
            "parent_uid": syllabus_data.get("parent_uid"),
            "created_at": syllabus_data.get("created_at"),
            "updated_at": syllabus_data.get("updated_at"),
            "user_entered_topic": state.get("user_entered_topic", topic),
            "topic": syllabus_data.get("topic", topic),
            "user_knowledge_level": syllabus_data.get("level", knowledge_level),
        }
    else:
        logger.info("No matching syllabus found in DB.")
        return {"existing_syllabus": None}


def search_internet(
    state: SyllabusState, tavily_client: Optional[TavilyClient]
) -> Dict[str, List[str]]:  # Changed return type hint
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
    llm_model: Optional[genai.GenerativeModel]  # type: ignore[name-defined]
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


# pylint: disable=too-many-return-statements
def save_syllabus(
    state: SyllabusState, db_service: SQLiteDatabaseService
) -> Dict[str, Any]:  # Changed return type hint
    """Saves the current syllabus (generated or existing) to the database."""
    syllabus_to_save = state.get("generated_syllabus") or state.get("existing_syllabus")
    if not syllabus_to_save:
        logger.warning("No syllabus found in state to save.")
        return {"syllabus_saved": False}

    user_entered_topic = state.get("user_entered_topic", syllabus_to_save.get("topic"))
    user_id = state.get("user_id")
    logger.info(f"Save Attempt: User={user_id}, Topic='{user_entered_topic}'")

    try:
        syllabus_dict = dict(syllabus_to_save).copy()
    except (TypeError, ValueError):
        logger.error(
            f"Error: Cannot convert syllabus type {type(syllabus_to_save)} to dict."
        )
        return {"syllabus_saved": False}

    # Ensure topic and level are strings before passing to db_service
    topic_str = syllabus_dict.get("topic")
    level_str = syllabus_dict.get("level")

    if not isinstance(topic_str, str) or not isinstance(level_str, str):
        logger.error(
            f"Error: Syllabus missing 'topic' or 'level' as strings. Data: {syllabus_dict}"
        )
        return {"syllabus_saved": False}

    now = datetime.now().isoformat()
    syllabus_dict["updated_at"] = now
    if not syllabus_dict.get("created_at"):
        syllabus_dict["created_at"] = now
    if not syllabus_dict.get("uid"):
        syllabus_dict["uid"] = str(uuid.uuid4())
        logger.info(f"Generated new UID for saving: {syllabus_dict['uid']}")

    content_to_save = {
        k: syllabus_dict.get(k)
        for k in ["topic", "level", "duration", "learning_objectives", "modules"]
        if k in syllabus_dict
    }
    if not all(k in content_to_save for k in ["topic", "level", "modules"]):
        logger.error(
            f"Error: Prepared content missing required keys for DB save. Content: {content_to_save}"
        )
        return {"syllabus_saved": False}

    is_master_save = not user_id

    try:
        saved_id = db_service.save_syllabus(
            topic=topic_str,  # Pass validated string
            level=level_str,  # Pass validated string
            content=content_to_save,
            user_id=user_id,
            user_entered_topic=user_entered_topic,
        )

        if saved_id:
            saved_uid = syllabus_dict["uid"]
            logger.info(f"Syllabus UID {saved_uid} saved (DB ID: {saved_id}).")
            return {
                "syllabus_saved": True,
                "saved_uid": saved_uid,
                "uid": saved_uid,
                "created_at": syllabus_dict["created_at"],
                "updated_at": now,
                "is_master": is_master_save,
            }
        else:
            logger.error(
                f"Error: db_service.save_syllabus failed for UID {syllabus_dict['uid']}."
            )
            return {"syllabus_saved": False}

    except Exception as e:
        logger.error(
            f"Error saving syllabus UID {syllabus_dict.get('uid', 'N/A')}: {e}",
            exc_info=True,
        )
        traceback.print_exc()
        return {"syllabus_saved": False}


def end_node(_: SyllabusState) -> Dict[str, Any]:  # Changed return type hint
    """Terminal node for the graph."""
    logger.info("Workflow ended.")
    return {}
