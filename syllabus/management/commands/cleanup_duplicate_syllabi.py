# syllabus/management/commands/cleanup_duplicate_syllabi.py
"""
Django management command to clean up duplicate Syllabus entries.

For each unique combination of user, user_entered_topic, and level, this command
keeps only the most recently created syllabus entry and deletes the older ones.
"""
import logging
from typing import Set
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from core.models import Syllabus

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Command(BaseCommand):
    """
    Management command to remove duplicate Syllabus entries.

    Identifies syllabi with the same user, user_entered_topic, and level, keeping only the
    most recent one based on creation timestamp and ID.
    """

    help = (
        "Removes duplicate Syllabus entries, keeping only the most recent "
        "for each user, user_entered_topic, and level combination."
    )

    def handle(self, *args, **options) -> None:
        """
        Executes the cleanup logic.
        """
        self.stdout.write("Starting cleanup of duplicate Syllabus entries...")

        ids_to_delete: Set[int] = set()

        try:
            with transaction.atomic():
                # Identify combinations of user, user_entered_topic, level with duplicates
                duplicate_combinations = (
                    Syllabus.objects.values("user_id", "user_entered_topic", "level")
                    .annotate(count=Count("syllabus_id"))
                    .filter(count__gt=1)
                    .values("user_id", "user_entered_topic", "level")
                    .distinct()
                )

                if not duplicate_combinations.exists():
                    self.stdout.write(
                        self.style.SUCCESS("No duplicate Syllabus entries found.")
                    )
                    return

                self.stdout.write(
                    f"Found {duplicate_combinations.count()} combinations with duplicates."
                )

                # Iterate through each duplicate combination
                for combo in duplicate_combinations:
                    user_id = combo["user_id"]
                    user_entered_topic = combo["user_entered_topic"]
                    level = combo["level"]

                    # Find all syllabi for this combination, ordered newest first
                    syllabi_for_combo = Syllabus.objects.filter(
                        user_id=user_id, user_entered_topic=user_entered_topic, level=level
                    ).order_by("-created_at", "-syllabus_id") # Use -syllabus_id as tie-breaker

                    # Keep the first one (newest)
                    latest_syllabus = syllabi_for_combo.first()
                    if latest_syllabus:
                        # Collect IDs of the older duplicates
                        duplicate_ids = syllabi_for_combo.exclude(
                            syllabus_id=latest_syllabus.syllabus_id
                        ).values_list("syllabus_id", flat=True)
                        ids_to_delete.update(duplicate_ids)
                        self.stdout.write(
                            f"  - User {user_id}, User Entered Topic '{user_entered_topic}', Level '{level}': "
                            f"Keeping ID {latest_syllabus.syllabus_id}, marking "
                            f"{len(duplicate_ids)} for deletion."
                        )

                # Perform bulk delete if any duplicates were found
                if ids_to_delete:
                    count_to_delete = len(ids_to_delete)
                    self.stdout.write(
                        f"\nAttempting to delete {count_to_delete} duplicate entries..."
                    )
                    deleted_count, _ = Syllabus.objects.filter(
                        syllabus_id__in=list(ids_to_delete)
                    ).delete()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully deleted {deleted_count} duplicate Syllabus entries."
                        )
                    )
                else:
                    # This case should ideally not be reached if duplicate_combinations existed,
                    # but included for robustness.
                    self.stdout.write(
                        self.style.WARNING(
                            "Identified duplicate combinations, but found no specific "
                            "entries to delete. This might indicate an unexpected state."
                        )
                    )

        except Exception as e:
            logger.error(f"An error occurred during syllabus cleanup: {e}", exc_info=True)
            raise CommandError(f"Failed to clean up duplicate syllabi. Error: {e}")

        self.stdout.write("Syllabus cleanup process finished.")