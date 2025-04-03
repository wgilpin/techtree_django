"""Service layer for handling syllabus logic in the Django application."""

# pylint: disable=no-member

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from django.conf import settings  # Import settings
from django.db import transaction

from core.models import Lesson, Module, Syllabus
from core.exceptions import NotFoundError, ApplicationError

from .ai.syllabus_graph import SyllabusAI
from .ai.state import SyllabusState

logger = logging.getLogger(__name__)
# User = get_user_model() # No longer needed with settings.AUTH_USER_MODEL type hint

if TYPE_CHECKING:
    # Use settings.AUTH_USER_MODEL for type checking User model relation
    User = settings.AUTH_USER_MODEL  # type: ignore[misc] # Define User type alias for type checking


class SyllabusService:
    """
    Provides methods for syllabus creation, retrieval, and management using Django ORM
    and the adapted SyllabusAI graph.
    """

    def _get_syllabus_ai_instance(self) -> SyllabusAI:
        """Creates and returns an instance of the SyllabusAI."""
        # This might involve loading configurations or API keys in a real app
        return SyllabusAI()

    def _format_syllabus_dict(self, syllabus_obj: Syllabus) -> Dict[str, Any]:
        """Formats a Syllabus ORM object into a dictionary structure."""
        modules_list = []
        # Use prefetch_related for efficiency if called often outside of queries
        # that already prefetch.
        for module in syllabus_obj.modules.order_by("module_index").all():
            lessons_list = [
                {
                    "title": lesson.title,
                    "summary": lesson.summary,
                    "duration": lesson.duration,
                    "lesson_index": lesson.lesson_index,
                    "id": lesson.id,
                }
                for lesson in module.lessons.order_by("lesson_index").all()
            ]
            modules_list.append(
                {
                    "title": module.title,
                    "summary": module.summary,
                    "lessons": lessons_list,
                    "module_index": module.module_index,
                    "id": module.id,
                }
            )
        # Calculate user_id safely before creating the dictionary
        user_id_val = None
        if syllabus_obj.user:
            # Use assert to help mypy understand user is not None here
            assert syllabus_obj.user is not None
            user_id_val = str(syllabus_obj.user_id)

        # Corrected dictionary structure
        return {
            "syllabus_id": str(syllabus_obj.syllabus_id),
            "topic": syllabus_obj.topic,
            "level": syllabus_obj.level,
            "user_entered_topic": syllabus_obj.user_entered_topic,
            "user_id": user_id_val,  # Use pre-calculated value
            "created_at": (
                syllabus_obj.created_at.isoformat() if syllabus_obj.created_at else None
            ),
            "updated_at": (
                syllabus_obj.updated_at.isoformat() if syllabus_obj.updated_at else None
            ),
            "modules": modules_list,
            # Add other fields like duration, learning_objectives if they exist on the model
        }

    @transaction.atomic
    def get_or_generate_syllabus(
        # Use string literal for type hint if settings not directly available
        # Use string literal for type hint correctly within Optional
        self,
        topic: str,
        level: str,
        user: Optional["User"],  # type: ignore[valid-type]
    ) -> Dict[str, Any]:
        """
        Retrieves a syllabus by topic, level, and user, generating one via AI if it doesn't exist.

        Args:
            topic: The topic of the syllabus.
            level: The knowledge level of the syllabus.
            user: The user requesting the syllabus (None for master syllabus).

        Returns:
            A dictionary representing the found or newly created syllabus.

        Raises:
            ApplicationError: If syllabus generation fails.
        """
        logger.info(
            f"Attempting to get/generate syllabus: Topic='{topic}', Level='{level}', User='{user.pk if user else None}'"
        )
        try:
            syllabus_obj = (
                Syllabus.objects.prefetch_related("modules__lessons")
                .select_related("user")
                .get(topic=topic, level=level, user=user)
            )
            logger.info(f"Found existing syllabus ID: {syllabus_obj.syllabus_id}")
            return self._format_syllabus_dict(syllabus_obj)

        except Syllabus.DoesNotExist as ex:
            logger.info("Syllabus not found. Attempting generation.")
            try:
                syllabus_ai = self._get_syllabus_ai_instance()
                user_id_str = str(user.pk) if user else None
                syllabus_ai.initialize(
                    topic=topic, knowledge_level=level, user_id=user_id_str
                )

                # The AI graph now handles DB search and generation internally.
                # get_or_create_syllabus returns the final state dict containing the syllabus.
                # The save_syllabus node within the graph handles saving to DB via ORM.
                # get_or_create_syllabus now returns the full final state dictionary.
                final_state: SyllabusState = syllabus_ai.get_or_create_syllabus()

                # Extract the syllabus content and UID from the final state
                syllabus_content = final_state.get(
                    "generated_syllabus"
                ) or final_state.get("existing_syllabus")
                saved_uid = final_state.get(
                    "uid"
                )  # Get UID from the top level of the state

                if not syllabus_content or not isinstance(syllabus_content, dict):
                    logger.error(
                        "Syllabus generation failed: No valid syllabus content in final AI state."
                    )
                    raise ApplicationError("Failed to generate syllabus content.") from ex

                # The syllabus should already be saved by the save_syllabus node.
                # We just need to retrieve it using the UID from the state.
                if not saved_uid:
                    logger.error(
                        "Syllabus generation failed: No UID found in final AI state syllabus data."
                    )
                    raise ApplicationError("Failed to get ID of generated syllabus.") from ex

                # Retrieve the newly saved/updated syllabus object
                syllabus_obj = (
                    Syllabus.objects.prefetch_related("modules__lessons")
                    .select_related("user")
                    .get(pk=saved_uid)
                )

                logger.info(
                    f"Successfully generated and saved syllabus ID: {syllabus_obj.syllabus_id}"
                )
                return self._format_syllabus_dict(syllabus_obj)

            except Exception as e:
                logger.exception(f"Syllabus generation failed: {e}")
                raise ApplicationError(f"Failed to generate syllabus: {e}") from e

    def get_syllabus_by_id(self, syllabus_id: str) -> Dict[str, Any]:
        """
        Retrieves a specific syllabus by its primary key (UUID).

        Args:
            syllabus_id: The UUID primary key of the syllabus.

        Returns:
            A dictionary representing the syllabus.

        Raises:
            NotFoundError: If the syllabus with the given ID is not found.
        """
        logger.info(f"Retrieving syllabus by ID: {syllabus_id}")
        try:
            syllabus_obj = (
                Syllabus.objects.prefetch_related("modules__lessons")
                .select_related("user")
                .get(pk=syllabus_id)
            )
            return self._format_syllabus_dict(syllabus_obj)
        except Syllabus.DoesNotExist as exc:
            logger.warning(f"Syllabus with ID {syllabus_id} not found.")
            raise NotFoundError(f"Syllabus with ID {syllabus_id} not found.") from exc
        except Exception as e:
            logger.exception(f"Error retrieving syllabus ID {syllabus_id}: {e}")
            raise ApplicationError(f"Error retrieving syllabus: {e}") from e

    def get_module_details(self, syllabus_id: str, module_index: int) -> Dict[str, Any]:
        """
        Retrieves details for a specific module within a syllabus.

        Args:
            syllabus_id: The ID of the syllabus.
            module_index: The index of the module.

        Returns:
            A dictionary containing the module's details.

        Raises:
            NotFoundError: If the syllabus or module is not found.
        """
        logger.info(
            f"Retrieving module details: Syllabus ID={syllabus_id}, Module Index={module_index}"
        )
        try:
            # Correctly assign and type hint module_obj
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
                "id": module_obj.id,
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

    def get_lesson_details(
        self, syllabus_id: str, module_index: int, lesson_index: int
    ) -> Dict[str, Any]:
        """
        Retrieves details for a specific lesson within a syllabus module.

        Args:
            syllabus_id: The ID of the syllabus.
            module_index: The index of the module.
            lesson_index: The index of the lesson within the module.

        Returns:
            A dictionary containing the lesson's details.

        Raises:
            NotFoundError: If the syllabus, module, or lesson is not found.
        """
        logger.info(
            f"Retrieving lesson details: Syllabus ID={syllabus_id}, Module Index={module_index}, Lesson Index={lesson_index}"
        )
        try:
            # Correctly assign and type hint lesson_obj
            lesson_obj: Lesson = Lesson.objects.select_related("module__syllabus").get(
                module__syllabus_id=syllabus_id,
                module__module_index=module_index,
                lesson_index=lesson_index,
            )
            return {
                "id": lesson_obj.id,
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
                # Add lesson content field if applicable, e.g., lesson_obj.content_items.first().content
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


# Example usage (for testing or integration):
# syllabus_service = SyllabusService()
# user = User.objects.get(username='someuser') # Get a user instance
# syllabus_dict = syllabus_service.get_or_generate_syllabus(topic="Python Basics", level="beginner", user=user)
# print(syllabus_dict)
