"""Service layer for handling syllabus logic in the Django application."""

# pylint: disable=no-member

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING
from asgiref.sync import sync_to_async

from django.conf import settings
from django.db import transaction

from core.models import Lesson, Module, Syllabus
from core.exceptions import NotFoundError, ApplicationError

from .ai.syllabus_graph import SyllabusAI
from .ai.state import SyllabusState

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Use string literal for User type hint
    pass


class SyllabusService:
    """
    Provides methods for syllabus creation, retrieval, and management using Django ORM
    and the adapted SyllabusAI graph.
    """

    def _get_syllabus_ai_instance(self) -> SyllabusAI:
        """Creates and returns an instance of the SyllabusAI."""
        return SyllabusAI()

    # Make helper async and use sync_to_async for internal ORM access
    async def _format_syllabus_dict(self, syllabus_obj: Syllabus) -> Dict[str, Any]:
        """Formats a Syllabus ORM object into a dictionary structure asynchronously."""

        @sync_to_async
        def get_modules_and_lessons_sync(syllabus):
            """Synchronous helper to fetch related data."""
            modules_list_sync = []
            # Access related managers within the sync context
            # Prefetching should be done in the calling async query
            for module in syllabus.modules.order_by("module_index").all():
                lessons_list_sync = [
                    {
                        "title": lesson.title, "summary": lesson.summary, "duration": lesson.duration,
                        "lesson_index": lesson.lesson_index, "id": lesson.id,
                    }
                    for lesson in module.lessons.order_by("lesson_index").all()
                ]
                modules_list_sync.append({
                    "title": module.title, "summary": module.summary, "lessons": lessons_list_sync,
                    "module_index": module.module_index, "id": module.id,
                })
            return modules_list_sync

        # Await the synchronous helper wrapped in sync_to_async
        modules_list = await get_modules_and_lessons_sync(syllabus_obj)

        user_id_val = None
        if syllabus_obj.user:
            assert syllabus_obj.user is not None
            user_id_val = str(syllabus_obj.user_id)

        return {
            "syllabus_id": str(syllabus_obj.syllabus_id),
            "topic": syllabus_obj.topic,
            "level": syllabus_obj.level,
            "user_entered_topic": syllabus_obj.user_entered_topic,
            "user_id": user_id_val,
            "created_at": syllabus_obj.created_at.isoformat() if syllabus_obj.created_at else None,
            "updated_at": syllabus_obj.updated_at.isoformat() if syllabus_obj.updated_at else None,
            "modules": modules_list,
        }

    async def get_or_generate_syllabus(
        self,
        topic: str,
        level: str,
        user: Optional[settings.AUTH_USER_MODEL], # Use string literal
    ) -> Dict[str, Any]:
        """
        Retrieves a syllabus by topic, level, and user, generating one via AI if it doesn't exist.
        """
        user_pk_str = str(user.pk) if user else "None"
        logger.info(
            f"Attempting to get/generate syllabus: Topic='{topic}', Level='{level}', User='{user_pk_str}'"
        )
        try:
            syllabus_obj = await Syllabus.objects.prefetch_related(
                "modules__lessons" # Ensure prefetch for _format_syllabus_dict
            ).select_related("user").aget(
                topic=topic, level=level, user=user
            )
            logger.info(f"Found existing syllabus ID: {syllabus_obj.syllabus_id}")
            # Await the async helper
            return await self._format_syllabus_dict(syllabus_obj) # type: ignore

        except Syllabus.DoesNotExist as ex:
            logger.info("Syllabus not found. Attempting generation.")
            try:
                syllabus_ai = self._get_syllabus_ai_instance()
                user_id_str = str(user.pk) if user else None
                syllabus_ai.initialize(
                    topic=topic, knowledge_level=level, user_id=user_id_str
                )
                final_state: SyllabusState = await syllabus_ai.get_or_create_syllabus()

                syllabus_content = final_state.get("generated_syllabus") or final_state.get("existing_syllabus")
                saved_uid = final_state.get("uid")

                if not syllabus_content or not isinstance(syllabus_content, dict):
                    logger.error("Syllabus generation failed: No valid syllabus content in final AI state.")
                    raise ApplicationError("Failed to generate syllabus content.") from ex
                if not saved_uid:
                    logger.error("Syllabus generation failed: No UID found in final AI state syllabus data.")
                    raise ApplicationError("Failed to get ID of generated syllabus.") from ex

                syllabus_obj = await Syllabus.objects.prefetch_related(
                    "modules__lessons" # Ensure prefetch for _format_syllabus_dict
                ).select_related("user").aget(
                    pk=saved_uid
                )
                logger.info(f"Successfully generated and saved syllabus ID: {syllabus_obj.syllabus_id}")
                # Await the async helper
                return await self._format_syllabus_dict(syllabus_obj) # type: ignore

            except Exception as e:
                logger.exception(f"Syllabus generation failed: {e}")
                raise ApplicationError(f"Failed to generate syllabus: {e}") from e

    async def get_syllabus_by_id(self, syllabus_id: str) -> Dict[str, Any]:
        """
        Retrieves a specific syllabus by its primary key (UUID).
        """
        logger.info(f"Retrieving syllabus by ID: {syllabus_id}")
        try:
            syllabus_obj = await Syllabus.objects.prefetch_related(
                "modules__lessons" # Ensure prefetch for _format_syllabus_dict
            ).select_related("user").aget(
                pk=syllabus_id
            )
            # Await the async helper
            return await self._format_syllabus_dict(syllabus_obj) # type: ignore
        except Syllabus.DoesNotExist as exc:
            logger.warning(f"Syllabus with ID {syllabus_id} not found.")
            raise NotFoundError(f"Syllabus with ID {syllabus_id} not found.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving syllabus ID {syllabus_id}: {e}")
            raise ApplicationError(f"Error retrieving syllabus: {e}") from e

    async def get_module_details(self, syllabus_id: str, module_index: int) -> Dict[str, Any]:
        """
        Retrieves details for a specific module within a syllabus.
        """
        logger.info(
            f"Retrieving module details: Syllabus ID={syllabus_id}, Module Index={module_index}"
        )
        try:
            module_obj: Module = await Module.objects.select_related(
                "syllabus"
            ).prefetch_related(
                "lessons" # Ensure prefetch for sync access below
            ).aget(
                syllabus_id=syllabus_id, module_index=module_index
            )

            @sync_to_async
            def get_lessons_sync(module):
                lessons_list_sync = [
                    {
                        "title": lesson.title, "summary": lesson.summary, "duration": lesson.duration,
                        "lesson_index": lesson.lesson_index, "id": lesson.id,
                    }
                    for lesson in module.lessons.order_by("lesson_index").all()
                ]
                return lessons_list_sync

            lessons_list = await get_lessons_sync(module_obj)

            return {
                "id": module_obj.id, # type: ignore[attr-defined]
                "syllabus_id": str(module_obj.syllabus.syllabus_id), # type: ignore[attr-defined]
                "module_index": module_obj.module_index,
                "title": module_obj.title,
                "summary": module_obj.summary,
                "lessons": lessons_list,
                "created_at": module_obj.created_at.isoformat() if module_obj.created_at else None,
                "updated_at": module_obj.updated_at.isoformat() if module_obj.updated_at else None,
            }
        except Module.DoesNotExist as exc:
            logger.warning(f"Module not found: Syllabus ID={syllabus_id}, Index={module_index}")
            raise NotFoundError(f"Module {module_index} not found in syllabus {syllabus_id}.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving module details: {e}")
            raise ApplicationError(f"Error retrieving module details: {e}") from e

    async def get_lesson_details(
        self, syllabus_id: str, module_index: int, lesson_index: int
    ) -> Dict[str, Any]:
        """
        Retrieves details for a specific lesson within a syllabus module.
        """
        logger.info(
            f"Retrieving lesson details: Syllabus ID={syllabus_id}, Module Index={module_index}, Lesson Index={lesson_index}"
        )
        try:
            lesson_obj: Lesson = await Lesson.objects.select_related(
                "module__syllabus"
            ).aget(
                module__syllabus_id=syllabus_id,
                module__module_index=module_index,
                lesson_index=lesson_index,
            )
            return {
                "id": lesson_obj.id, # type: ignore[attr-defined]
                "module_id": lesson_obj.module.id, # type: ignore[attr-defined]
                "syllabus_id": str(lesson_obj.module.syllabus.syllabus_id), # type: ignore[attr-defined]
                "lesson_index": lesson_obj.lesson_index,
                "title": lesson_obj.title,
                "summary": lesson_obj.summary,
                "duration": lesson_obj.duration,
                "created_at": lesson_obj.created_at.isoformat() if lesson_obj.created_at else None,
                "updated_at": lesson_obj.updated_at.isoformat() if lesson_obj.updated_at else None,
            }
        except Lesson.DoesNotExist as exc:
            logger.warning(f"Lesson not found: Syllabus ID={syllabus_id}, Module={module_index}, Lesson={lesson_index}")
            raise NotFoundError(f"Lesson {lesson_index} not found in module {module_index}, syllabus {syllabus_id}.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving lesson details: {e}")
            raise ApplicationError(f"Error retrieving lesson details: {e}") from e
