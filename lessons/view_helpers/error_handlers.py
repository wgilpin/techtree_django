""" error handlers for lessons/views.py """

import logging

from django.http import HttpResponse
from django.shortcuts import render


logger = logging.getLogger(__name__)

def _handle_lesson_detail_error(error, syllabus_id, module_index, lesson_index, request=None, status=500):
    """Handle errors in lesson_detail view with consistent logging and responses."""
    if status == 404:
        logger.warning(
            "Resource not found in lesson_detail view: %s:%s:%s - %s",
            syllabus_id,
            module_index,
            lesson_index,
            error,
        )
        return HttpResponse("Lesson not found", status=404)
    
    logger.error(
        "Error in lesson_detail view for %s:%s:%s: %s",
        syllabus_id,
        module_index,
        lesson_index,
        error,
        exc_info=True,
    )
    return _create_fallback_response(request, status)

def _create_fallback_response(request, status):
    """Create a fallback response with dummy data for error scenarios."""
    class Dummy:
        def __init__(self, pk):
            self.pk = pk
            self.module_index = 0
            self.lesson_index = 0
            self.title = ""
            self.summary = ""

    dummy_uuid = "00000000-0000-0000-0000-000000000000"
    return render(
        request,
        "lessons/lesson_detail.html",
        {
            "syllabus": Dummy(dummy_uuid),
            "module": Dummy(dummy_uuid),
            "lesson": Dummy(dummy_uuid),
            "progress": None,
            "title": "Lesson",
            "exposition_content": None,
            "content_status": "ERROR",
            "absolute_lesson_number": None,
            "conversation_history": [],
            "lesson_state_json": "{}",
            "LessonContentStatus": {
                "COMPLETED": "COMPLETED",
                "GENERATING": "GENERATING",
                "FAILED": "FAILED",
                "PENDING": "PENDING",
            },
            "trigger_regeneration": False,
            "regeneration_url": None,
        },
        status=status
    )
