"""Service layer for handling syllabus logic in the Django application."""

# pylint: disable=no-member

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

from asgiref.sync import sync_to_async

from core.exceptions import ApplicationError, NotFoundError
from core.models import Lesson, Module, Syllabus
from lessons.content_service import (
    trigger_first_lesson_generation,
)  # Import function directly

from .ai.state import SyllabusState
from .ai.syllabus_graph import SyllabusAI

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Import User model for type hinting
    from django.contrib.auth import models as auth_models


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
                        "title": lesson.title,
                        "summary": lesson.summary,
                        "duration": lesson.duration,
                        "lesson_index": lesson.lesson_index,
                        "id": lesson.id,
                    }
                    for lesson in module.lessons.order_by("lesson_index").all()
                ]
                modules_list_sync.append(
                    {
                        "title": module.title,
                        "summary": module.summary,
                        "lessons": lessons_list_sync,
                        "module_index": module.module_index,
                        "id": module.id,
                    }
                )
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
            "created_at": (
                syllabus_obj.created_at.isoformat() if syllabus_obj.created_at else None
            ),
            "updated_at": (
                syllabus_obj.updated_at.isoformat() if syllabus_obj.updated_at else None
            ),
            "modules": modules_list,
        }

    # --- Synchronous Counterparts for Sync Views ---

    def _format_syllabus_dict_sync(self, syllabus_obj: Syllabus) -> Dict[str, Any]:
        """Formats a Syllabus ORM object into a dictionary structure synchronously."""

        # Pre-calculate absolute lesson numbers for efficiency
        all_lessons_ordered = list(
            Lesson.objects.filter(module__syllabus=syllabus_obj)
            .order_by("module__module_index", "lesson_index")
            .values_list("pk", flat=True)  # Fetch only primary keys
        )
        absolute_lesson_number_map = {
            lesson_pk: index + 1 for index, lesson_pk in enumerate(all_lessons_ordered)
        }

        modules_list_sync = []
        # Access related managers synchronously
        # Prefetching should be done in the calling query if needed
        for module in syllabus_obj.modules.order_by("module_index").all():  # type: ignore[attr-defined]
            lessons_list_sync = []
            for lesson in module.lessons.order_by("lesson_index").all():
                absolute_number = absolute_lesson_number_map.get(lesson.pk)
                lessons_list_sync.append(
                    {
                        "title": lesson.title,
                        "summary": lesson.summary,
                        "duration": lesson.duration,
                        "lesson_index": lesson.lesson_index,  # Keep relative index if needed elsewhere
                        "absolute_lesson_number": absolute_number,  # Add absolute number
                        "id": lesson.id,
                    }
                )

            modules_list_sync.append(
                {
                    "title": module.title,
                    "summary": module.summary,
                    "lessons": lessons_list_sync,
                    "module_index": module.module_index,
                    "id": module.id,
                }
            )

        user_id_val = None
        if syllabus_obj.user:
            user_id_val = str(syllabus_obj.user_id)

        return {
            "syllabus_id": str(syllabus_obj.syllabus_id),
            "topic": syllabus_obj.topic,
            "level": syllabus_obj.level,
            "user_entered_topic": syllabus_obj.user_entered_topic,
            "user_id": user_id_val,
            "created_at": (
                syllabus_obj.created_at.isoformat() if syllabus_obj.created_at else None
            ),
            "updated_at": (
                syllabus_obj.updated_at.isoformat() if syllabus_obj.updated_at else None
            ),
            "modules": modules_list_sync,
        }

    def get_syllabus_by_id_sync(self, syllabus_id: str) -> Dict[str, Any]:
        """
        Retrieves a specific syllabus by its primary key (UUID) synchronously.
        """
        logger.info(f"Retrieving syllabus by ID (sync): {syllabus_id}")
        try:
            # Use prefetch_related for efficiency
            syllabus_obj = (
                Syllabus.objects.prefetch_related("modules__lessons")
                .select_related("user")
                .get(pk=syllabus_id)
            )
            return self._format_syllabus_dict_sync(syllabus_obj)
        except Syllabus.DoesNotExist as exc:
            logger.warning(f"Syllabus with ID {syllabus_id} not found (sync).")
            raise NotFoundError(f"Syllabus with ID {syllabus_id} not found.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving syllabus ID {syllabus_id} (sync): {e}")
            raise ApplicationError(f"Error retrieving syllabus: {e}") from e

    def get_module_details_sync(
        self, syllabus_id: str, module_index: int
    ) -> Dict[str, Any]:
        """
        Retrieves details for a specific module within a syllabus synchronously.
        """
        logger.info(
            f"Retrieving module details (sync): Syllabus ID={syllabus_id}, Module Index={module_index}"
        )
        try:
            module_obj: Module = (
                Module.objects.select_related("syllabus")
                .prefetch_related("lessons")
                .get(syllabus_id=syllabus_id, module_index=module_index)
            )

            lessons_list = [
                {
                    "title": lesson.title,
                    "summary": lesson.summary,
                    "duration": lesson.duration,
                    "lesson_index": lesson.lesson_index,
                    "id": lesson.id,
                }
                for lesson in module_obj.lessons.order_by("lesson_index").all()
            ]

            return {
                "id": module_obj.id,  # type: ignore[attr-defined]
                "syllabus_id": str(module_obj.syllabus.syllabus_id),  # type: ignore[attr-defined]
                "module_index": module_obj.module_index,
                "title": module_obj.title,
                "summary": module_obj.summary,
                "lessons": lessons_list,
                "created_at": (
                    module_obj.created_at.isoformat() if module_obj.created_at else None
                ),
                "updated_at": (
                    module_obj.updated_at.isoformat() if module_obj.updated_at else None
                ),
            }
        except Module.DoesNotExist as exc:
            logger.warning(
                f"Module not found (sync): Syllabus ID={syllabus_id}, Index={module_index}"
            )
            raise NotFoundError(
                f"Module {module_index} not found in syllabus {syllabus_id}."
            ) from exc
        except Exception as e:
            logger.exception(f"Error retrieving module details (sync): {e}")
            raise ApplicationError(f"Error retrieving module details: {e}") from e

    def get_lesson_details_sync(
        self, syllabus_id: str, module_index: int, lesson_index: int
    ) -> Dict[str, Any]:
        """
        Retrieves details for a specific lesson within a syllabus module synchronously.
        """
        logger.info(
            f"Retrieving lesson details (sync): Syllabus ID={syllabus_id}, Module Index={module_index}, "
            f"Lesson Index={lesson_index}"
        )
        try:
            lesson_obj: Lesson = Lesson.objects.select_related("module__syllabus").get(
                module__syllabus_id=syllabus_id,
                module__module_index=module_index,
                lesson_index=lesson_index,
            )
            return {
                "id": lesson_obj.id,  # type: ignore[attr-defined]
                "module_id": lesson_obj.module.id,  # type: ignore[attr-defined]
                "syllabus_id": str(lesson_obj.module.syllabus.syllabus_id),  # type: ignore[attr-defined]
                "lesson_index": lesson_obj.lesson_index,
                "title": lesson_obj.title,
                "summary": lesson_obj.summary,
                "duration": lesson_obj.duration,
                "created_at": (
                    lesson_obj.created_at.isoformat() if lesson_obj.created_at else None
                ),
                "updated_at": (
                    lesson_obj.updated_at.isoformat() if lesson_obj.updated_at else None
                ),
            }
        except Lesson.DoesNotExist as exc:
            logger.warning(
                f"Lesson not found (sync): Syllabus ID={syllabus_id}, Module={module_index}, Lesson={lesson_index}"
            )
            raise NotFoundError(
                f"Lesson {lesson_index} not found in module {module_index}, syllabus {syllabus_id}."
            ) from exc
        except Exception as e:
            logger.exception(f"Error retrieving lesson details (sync): {e}")
            raise ApplicationError(f"Error retrieving lesson details: {e}") from e

    # --- Async Methods ---
    async def get_or_generate_syllabus_sync(
        self,
        topic: str,
        level: str,
        user: Optional["auth_models.User"],
    ) -> UUID:
        """
        Synchronously gets or generates a syllabus without using background tasks.

        Args:
            topic: The topic of the syllabus.
            level: The difficulty level of the syllabus.
            user: The user requesting the syllabus.

        Returns:
            The UUID of the existing or newly generated syllabus.

        Raises:
            ApplicationError: If syllabus generation fails.
        """
        user_pk_str = str(user.pk) if user else "None"
        logger.info(
            f"Attempting to get/generate syllabus synchronously: Topic='{topic}', Level='{level}', User='{user_pk_str}'"
        )
        # First, check if a completed syllabus already exists
        try:
            syllabus_obj = await Syllabus.objects.aget(
                topic=topic,
                level=level,
                user=user,
                status=Syllabus.StatusChoices.COMPLETED,
            )
            logger.info(
                f"Found existing COMPLETED syllabus ID {syllabus_obj.syllabus_id} for "
                f"Topic='{topic}', Level='{level}', User='{user_pk_str}'"
            )
            # Trigger first lesson generation
            asyncio.create_task(
                trigger_first_lesson_generation(syllabus_obj.syllabus_id)
            )
            return syllabus_obj.syllabus_id
        except Syllabus.DoesNotExist:
            logger.info(
                f"No existing COMPLETED syllabus found for Topic='{topic}', Level='{level}', User='{user_pk_str}'. "
                f"Generating new one synchronously."
            )
            # No existing completed syllabus, generate a new one synchronously

            # Create a new syllabus with GENERATING status
            # Use try-except to handle potential creation errors
            try:
                placeholder_syllabus = await Syllabus.objects.acreate(
                    topic=topic,
                    level=level,
                    user=user,
                    user_entered_topic=topic,
                    status=Syllabus.StatusChoices.GENERATING,
                )
                logger.info(
                    f"Created placeholder syllabus ID: {placeholder_syllabus.syllabus_id} for sync generation."
                )
            except Exception as e:
                logger.exception(
                    f"Failed to create placeholder syllabus for sync generation: {e}"
                )
                raise ApplicationError(
                    f"Failed to initiate syllabus generation: {e}"
                ) from e

            # Generate the syllabus content directly (no background task)
            try:
                syllabus_ai = self._get_syllabus_ai_instance()
                syllabus_ai.initialize(
                    topic=topic,
                    knowledge_level=level,
                    user_id=str(user.pk) if user else None,
                )

                # Run the AI graph to generate the syllabus
                final_state: SyllabusState = await syllabus_ai.get_or_create_syllabus()

                # Check for explicit error state from AI
                if final_state.get("error_generating"):
                    error_msg = final_state.get(
                        "error_message", "AI indicated generation error"
                    )
                    logger.error(
                        f"Sync AI generation failed for {placeholder_syllabus.syllabus_id}: {error_msg}"
                    )
                    # Attempt to mark as FAILED
                    placeholder_syllabus.status = Syllabus.StatusChoices.FAILED
                    await placeholder_syllabus.asave(
                        update_fields=["status", "updated_at"]
                    )
                    raise ApplicationError(
                        f"Failed to generate syllabus content: {error_msg}"
                    )

                # The save_syllabus node should have updated the status to COMPLETED.
                # Verify status after generation
                await placeholder_syllabus.arefresh_from_db()
                if placeholder_syllabus.status != Syllabus.StatusChoices.COMPLETED:
                    logger.warning(
                        f"Syllabus {placeholder_syllabus.syllabus_id} status is {placeholder_syllabus.status} after sync generation, expected COMPLETED. Forcing update."
                    )
                    placeholder_syllabus.status = Syllabus.StatusChoices.COMPLETED
                    await placeholder_syllabus.asave(
                        update_fields=["status", "updated_at"]
                    )

                logger.info(
                    f"Successfully generated syllabus synchronously for ID: {placeholder_syllabus.syllabus_id}"
                )
                # Trigger first lesson generation
                asyncio.create_task(
                    trigger_first_lesson_generation(placeholder_syllabus.syllabus_id)
                )
                return placeholder_syllabus.syllabus_id

            except Exception as e:
                logger.exception(
                    f"Error during synchronous syllabus generation for ID {placeholder_syllabus.syllabus_id}: {e}"
                )
                # Attempt to mark the placeholder as FAILED
                try:
                    placeholder_syllabus.status = Syllabus.StatusChoices.FAILED
                    await placeholder_syllabus.asave(
                        update_fields=["status", "updated_at"]
                    )
                    logger.info(
                        f"Marked syllabus {placeholder_syllabus.syllabus_id} as FAILED due to sync generation error."
                    )
                except Exception as update_err:
                    logger.exception(
                        f"Failed to mark syllabus {placeholder_syllabus.syllabus_id} as FAILED after sync error: {update_err}"
                    )
                raise ApplicationError(f"Failed during syllabus generation: {e}") from e

    def _run_generation_task(
        self,
        placeholder_id: UUID,
        gen_topic: str,
        gen_level: str,
        gen_user_id_str: Optional[str],
    ) -> None:
        """Runs the AI generation and updates the placeholder syllabus in a dedicated thread."""
        import threading

        logger.info(
            f"Starting background generation task for syllabus ID: {placeholder_id}"
        )

        async def _async_generation() -> None:
            """The actual async generation logic."""
            try:
                syllabus_ai = self._get_syllabus_ai_instance()
                syllabus_ai.initialize(
                    topic=gen_topic, knowledge_level=gen_level, user_id=gen_user_id_str
                )
                final_state: SyllabusState = await syllabus_ai.get_or_create_syllabus()

                if final_state.get("error_generating"):
                    error_msg = final_state.get(
                        "error_message", "AI indicated generation error"
                    )
                    logger.error(
                        f"AI generation failed for {placeholder_id}: {error_msg}"
                    )
                    raise ApplicationError("Failed to generate syllabus content")

                syllabus_content = final_state.get(
                    "generated_syllabus"
                ) or final_state.get("existing_syllabus")

                if not syllabus_content or not isinstance(syllabus_content, dict):
                    logger.error(
                        f"AI returned no valid syllabus content for {placeholder_id}."
                    )
                    raise ApplicationError("Failed to generate syllabus content")

                uid = final_state.get("uid")
                if not uid:
                    logger.error(
                        f"Generated syllabus state missing UID for {placeholder_id}."
                    )
                    raise ApplicationError("Failed to get ID of generated syllabus")

                try:
                    syllabus = await Syllabus.objects.aget(pk=placeholder_id)
                    if syllabus.status != Syllabus.StatusChoices.COMPLETED:
                        logger.warning(
                            f"Syllabus {placeholder_id} status is {syllabus.status} after generation, expected COMPLETED."
                        )
                except Syllabus.DoesNotExist:
                    logger.error(
                        f"Syllabus {placeholder_id} disappeared after generation task!"
                    )

                logger.info(
                    f"Successfully generated syllabus content for ID: {placeholder_id}"
                )
                
                # Skip lesson generation in this thread to avoid nested event loops
                # We'll handle it separately in a future enhancement
                logger.info(f"Skipping immediate lesson generation for syllabus {placeholder_id}")

            except Exception as e:
                logger.exception(
                    f"Error in background syllabus generation task for ID {placeholder_id}: {e}"
                )
                try:
                    syllabus = await Syllabus.objects.aget(pk=placeholder_id)
                    if syllabus.status != Syllabus.StatusChoices.FAILED:
                        syllabus.status = Syllabus.StatusChoices.FAILED
                        await syllabus.asave(update_fields=["status", "updated_at"])
                        logger.info(
                            f"Marked syllabus {placeholder_id} as FAILED due to generation error."
                        )
                except Exception as update_err:
                    logger.exception(
                        f"Failed to mark syllabus {placeholder_id} as FAILED after error: {update_err}"
                    )

        def _thread_target() -> None:
            """Thread target that runs the async generation with proper event loop handling."""
            try:
                # Use asyncio.run which properly handles async generator cleanup
                asyncio.run(_async_generation())
                logger.info(f"Generation thread for syllabus {placeholder_id} completed successfully")
            except Exception as e:
                logger.exception(f"Unhandled error in generation thread for syllabus {placeholder_id}: {e}")

        # Start a dedicated thread for this generation task
        thread = threading.Thread(
            target=_thread_target,
            name=f"syllabus-gen-{placeholder_id}",
            daemon=True,  # Allow the thread to be terminated when the main process exits
        )
        thread.start()
        logger.info(f"Started dedicated thread for syllabus {placeholder_id} generation")

    async def get_or_generate_syllabus(
        self,
        topic: str,
        level: str,
        user: Optional["auth_models.User"],
    ) -> UUID:
        """
        Retrieves a syllabus ID by topic, level, and user.
        If it doesn't exist, creates a placeholder and starts generation asynchronously.
        """
        user_pk_str = str(user.pk) if user else "None"
        logger.info(
            f"Attempting to get/generate syllabus: Topic='{topic}', Level='{level}', User='{user_pk_str}'"
        )

        completed = await self._get_completed_syllabus(topic, level, user, user_pk_str)
        if completed:
            return completed

        placeholder = await self._get_existing_placeholder(
            topic, level, user, user_pk_str
        )
        if placeholder:
            return placeholder

        new_placeholder = await self._create_placeholder_and_launch(
            topic, level, user, user_pk_str
        )
        return new_placeholder

    async def _get_completed_syllabus(
        self,
        topic: str,
        level: str,
        user: Optional["auth_models.User"],
        user_pk_str: str,
    ) -> Optional[UUID]:
        try:
            syllabus_obj = await Syllabus.objects.aget(
                topic=topic,
                level=level,
                user=user,
                status=Syllabus.StatusChoices.COMPLETED,
            )
            logger.info(
                f"Found existing COMPLETED syllabus ID {syllabus_obj.syllabus_id} for "
                f"Topic='{topic}', Level='{level}', User='{user_pk_str}'"
            )
            asyncio.create_task(
                trigger_first_lesson_generation(syllabus_obj.syllabus_id)
            )
            return syllabus_obj.syllabus_id
        except Syllabus.DoesNotExist:
            logger.info(
                f"No existing COMPLETED syllabus found for Topic='{topic}', Level='{level}', User='{user_pk_str}'."
            )
            return None
        except asyncio.CancelledError:
            logger.warning(
                f"Syllabus retrieval cancelled for Topic='{topic}', Level='{level}', User='{user_pk_str}'"
            )
            return None

    async def _get_existing_placeholder(
        self,
        topic: str,
        level: str,
        user: Optional["auth_models.User"],
        user_pk_str: str,
    ) -> Optional[UUID]:
        try:
            placeholder = await Syllabus.objects.exclude(
                status=Syllabus.StatusChoices.COMPLETED
            ).aget(topic=topic, level=level, user=user)
            logger.info(
                f"Found existing placeholder syllabus ID: {placeholder.syllabus_id} with status {placeholder.status}."
            )
            if placeholder.status == Syllabus.StatusChoices.FAILED:
                logger.info(
                    f"Placeholder syllabus {placeholder.syllabus_id} previously FAILED. Resetting status and retrying generation."
                )
                placeholder.status = Syllabus.StatusChoices.GENERATING
                await placeholder.asave(update_fields=["status", "updated_at"])

                user_id_str_for_task = str(user.pk) if user else None
                self._run_generation_task(
                    placeholder.syllabus_id,
                    topic,
                    level,
                    user_id_str_for_task,
                )
                logger.info(
                    f"Relaunched background generation task for placeholder syllabus {placeholder.syllabus_id}"
                )
            elif placeholder.status == Syllabus.StatusChoices.GENERATING:
                logger.info(
                    f"Placeholder syllabus {placeholder.syllabus_id} is already GENERATING. Skipping new generation task."
                )
            return placeholder.syllabus_id
        except Syllabus.DoesNotExist:
            logger.info("No existing placeholder found. Will create new one.")
            return None

    async def _create_placeholder_and_launch(
        self,
        topic: str,
        level: str,
        user: Optional["auth_models.User"],
        user_pk_str: str,
    ) -> UUID:
        try:
            placeholder = await Syllabus.objects.acreate(
                topic=topic,
                level=level,
                user=user,
                user_entered_topic=topic,
                status=Syllabus.StatusChoices.GENERATING,
            )
            logger.info(
                f"Created new placeholder syllabus ID: {placeholder.syllabus_id}"
            )
        except Exception as e:
            logger.exception(f"Failed to create placeholder syllabus: {e}")
            raise ApplicationError(f"Failed to create placeholder syllabus: {e}") from e

        user_id_str_for_task = str(user.pk) if user else None
        self._run_generation_task(
            placeholder.syllabus_id, topic, level, user_id_str_for_task
        )
        logger.info(
            f"Launched background generation task for {placeholder.syllabus_id}"
        )
        return placeholder.syllabus_id

    async def get_syllabus_by_id(self, syllabus_id: str) -> Dict[str, Any]:
        """
        Retrieves a specific syllabus by its primary key (UUID).
        """
        logger.info(f"Retrieving syllabus by ID: {syllabus_id}")
        try:
            syllabus_obj = (
                await Syllabus.objects.prefetch_related(
                    "modules__lessons"  # Ensure prefetch for _format_syllabus_dict
                )
                .select_related("user")
                .aget(pk=syllabus_id)
            )
            # Await the async helper
            return await self._format_syllabus_dict(syllabus_obj)  # type: ignore
        except Syllabus.DoesNotExist as exc:
            logger.warning(f"Syllabus with ID {syllabus_id} not found.")
            raise NotFoundError(f"Syllabus with ID {syllabus_id} not found.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving syllabus ID {syllabus_id}: {e}")
            raise ApplicationError(f"Error retrieving syllabus: {e}") from e

    async def get_module_details(
        self, syllabus_id: str, module_index: int
    ) -> Dict[str, Any]:
        """
        Retrieves details for a specific module within a syllabus.
        """
        logger.info(
            f"Retrieving module details: Syllabus ID={syllabus_id}, Module Index={module_index}"
        )
        try:
            module_obj: Module = (
                await Module.objects.select_related("syllabus")
                .prefetch_related("lessons")  # Ensure prefetch for sync access below
                .aget(syllabus_id=syllabus_id, module_index=module_index)
            )

            @sync_to_async
            def get_lessons_sync(module):
                lessons_list_sync = [
                    {
                        "title": lesson.title,
                        "summary": lesson.summary,
                        "duration": lesson.duration,
                        "lesson_index": lesson.lesson_index,
                        "id": lesson.id,
                    }
                    for lesson in module.lessons.order_by("lesson_index").all()
                ]
                return lessons_list_sync

            lessons_list = await get_lessons_sync(module_obj)

            return {
                "id": module_obj.id,  # type: ignore[attr-defined]
                "syllabus_id": str(module_obj.syllabus.syllabus_id),  # type: ignore[attr-defined]
                "module_index": module_obj.module_index,
                "title": module_obj.title,
                "summary": module_obj.summary,
                "lessons": lessons_list,
                "created_at": (
                    module_obj.created_at.isoformat() if module_obj.created_at else None
                ),
                "updated_at": (
                    module_obj.updated_at.isoformat() if module_obj.updated_at else None
                ),
            }
        except Module.DoesNotExist as exc:
            logger.warning(
                f"Module not found: Syllabus ID={syllabus_id}, Index={module_index}"
            )
            raise NotFoundError(
                f"Module {module_index} not found in syllabus {syllabus_id}."
            ) from exc
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
            f"Retrieving lesson details: Syllabus ID={syllabus_id}, Module Index={module_index}, "
            f"Lesson Index={lesson_index}"
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
                "id": lesson_obj.id,  # type: ignore[attr-defined]
                "module_id": lesson_obj.module.id,  # type: ignore[attr-defined]
                "syllabus_id": str(lesson_obj.module.syllabus.syllabus_id),  # type: ignore[attr-defined]
                "lesson_index": lesson_obj.lesson_index,
                "title": lesson_obj.title,
                "summary": lesson_obj.summary,
                "duration": lesson_obj.duration,
                "created_at": (
                    lesson_obj.created_at.isoformat() if lesson_obj.created_at else None
                ),
                "updated_at": (
                    lesson_obj.updated_at.isoformat() if lesson_obj.updated_at else None
                ),
            }
        except Lesson.DoesNotExist as exc:
            logger.warning(
                f"Lesson not found: Syllabus ID={syllabus_id}, Module={module_index}, Lesson={lesson_index}"
            )
            raise NotFoundError(
                f"Lesson {lesson_index} not found in module {module_index}, syllabus {syllabus_id}."
            ) from exc
        except Exception as e:
            logger.exception(f"Error retrieving lesson details: {e}")
            raise ApplicationError(f"Error retrieving lesson details: {e}") from e
