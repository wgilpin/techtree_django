"""
Synchronous lesson content generation processor for background task execution.
"""

import json

from core.constants import DIFFICULTY_VALUES
from core.models import Lesson, LessonContent
from lessons.content_service import _fetch_syllabus_structure, _get_llm
from lessons.ai.prompts import (
        GENERATE_LESSON_CONTENT_PROMPT,
        LATEX_FORMATTING_INSTRUCTIONS,
    )

def process_lesson_content(task):
    """
    Process a lesson content generation task synchronously.
    """
    lesson_id = task.input_data.get("lesson_id")

    lesson = Lesson.objects.get(pk=lesson_id)  # pylint: disable=no-member
    module = lesson.module
    syllabus = module.syllabus

    lesson_content, _ = LessonContent.objects.get_or_create(
        lesson=lesson,
        defaults={
            "content": {"status": "placeholder"},
            "status": LessonContent.StatusChoices.GENERATING,
        },
    )

    llm = _get_llm()
    if not llm:
        raise ValueError("LLM could not be initialized")

    topic = syllabus.topic
    level = syllabus.level
    lesson_title = lesson.title
    syllabus_structure = _fetch_syllabus_structure(syllabus)
    syllabus_structure_json = json.dumps(syllabus_structure, indent=2)

    difficulty_value = DIFFICULTY_VALUES.get(level)
    if difficulty_value is None:
        word_count = 400
    else:
        word_count = (difficulty_value + 1) * 200


    prompt_input = {
        "topic": topic,
        "level_name": level,
        "levels_list": list(DIFFICULTY_VALUES.keys()),
        "word_count": word_count,
        "lesson_title": lesson_title,
        "syllabus_structure_json": syllabus_structure_json,
        "latex_formatting_instructions": LATEX_FORMATTING_INSTRUCTIONS,
    }
    formatted_prompt = GENERATE_LESSON_CONTENT_PROMPT.format(**prompt_input)

    response = llm.invoke(formatted_prompt)
    generated_text = (
        str(response.content).strip() if hasattr(response, "content") else ""
    )

    content_data = {}
    if generated_text:
        cleaned_text = generated_text
        if cleaned_text.startswith("```json"):
            cleaned_text = (
                cleaned_text.removeprefix("```json").removesuffix("```").strip()
            )
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text.removeprefix("```").removesuffix("```").strip()

        try:
            parsed_data = json.loads(cleaned_text)
            if isinstance(parsed_data, dict):
                exposition_content = parsed_data.get("exposition", "")
                content_data = {"exposition": exposition_content}
            else:
                content_data = {
                    "error": "LLM output parsed but not a dictionary.",
                    "raw_response": cleaned_text,
                }
        except json.JSONDecodeError:
            content_data = {
                "error": "Failed to parse LLM output as JSON.",
                "raw_response": cleaned_text,
            }

    lesson_content.content = content_data
    if "error" in content_data:
        lesson_content.status = LessonContent.StatusChoices.FAILED
    else:
        lesson_content.status = LessonContent.StatusChoices.COMPLETED
    lesson_content.save()

    return content_data
