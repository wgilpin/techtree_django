"""
Synchronous syllabus generation processor for background task execution.
"""

import logging
from typing import Dict, Any, Optional

from syllabus.ai.syllabus_graph import SyllabusAI

logger = logging.getLogger(__name__)


def process_syllabus_generation(task):
    """
    Process a syllabus generation task synchronously.
    
    Args:
        task: The AITask instance containing input data for syllabus generation
        
    Returns:
        dict: The generated syllabus data
    """
    # Extract parameters from input_data
    topic = task.input_data.get("topic")
    knowledge_level = task.input_data.get("knowledge_level")
    user_id = task.input_data.get("user_id")
    
    if not topic or not knowledge_level:
        raise ValueError("Missing required parameters: topic and knowledge_level are required")
    
    logger.info(
        f"Processing syllabus generation for topic '{topic}', "
        f"level '{knowledge_level}', user_id '{user_id}'"
    )
    
    # Initialize syllabus AI
    syllabus_ai = SyllabusAI()
    syllabus_ai.initialize(topic, knowledge_level, user_id)
    
    # Run synchronously using the sync method
    try:
        result_state = syllabus_ai.get_or_create_syllabus_sync()
        
        # Extract the syllabus from the state
        syllabus = result_state.get("generated_syllabus") or result_state.get("existing_syllabus")
        
        if not syllabus:
            raise ValueError("Syllabus generation completed but no syllabus was found in the result state")
        
        # Fetch ORM Syllabus object and trigger first lesson content generation
        from core.models import Syllabus, LessonContent
        from taskqueue.models import AITask
        from taskqueue.tasks import process_ai_task

        syllabus_id = result_state.get("syllabus_id")
        if syllabus_id:
            try:
                syllabus_obj = Syllabus.objects.get(pk=syllabus_id)
                first_module = syllabus_obj.modules.filter(module_index=0).first()
                if first_module:
                    first_lesson = first_module.lessons.filter(lesson_index=0).first()
                    if first_lesson:
                        existing_content = LessonContent.objects.filter(
                            lesson=first_lesson,
                            status=LessonContent.StatusChoices.COMPLETED
                        ).first()
                        if not existing_content:
                            lesson_task = AITask.objects.create(
                                task_type=AITask.TaskType.LESSON_CONTENT,
                                input_data={"lesson_id": str(first_lesson.pk)},
                                syllabus=syllabus_obj,
                                lesson=first_lesson,
                                user=task.user if hasattr(task, "user") else None,
                            )
                            process_ai_task(str(lesson_task.task_id))
            except Exception as e:
                logger.error("Error triggering first lesson content generation: %s", e, exc_info=True)

        # Return the syllabus data
        return {
            "syllabus": syllabus,
            "syllabus_id": result_state.get("syllabus_id"),
            "topic": topic,
            "knowledge_level": knowledge_level,
        }
        
    except Exception as e:
        logger.error(f"Error in syllabus generation: {str(e)}", exc_info=True)
        raise