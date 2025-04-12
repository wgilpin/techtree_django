"""Defines and manages the LangGraph workflow for syllabus generation."""

# pylint: disable=broad-exception-caught,singleton-comparison

import copy
import uuid
import traceback
from datetime import datetime
from typing import Dict, Optional, cast, Any, Union  # Added cast, Any, Union

# Standard library imports
import logging
from functools import partial

# Third-party imports
from langgraph.graph import StateGraph

# First-party/Local imports
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from core.models import Syllabus, Module, Lesson  # Import Django models
from .state import SyllabusState
from . import nodes
from .config import (
    MODEL as llm_model,
    TAVILY as tavily_client,
)

# Add logger
logger = logging.getLogger(__name__)
User = get_user_model()  # Define User model


class SyllabusAI:
    """Orchestrates syllabus generation using a LangGraph workflow."""

    def __init__(self) -> None:
        """Initializes the SyllabusAI graph and stores dependencies."""
        self.state: Optional[SyllabusState] = None
        # Store configured clients (or handle None if config failed)
        # These are needed for the partials below
        self.llm_model = llm_model
        self.tavily_client = tavily_client
        self.workflow = self._create_workflow()
        self.graph = self.workflow.compile()

    def _create_workflow(self) -> StateGraph:
        """Defines the structure (nodes and edges) of the syllabus LangGraph workflow."""
        workflow = StateGraph(SyllabusState)

        # Note: The first argument (state) is passed automatically by LangGraph
        # search_database now only takes state, no db_service needed
        search_internet_partial = partial(
            nodes.search_internet, tavily_client=self.tavily_client
        )
        generate_syllabus_partial = partial(
            nodes.generate_syllabus, llm_model=self.llm_model
        )

        # Add nodes using the standalone functions from nodes.py
        workflow.add_node(
            "search_database", nodes.search_database
        )  # Pass function directly
        workflow.add_node("search_internet", search_internet_partial)
        workflow.add_node("generate_syllabus", generate_syllabus_partial)
        workflow.add_node("end_node", nodes.end_node)  # Use the simple end node

        # Define edges and entry point
        workflow.set_entry_point("search_database")  # Start flow by searching DB

        workflow.add_conditional_edges(
            "search_database",
            self._should_search_internet,
            {
                "search_internet": "search_internet",
                "end": "end_node",
            },  # Route to end if found
        )
        workflow.add_edge("search_internet", "generate_syllabus")
        workflow.add_edge("generate_syllabus", "end_node")  # Generation leads to end

        return workflow

    def _should_search_internet(self, state: SyllabusState) -> str:
        """Conditional Edge: Determines if web search is needed."""
        if state.get("existing_syllabus"):
            print("Conditional Edge: Existing syllabus found, ending.")
            return "end"
        else:
            print("Conditional Edge: No existing syllabus, searching internet.")
            return "search_internet"

    # --- Public Methods for Service Interaction ---

    def initialize(
        self, topic: str, knowledge_level: str, user_id: Optional[str] = None
    ) -> Dict[str, Optional[str]]:  # Revert: Returns a status dict, not the full state
        """Initializes the internal state for a new run."""
        # Use the node function directly to create the initial state dict
        # Cast the result to SyllabusState
        initial_state_dict = nodes.initialize_state(
            None,  # Pass None for state as it's initialization
            topic=topic,
            knowledge_level=knowledge_level,
            user_id=user_id,
        )
        self.state = cast(SyllabusState, initial_state_dict)
        print(
            f"SyllabusAI initialized: Topic='{topic}', Level='{knowledge_level}', User={user_id}"
        )
        return {
            "status": "initialized",
            "topic": topic,
            "knowledge_level": knowledge_level,
            "user_id": user_id,
        }

    def get_or_create_syllabus(self) -> SyllabusState:
        """Retrieves an existing syllabus or orchestrates the creation of a new one."""
        if not self.state:
            raise ValueError("Agent not initialized. Call initialize() first.")
        if not self.graph:
            raise RuntimeError("Graph not compiled.")
        print("Starting get_or_create_syllabus graph execution...")

        # Run the graph from the entry point ('search_database')
        final_state_updates = {}
        try:
            # Stream the execution, starting with the current state
            for step in self.graph.stream(self.state, config={"recursion_limit": 10}):
                node_name = list(step.keys())[0]
                print(f"Graph Step: {node_name}")
                # Accumulate all updates from the steps
                # Ensure the update value is a dictionary
                update_value = step[node_name]
                if isinstance(update_value, dict):
                    final_state_updates.update(update_value)
                else:
                    logger.warning(
                        f"Ignoring non-dict update from node '{node_name}': {update_value}"
                    )

            # Apply accumulated updates to the internal state carefully
            if final_state_updates and self.state:
                for key, value in final_state_updates.items():
                    if key in SyllabusState.__annotations__:
                        # Mypy might still complain about direct assignment, but it's safer than .update()
                        self.state[key] = value  # type: ignore
                    else:
                        logger.warning(
                            f"Ignoring unexpected key '{key}' from graph execution update."
                        )

        except Exception as e:
            print(f"Error during graph execution in get_or_create_syllabus: {e}")
            traceback.print_exc()
            raise RuntimeError("Syllabus graph execution failed.") from e

        # The result is the syllabus found or generated, now stored in the updated state
        syllabus = self.state.get("generated_syllabus") or self.state.get(
            "existing_syllabus"
        )

        if not syllabus:
            print(
                "Error: Graph execution finished but no valid syllabus found in state."
            )
            # Attempt to provide more context if available
            if self.state and self.state.get("error_generating"):
                print("Generation fallback structure was used but might be invalid.")
            raise RuntimeError("Failed to get or create a valid syllabus.")

        print(f"Syllabus get/create finished. Result UID: {syllabus.get('uid', 'N/A')}")
        # Cast to SyllabusState to satisfy mypy
        return cast(SyllabusState, syllabus)

    def update_syllabus(self, feedback: str) -> SyllabusState:
        """Updates the current syllabus based on user feedback."""
        if not self.state:
            raise ValueError("Agent not initialized.")
        if not (
            self.state.get("generated_syllabus") or self.state.get("existing_syllabus")
        ):
            raise ValueError("No syllabus loaded to update.")
        if not self.llm_model:
            raise RuntimeError("LLM model not configured for updates.")
        print("Starting syllabus update based on feedback...")

        # Call the update node function directly, passing current state and feedback
        update_result = nodes.update_syllabus(self.state, feedback, self.llm_model)

        # Update internal state with results carefully
        if self.state:
            for key, value in update_result.items():
                if key in SyllabusState.__annotations__:
                    self.state[key] = value  # type: ignore
                else:
                    logger.warning(
                        f"Ignoring unexpected key '{key}' from update_syllabus node result."
                    )

        # Return the syllabus currently in state
        # (which might be the updated one or original if update failed)
        syllabus = self.state.get("generated_syllabus") or self.state.get(
            "existing_syllabus"
        )
        if not syllabus:
            print("Error: Syllabus became invalid after update attempt.")
            raise RuntimeError("Syllabus became invalid after update attempt.")

        print(f"Syllabus update finished. Result UID: {syllabus.get('uid', 'N/A')}")
        # Cast to SyllabusState to satisfy mypy
        return cast(SyllabusState, syllabus)

    # For test compatibility: add get_or_create_syllabus_sync as an alias
    def get_or_create_syllabus_sync(self) -> SyllabusState:
        return self.get_or_create_syllabus()

    def save_syllabus(self) -> Dict[str, Optional[str]]:
        """Saves the current syllabus in the state to the database."""
        if not self.state:
            raise ValueError("Agent not initialized")
        print("Starting syllabus save process...")

        current_syllabus = self.state.get("generated_syllabus") or self.state.get(
            "existing_syllabus"
        )
        if not current_syllabus:
            print("Warning: No syllabus in state to save.")
            return {"status": "skipped", "reason": "No syllabus in state"}

        # Determine if save is needed (e.g., if generated_syllabus is populated)
        needs_save = self.state.get("generated_syllabus") is not None

        if not needs_save:
            # Check if it's an existing syllabus that might have been modified outside generation
            # For now, only save if explicitly generated/updated in this session.
            print(
                "Skipping save, syllabus was likely loaded and not modified in this session."
            )
            return {
                "status": "skipped",
                "reason": "Syllabus loaded, not generated/modified",
            }

        # Call the save node function directly (it now only takes state)
        save_result = nodes.save_syllabus(self.state)
        # Update state with any potential changes from saving (like UID, timestamps)
        if save_result.get("syllabus_saved"):
            # Selectively update state fields returned by save_syllabus
            state_updates = {
                k: v
                for k, v in save_result.items()
                if k in SyllabusState.__annotations__
            }  # Check keys
            if self.state:
                for key, value in state_updates.items():
                    self.state[key] = value  # type: ignore

            print(
                f"Syllabus save finished. Saved UID: {save_result.get('saved_uid', 'N/A')}"
            )
            return {"status": "saved", "uid": save_result.get("saved_uid")}
        else:
            print("Syllabus save failed.")
            return {"status": "failed"}

    def get_syllabus(self) -> Optional[Dict[str, Any]]:
        """Returns the current syllabus dictionary held in the agent's state."""
        if not self.state:
            raise ValueError("Agent not initialized")
        syllabus = self.state.get("generated_syllabus") or self.state.get(
            "existing_syllabus"
        )
        if not syllabus:
            raise ValueError("No syllabus loaded in the current state.")
        # Ensure we return a dict, not potentially a Pydantic model if state changes
        return dict(syllabus)

    # pylint: disable=too-many-statements
    def clone_syllabus_for_user(self, user_id: str) -> Dict[str, Any]:
        """Clones the current syllabus in the state for a specific user."""
        if not self.state:
            raise ValueError("Agent not initialized")

        syllabus_to_clone = self.state.get("generated_syllabus") or self.state.get(
            "existing_syllabus"
        )
        if not syllabus_to_clone:
            raise ValueError("No syllabus to clone")

        print(
            f"Cloning syllabus for user {user_id}. Source UID: {syllabus_to_clone.get('uid')}"
        )

        try:
            syllabus_dict = dict(syllabus_to_clone)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Invalid syllabus format for cloning: {type(syllabus_to_clone)}"
            ) from e

        # Create a deep copy for the user version
        user_syllabus = copy.deepcopy(syllabus_dict)
        now = datetime.now().isoformat()
        new_uid = str(uuid.uuid4())

        # Update the copy with user-specific information
        user_syllabus["uid"] = new_uid
        user_syllabus["user_id"] = user_id
        user_syllabus["is_master"] = False
        user_syllabus["created_at"] = now
        user_syllabus["updated_at"] = now
        user_syllabus["user_entered_topic"] = self.state.get(
            "user_entered_topic", user_syllabus.get("topic")
        )

        # Determine the parent UID using Django ORM
        parent_uid = syllabus_to_clone.get(
            "uid"
        )  # Default to original if master not found
        try:
            master_syllabus_obj = Syllabus.objects.get(  # pylint: disable=no-member
                topic=user_syllabus["topic"],
                level=user_syllabus["level"],
                user=None,  # Look for master (no user)
                status=Syllabus.StatusChoices.COMPLETED,
            )
            parent_uid = str(master_syllabus_obj.syllabus_id)
            logger.info(f"Found master syllabus {parent_uid} for cloning.")
        except ObjectDoesNotExist:
            logger.warning(
                f"Master syllabus not found for topic '{user_syllabus['topic']}' and level "
                f"'{user_syllabus['level']}'. Using original UID {parent_uid} as parent."
            )
        except Exception as e:
            logger.error(
                f"Error finding master syllabus during clone: {e}", exc_info=True
            )
            # Continue with original UID as parent

        user_syllabus["parent_uid"] = parent_uid
        print(f"Setting parent UID for clone {new_uid} to {parent_uid}")

        # Prepare data for saving using Django ORM
        try:
            user_obj = User.objects.get(pk=user_id)  # pylint: disable=no-member
        except User.DoesNotExist:  # pylint: disable=no-member
            raise ValueError(f"User with ID {user_id} not found for cloning.") from None
        except ValueError as e:
            raise ValueError(f"Invalid User ID format '{user_id}': {e}") from e

        try:
            # Create the new Syllabus instance
            cloned_syllabus_instance = Syllabus.objects.create(  # pylint: disable=no-member
                syllabus_id=new_uid,  # Use the generated UUID as the primary key
                user=user_obj,
                topic=user_syllabus["topic"],
                level=user_syllabus["level"],
                user_entered_topic=user_syllabus["user_entered_topic"],
                # duration=user_syllabus.get("duration"), # Removed - not in model
                # learning_objectives=user_syllabus.get("learning_objectives"), # Removed - not in model
                status=Syllabus.StatusChoices.COMPLETED,  # Assume cloned is complete
                # created_at and updated_at are handled by auto_now_add/auto_now
            )

            # Create Modules and Lessons
            for module_index, module_data in enumerate(
                user_syllabus.get("modules", [])
            ):
                if not isinstance(module_data, dict):
                    continue
                module_instance = Module.objects.create(  # pylint: disable=no-member
                    syllabus=cloned_syllabus_instance,
                    module_index=module_index,
                    title=module_data.get("title", f"Module {module_index+1}"),
                    summary=module_data.get("summary", ""),
                )
                for lesson_index, lesson_data in enumerate(
                    module_data.get("lessons", [])
                ):
                    if not isinstance(lesson_data, dict):
                        continue
                    Lesson.objects.create(  # pylint: disable=no-member
                        module=module_instance,
                        lesson_index=lesson_index,
                        title=lesson_data.get("title", f"Lesson {lesson_index+1}"),
                        summary=lesson_data.get("summary", ""),
                        duration=lesson_data.get("duration"),
                    )

            saved_id = str(cloned_syllabus_instance.syllabus_id)  # This is the new_uid
            print(f"Cloned syllabus UID {saved_id} saved for user {user_id}.")

            # Update the agent's state to reflect the newly cloned syllabus
            if self.state:  # Ensure state exists before updating
                self.state["generated_syllabus"] = (
                    user_syllabus  # Now working with the user copy
                )
                self.state["existing_syllabus"] = (
                    None  # Clear existing master from state
                )
                self.state["uid"] = saved_id
                self.state["user_id"] = user_id  # Ensure state reflects the user
                self.state["is_master"] = False
                self.state["parent_uid"] = parent_uid
                # Update timestamps from the saved instance
                self.state["created_at"] = (
                    cloned_syllabus_instance.created_at.isoformat()
                    if cloned_syllabus_instance.created_at
                    else None
                )
                self.state["updated_at"] = (
                    cloned_syllabus_instance.updated_at.isoformat()
                    if cloned_syllabus_instance.updated_at
                    else None
                )

            # Add the database primary key if needed, though UID is primary identifier
            user_syllabus["syllabus_id"] = saved_id

            return user_syllabus
        except Exception as e:
            print(f"Error saving cloned syllabus UID {new_uid} for user {user_id}: {e}")
            traceback.print_exc()
            # Attempt to delete the partially created syllabus if save failed
            try:
                Syllabus.objects.filter(
                    syllabus_id=new_uid
                ).delete()  # pylint: disable=no-member
                logger.warning(
                    f"Deleted partially created syllabus {new_uid} due to save error."
                )
            except Exception as del_e:
                logger.error(
                    f"Failed to delete partially created syllabus {new_uid}: {del_e}"
                )
            raise RuntimeError("Failed to save cloned syllabus.") from e

    def delete_syllabus(self) -> Dict[str, Union[bool, str]]:
        """Deletes the syllabus corresponding to the current state from the database."""
        if not self.state:
            raise ValueError("Agent not initialized")

        topic = self.state.get("topic")
        knowledge_level = self.state.get("user_knowledge_level")
        user_id = self.state.get("user_id")  # Use state's user_id

        if not topic or not knowledge_level:
            raise ValueError("State is missing topic or knowledge level for deletion.")

        print(
            f"Attempting deletion: Topic='{topic}', Level='{knowledge_level}', User={user_id}"
        )
        try:
            # Use Django ORM to delete the syllabus
            user_obj = (
                User.objects.get(pk=user_id) if user_id else None
            )  # pylint: disable=no-member
            delete_count, _ = Syllabus.objects.filter(  # pylint: disable=no-member
                topic=topic, level=knowledge_level, user=user_obj
            ).delete()

            deleted = delete_count > 0

            if deleted:
                # This block will likely not be reached until delete_syllabus is implemented
                print("Syllabus deleted successfully from DB.")
                # Clear syllabus from state after deletion
                self.state["existing_syllabus"] = None
                self.state["generated_syllabus"] = None
                self.state["uid"] = None
                self.state["parent_uid"] = None
                self.state["created_at"] = None
                self.state["updated_at"] = None
                # Keep topic, level, user_id etc. as they defined what was deleted
                return {"syllabus_deleted": True}
            else:
                # Adjust message since the method doesn't exist
                print("Syllabus deletion not performed (method not implemented).")
                return {"syllabus_deleted": False, "reason": "Not implemented"}
        except Exception as e:
            print(f"Error during attempted syllabus deletion: {e}")
            traceback.print_exc()
            return {"syllabus_deleted": False, "error": str(e)}
