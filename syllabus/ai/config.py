"""Configuration for syllabus generation external APIs."""

# pylint: disable=broad-exception-caught

import os
import logging # Use standard logging
from typing import Optional  # Import Optional

import google.generativeai as genai
# from dotenv import load_dotenv # Settings are loaded via django-environ in settings.py
from tavily import TavilyClient  # type: ignore
from django.conf import settings # Import Django settings

from core.exceptions import log_and_raise_new, ConfigurationError # Import necessary exceptions/helpers

logger = logging.getLogger(__name__) # Get logger for this module

# Environment variables are loaded via django-environ in settings.py
# load_dotenv() # Removed

# Define type hints before assignment
MODEL: Optional[genai.GenerativeModel] = None  # type: ignore[name-defined]
TAVILY: Optional[TavilyClient] = None

try:
    # Use settings loaded by django-environ
    gemini_api_key = settings.GEMINI_API_KEY
    gemini_model_name = settings.LARGE_MODEL # Use LARGE_MODEL for syllabus generation
    if not gemini_api_key:
        # Use ConfigurationError instead of KeyError for better context
        log_and_raise_new(
            exception_type=ConfigurationError,
            exception_message="Missing environment variable: GEMINI_API_KEY",
            exc_info=False
        )
    if not gemini_model_name:
        # Check settings.LARGE_MODEL
        log_and_raise_new(
            exception_type=ConfigurationError,
            exception_message="Django setting LARGE_MODEL is not configured in .env or settings.",
            exc_info=False # Restore exc_info argument
        )
    # If the code reaches here, gemini_model_name must be set
    assert isinstance(gemini_model_name, str), "settings.LARGE_MODEL must be a string after check" # Help Mypy

    genai.configure(api_key=gemini_api_key)  # type: ignore[attr-defined]
    MODEL = genai.GenerativeModel(gemini_model_name)  # type: ignore[attr-defined]
    logger.info(f"Syllabus Config: Gemini model '{gemini_model_name}' (from LARGE_MODEL setting) configured.")
except ConfigurationError as e: # Catch the specific exception raised
    # The log_and_raise_new function already logs the error, so just pass here.
    # logger.error(f"Syllabus Config: Gemini configuration failed: {e}") # Redundant logging
    MODEL = None
except Exception as e:
    logger.error(f"Syllabus Config: Error configuring Gemini: {e}", exc_info=True)
    MODEL = None

# Configure Tavily API
try:
    # Use settings loaded by django-environ
    tavily_api_key = settings.TAVILY_API_KEY
    if not tavily_api_key:
        logger.warning(
            "Django setting TAVILY_API_KEY is not configured. Tavily search disabled."
        )
    else:
        TAVILY = TavilyClient(api_key=tavily_api_key)
        logger.info("Syllabus Config: Tavily client configured.")
except Exception as e:
    logger.error(f"Syllabus Config: Error configuring Tavily: {e}", exc_info=True)
    TAVILY = None
