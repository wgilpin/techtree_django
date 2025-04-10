from asgiref.sync import sync_to_async, async_to_sync
"""
Service layer for handling lesson content generation.

This module contains the logic for generating lesson exposition content using LLMs,
extracted from the main lessons service module.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

# pylint: disable=no-member
from asgiref.sync import sync_to_async
from django.conf import settings
from google.api_core.exceptions import GoogleAPIError
from langchain_google_genai import ChatGoogleGenerativeAI

from core.constants import DIFFICULTY_VALUES
from core.models import Lesson, LessonContent, Syllabus
from syllabus.ai.utils import call_with_retry  # type: ignore # Re-use retry logic

from .ai.prompts import GENERATE_LESSON_CONTENT_PROMPT, LATEX_FORMATTING_INSTRUCTIONS

logger = logging.getLogger(__name__)

async def _ainvoke_llm(llm, prompt):
    return await llm.ainvoke(prompt)



async def trigger_first_lesson_generation(syllabus_id: uuid.UUID) -> None:  # type: ignore
    """
    Triggers the generation of the first lesson's content for a given syllabus asynchronously.

    Finds the first lesson (module 0, lesson 0), checks if content exists or is generating.
    If not, creates a placeholder and launches the generation task.
    """
    logger.info("Triggering first lesson generation for Syllabus ID: %s", syllabus_id)
    try:
        # Find the first lesson (assuming module_index=0, lesson_index=0)
        # Use async ORM and prefetch related syllabus
        first_lesson = (
            await Lesson.objects.select_related("module__syllabus")
            .filter(
                module__syllabus_id=syllabus_id, module__module_index=0, lesson_index=0
            )
            .afirst()
        )  # Use async ORM

        if not first_lesson:
            logger.warning(
                "Could not find the first lesson (0, 0) for Syllabus ID: %s. Cannot trigger generation.",
                syllabus_id,
            )
            return

        logger.info(
            "Found first lesson (ID: %s) for Syllabus ID: %s",
            first_lesson.pk,
            syllabus_id,
        )

        # Check existing content status using async ORM
        existing_content = await LessonContent.objects.filter(
            lesson=first_lesson
        ).afirst()

        if existing_content:
            if existing_content.status == LessonContent.StatusChoices.COMPLETED:
                logger.info(
                    "Content for first lesson %s already exists and is COMPLETED. No action needed.",
                    first_lesson.pk,
                )
                return
            elif existing_content.status == LessonContent.StatusChoices.GENERATING:
                logger.info(
                    "Content generation for first lesson %s is already IN PROGRESS. No action needed.",
                    first_lesson.pk,
                )
                return
            elif existing_content.status == LessonContent.StatusChoices.FAILED:
                logger.info(
                    "Content generation for first lesson %s previously FAILED. Retrying generation.",
                    first_lesson.pk,
                )
                # Allow generation to proceed by falling through
            else:  # PENDING or other status
                logger.info(
                    "Content for first lesson %s exists but status is %s. Triggering generation.",
                    first_lesson.pk,
                    existing_content.status,
                )
                # Allow generation to proceed by falling through

        # If no suitable content exists, trigger generation asynchronously
        # get_or_create_lesson_content (async version) handles placeholder creation
        logger.info(
            "Creating asyncio task to generate content for first lesson %s.",
            first_lesson.pk,
        )
        # Create the task to run the async generation function
        asyncio.create_task(get_or_create_lesson_content(first_lesson))
        logger.info("Async task for lesson %s generation created.", first_lesson.pk)

    except Syllabus.DoesNotExist:  # Should not happen with filter but good practice
        logger.error("Syllabus with ID %s not found.", syllabus_id)
    except Exception as e:
        logger.error(
            "Unexpected error in trigger_first_lesson_generation for Syllabus ID %s: %s",
            syllabus_id,
            e,
            exc_info=True,
        )


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


async def get_or_create_lesson_content(lesson: Lesson) -> Optional[LessonContent]:
    """
    Retrieves the LessonContent for a given Lesson asynchronously, generating it if necessary.

    Checks for existing COMPLETED or GENERATING content first.
    If neither exists, creates a GENERATING placeholder, generates content via LLM,
    and updates the placeholder status to COMPLETED or FAILED.

    Args:
        lesson: The Lesson object for which to get content.

    Returns:
        The existing or newly created/updated LessonContent object, or None if generation fails critically.
    """
    logger.info(
        "Async check/generate content for Lesson ID: %s (%s)", lesson.pk, lesson.title
    )
    placeholder: Optional[LessonContent] = None

    try:
        # 1. Check for existing COMPLETED content (async)
        existing_completed = await LessonContent.objects.filter(  # type: ignore[misc]
            lesson=lesson,
            status=LessonContent.StatusChoices.COMPLETED.value,  # Use string value
        ).afirst()
        if existing_completed:
            logger.info("Found existing COMPLETED content for Lesson ID: %s", lesson.pk)
            return existing_completed

        # 2. Check for existing FAILED content (async) - retry if found
        existing_failed = await LessonContent.objects.filter(  # type: ignore[misc]
            lesson=lesson,
            status=LessonContent.StatusChoices.FAILED.value,  # Use string value
        ).afirst()
        if existing_failed:
            logger.info(
                "Found FAILED content for Lesson ID: %s - will retry generation", lesson.pk
            )
            # Update status to GENERATING to retry
            existing_failed.status = LessonContent.StatusChoices.GENERATING
            await existing_failed.asave(update_fields=["status", "updated_at"])
            # Continue with generation using this as the placeholder
            placeholder = existing_failed

        # 3. Check for existing GENERATING content (async)
        if not placeholder:  # Only check if we didn't find a FAILED one to retry
            existing_generating = await LessonContent.objects.filter(  # type: ignore[misc]
                lesson=lesson,
                status=LessonContent.StatusChoices.GENERATING.value,  # Use string value
            ).afirst()
            if existing_generating:
                logger.info(
                    "Content generation already IN PROGRESS for Lesson ID: %s", lesson.pk
                )
                # Return the placeholder to indicate it's being worked on
                return existing_generating

        # 4. If no existing content found, create a new placeholder (async)
        if not placeholder:
            # aupdate_or_create is atomic for its operation.
            placeholder, created = await LessonContent.objects.aupdate_or_create(
                lesson=lesson,
                defaults={
                    "content": {
                        "status": "placeholder",
                        "message": "Content generation initiated.",
                    },
                    "status": LessonContent.StatusChoices.GENERATING,
                },
            )
            if created:
                logger.info(
                    "Created GENERATING placeholder (ID: %s) for Lesson ID: %s",
                    placeholder.pk,
                    lesson.pk,
                )
            else:
                logger.info(
                    "Updated existing record (ID: %s) to GENERATING for Lesson ID: %s",
                    placeholder.pk,
                    lesson.pk,
                )

        # --- Content Generation Logic (moved inside try block) ---
        # 4. Gather context (wrap sync calls)
        module = await sync_to_async(lambda: lesson.module)()
        syllabus = await sync_to_async(lambda: module.syllabus)()  # type: ignore[attr-defined]
        topic = await sync_to_async(lambda: syllabus.topic)()
        level = await sync_to_async(lambda: syllabus.level)()
        lesson_title = await sync_to_async(lambda: lesson.title)()
        # Fetching syllabus structure can remain sync for now
        # Run sync helper in async context
        syllabus_structure = await sync_to_async(_fetch_syllabus_structure)(syllabus)
        try:
            syllabus_structure_json = json.dumps(syllabus_structure, indent=2)
        except TypeError as json_err:
            logger.error(
                "Failed to serialize syllabus structure for lesson %s: %s",
                lesson.pk,
                json_err,
                exc_info=True,
            )
            # Update placeholder to FAILED
            assert placeholder is not None  # Help mypy
            placeholder.status = LessonContent.StatusChoices.FAILED
            placeholder.content = {"error": "Failed to serialize syllabus structure."}
            await placeholder.asave(update_fields=["status", "content", "updated_at"])
            return placeholder  # Return failed placeholder

        # 5. Initialize LLM (remains synchronous)
        llm = _get_llm()
        if not llm:
            logger.error(
                "LLM could not be initialized. Cannot generate content for lesson %s.",
                lesson.pk,
            )
            # Update placeholder to FAILED
            assert placeholder is not None  # Help mypy
            placeholder.status = LessonContent.StatusChoices.FAILED
            placeholder.content = {"error": "LLM initialization failed."}
            await placeholder.asave(update_fields=["status", "content", "updated_at"])
            return placeholder  # Return failed placeholder
        logger.info("LLM initialized successfully for lesson %s.", lesson.pk)

        # 6. Format Prompt (remains synchronous)
        difficulty_value = DIFFICULTY_VALUES.get(level)
        if difficulty_value is None:
            logger.warning(
                "Difficulty level '%s' not found. Using default word count.", level
            )
            word_count = 400
        else:
            word_count = (difficulty_value + 1) * 200

        prompt_input = {
            "topic": topic,
            "level_name": level,
            "levels_list": list(DIFFICULTY_VALUES.keys()),  # Add available levels
            "word_count": word_count,
            "lesson_title": lesson_title,
            "syllabus_structure_json": syllabus_structure_json,
            "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
        }
        formatted_prompt = GENERATE_LESSON_CONTENT_PROMPT.format(**prompt_input)

        # 7. Call LLM with retry (needs to be async)
        logger.info("Calling LLM async to generate content for lesson %s...", lesson.pk)
        generated_text = ""
        llm_error = None
        try:
            # Use await with the async version of call_with_retry if available,
            # or run the sync llm.invoke in an executor if call_with_retry is sync.
            # Use the async invoke method directly
            response = await llm.ainvoke(formatted_prompt)
            generated_text = (
                str(response.content).strip() if hasattr(response, "content") else ""
            )
            if not generated_text:
                logger.warning("LLM returned empty content for lesson %s.", lesson.pk)
                # Treat as failure? Or just empty content? Let's treat as failure for now.
                llm_error = "LLM returned empty content."

        except GoogleAPIError as e:
            llm_error = f"Google API error during LLM call: {e}"
            logger.error("%s for lesson %s", llm_error, lesson.pk, exc_info=True)
        except Exception as e:
            llm_error = f"LLM invocation failed: {e}"
            logger.error("%s for lesson %s", llm_error, lesson.pk, exc_info=True)

        # 8. Process response and update placeholder (async)
        # asave is atomic for its operation.
        # Reload placeholder to ensure we have the latest version before updating
        assert placeholder is not None  # Help mypy before accessing pk
        placeholder = await LessonContent.objects.aget(pk=placeholder.pk)

        if llm_error:
            assert placeholder is not None  # Help mypy
            placeholder.status = LessonContent.StatusChoices.FAILED
            placeholder.content = {"error": llm_error}
            await placeholder.asave(update_fields=["status", "content", "updated_at"])
            logger.error(
                "Marked content generation as FAILED for lesson %s.", lesson.pk
            )
            return placeholder  # Return failed placeholder

        # Process successful response (remains mostly synchronous logic)
        content_data = {}
        try:
            # Clean potential markdown code fences
            cleaned_text = generated_text
            if cleaned_text.startswith("```json"):
                cleaned_text = (
                    cleaned_text.removeprefix("```json").removesuffix("```").strip()
                )
            elif cleaned_text.startswith("```"):
                pass
            cleaned_text = (
                cleaned_text.removeprefix("```").removesuffix("```").strip()
            )

            # Try JSON parsing
            try:  # Attempt to update the placeholder status atomically
                parsed_data = json.loads(cleaned_text)
                if isinstance(parsed_data, dict):
                    exposition_content = parsed_data.get("exposition", "")
                    content_data = {"exposition": exposition_content}
                    logger.info(
                        "Successfully extracted exposition via JSON for lesson %s.",
                        lesson.pk,
                    )
                else:
                    logger.warning(
                        "LLM JSON output not a dict for lesson %s.", lesson.pk
                    )
                    content_data = {
                        "error": "LLM output parsed but not a dictionary.",
                        "raw_response": cleaned_text,
                    }
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse LLM output as JSON for lesson %s.", lesson.pk)
            placeholder.content = content_data
            placeholder.status = LessonContent.StatusChoices.COMPLETED
            await placeholder.asave(update_fields=["content", "status", "updated_at"])
            return placeholder
        except Exception:
            pass

        # Update placeholder with final content and status
        placeholder.content = content_data
        # Check if content_data indicates an error during processing
        logger.info('DEBUG: Saving content_data = %s', content_data)
        if "error" in content_data:
            assert placeholder is not None  # Help mypy
            placeholder.status = LessonContent.StatusChoices.FAILED
            logger.error(
                "Marked content generation as FAILED due to processing error for lesson %s.",
                lesson.pk,
            )
        else:
            assert placeholder is not None  # Help mypy
            placeholder.status = LessonContent.StatusChoices.COMPLETED
            logger.info(
                "Successfully generated content for lesson %s. Marking COMPLETED.",
                lesson.pk,
            )

        # Correct indentation for save and return
        await placeholder.asave(update_fields=["content", "status", "updated_at"])
        return placeholder  # Return the final updated placeholder

    except Exception as e:
        logger.error(
            "Unexpected error in get_or_create_lesson_content for Lesson ID %s: %s",
            lesson.pk,
            e,
            exc_info=True,
        )
        # If an outer exception occurred, try to mark the placeholder as FAILED
        if placeholder:
            try:
                # Reload placeholder to ensure we have the latest version before updating,
                # especially if the error occurred during an async operation.
                placeholder = await LessonContent.objects.aget(pk=placeholder.pk)
                # Use string literal for status check here as well
                if placeholder.status != "COMPLETED":
                    placeholder.status = LessonContent.StatusChoices.FAILED
                    placeholder.content = {"error": f"Outer exception: {str(e)}"}
                    await placeholder.asave(
                        update_fields=["status", "content", "updated_at"]
                    )
                    logger.error(
                        "Marked content generation as FAILED due to outer exception for lesson %s.",
                        placeholder.lesson_id,
                    )
            except Exception as update_err:
                logger.error(
                    "Failed to mark placeholder as FAILED for lesson %s after outer exception: %s",
                    placeholder.lesson_id,
                    update_err,
                    exc_info=True,
                )
            # --- FIX: Always return the placeholder if it exists ---
            return placeholder  # Return the placeholder regardless of update success/failure
        else:  # Handle case where outer exception occurred and placeholder is None
            logger.warning(
                "Outer exception caught in get_or_create_lesson_content before placeholder assignment for lesson %s.",
                lesson.pk,
            )
            return None  # Return None explicitly ONLY when placeholder is None in outer except
    return None  # Explicit final return to satisfy mypy, though logically unreachable
