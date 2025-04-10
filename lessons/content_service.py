"""
Service layer for handling lesson content generation.

This module contains the logic for generating lesson exposition content using LLMs,
extracted from the main lessons service module.
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

# pylint: disable=no-member
from django.conf import settings
from google.api_core.exceptions import GoogleAPIError
from langchain_google_genai import ChatGoogleGenerativeAI

from core.constants import DIFFICULTY_VALUES
from core.models import Lesson, LessonContent, Syllabus
from syllabus.ai.utils import call_with_retry  # type: ignore # Re-use retry logic

from .ai.prompts import GENERATE_LESSON_CONTENT_PROMPT, LATEX_FORMATTING_INSTRUCTIONS

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


