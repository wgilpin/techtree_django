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
# from backend.services.sqlite_db import SQLiteDatabaseService # Removed, using Django ORM in nodes
from .state import SyllabusState
from .nodes import (
    search_database,
    search_internet,
    generate_syllabus,
    end_node,
    initialize_state,
    update_syllabus,
    save_syllabus,
)
from .config import (
    MODEL as llm_model,
    TAVILY as tavily_client,
)

# Add logger
logger = logging.getLogger(__name__)


class SyllabusAI:
    """Orchestrates syllabus generation using a LangGraph workflow."""

    def __init__(self) -> None:
        """Initializes the SyllabusAI graph and stores dependencies."""
        self.state: Optional[SyllabusState] = None
        # Store configured clients (or handle None if config failed)
        self.llm_model = llm_model
        self.tavily_client = tavily_client
        self.workflow = self._create_workflow()
        self.graph = self.workflow.compile()

    def _create_workflow(self) -> StateGraph:
        """Defines the structure (nodes and edges) of the syllabus LangGraph workflow."""
        workflow = StateGraph(SyllabusState)

        # Note: The first argument (state) is passed automatically by LangGraph
        # search_db_partial = partial(nodes.search_database, db_service=self.db_service) # Removed db_service
        # Node functions now handle DB access internally via Django ORM
        search_db_partial = search_database  # Use directly imported function
        search_internet_partial = partial(
            search_internet,
            tavily_client=self.tavily_client,  # Use directly imported function
        )
        generate_syllabus_partial = partial(
            generate_syllabus,
            llm_model=self.llm_model,  # Use directly imported function
        )

        # Add nodes using the standalone functions from nodes.py
        workflow.add_node("search_database", search_db_partial)
        workflow.add_node("search_internet", search_internet_partial)
        workflow.add_node("generate_syllabus", generate_syllabus_partial)
        # Add the save_syllabus node
        workflow.add_node(
            "save_syllabus", save_syllabus
        )  # Use directly imported function
        workflow.add_node("end_node", end_node)  # Use directly imported function

        # Define edges and entry point
        workflow.set_entry_point("search_database")  # Start flow by searching DB

        # workflow.add_edge("generate_syllabus", "end_node") # Generation should lead to save
        workflow.add_edge(
            "generate_syllabus", "save_syllabus"
        )  # Connect generation to save
        workflow.add_edge("save_syllabus", "end_node")  # Saving leads to end

        workflow.add_conditional_edges(
            "search_database",
            self._should_search_internet,
            {
                "search_internet": "search_internet",
                "end": "end_node",
            },  # Route to end if found
        )
        workflow.add_edge("search_internet", "generate_syllabus")
        # workflow.add_edge("generate_syllabus", "end_node") # Generation should lead to save
        workflow.add_edge(
            "generate_syllabus", "save_syllabus"
        )  # Connect generation to save
        workflow.add_edge("save_syllabus", "end_node")  # Saving leads to end

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
        initial_state_dict = initialize_state(  # Use directly imported function
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

    async def get_or_create_syllabus(self) -> SyllabusState: # Make async
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
            # Use astream for async execution
            async for step in self.graph.astream(self.state, config={"recursion_limit": 10}): # Use astream
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
        # Return the full updated state, not just the syllabus content dict
        if not self.state:
            # Should not happen if initialization worked, but safety check
            raise RuntimeError(
                "Syllabus AI state is unexpectedly None after execution."
            )
        return self.state

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
        update_result = update_syllabus(
            self.state, feedback, self.llm_model
        )  # Use directly imported function

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

        # Call the save node function directly
        # save_result = nodes.save_syllabus(self.state, self.db_service) # Removed db_service
        # save_syllabus node now handles DB access internally
        save_result = save_syllabus(self.state)  # Use directly imported function
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
        # Generate a new UUID for the clone, but it will be overwritten by the saved UID later
        generated_clone_uid = str(uuid.uuid4())

        # Update the copy with user-specific information
        user_syllabus["uid"] = generated_clone_uid  # Temporarily set generated UID
        user_syllabus["user_id"] = user_id
        user_syllabus["is_master"] = False
        user_syllabus["created_at"] = now
        user_syllabus["updated_at"] = now
        user_syllabus["user_entered_topic"] = self.state.get(
            "user_entered_topic", user_syllabus.get("topic")
        )

        # Determine the parent UID (should be the UID of the master version)
        master_syllabus = None  # Placeholder - needs review
        parent_uid = (
            master_syllabus.get("uid")
            if master_syllabus
            else syllabus_to_clone.get("uid")
        )
        user_syllabus["parent_uid"] = parent_uid
        print(f"Setting parent UID for clone {generated_clone_uid} to {parent_uid}")

        # Separate content for saving (ensure required keys are present)
        content_to_save = {}
        required_keys = ["topic", "level", "duration", "learning_objectives", "modules"]
        for k in required_keys:
            if k in user_syllabus:
                content_to_save[k] = user_syllabus[k]
            else:
                logger.warning(
                    f"Missing key '{k}' in syllabus content during clone save preparation."
                )
                content_to_save[k] = None  # Or some default

        if "topic" not in content_to_save or "level" not in content_to_save:
            raise ValueError(
                "Topic or level missing in content prepared for saving clone."
            )

        try:
            # Saving should be done via the save_syllabus node.
            # This direct save bypasses the graph logic. Needs significant review.
            # Simulate a successful save for now to avoid breaking the flow.
            logger.warning(
                "Direct DB save in clone_syllabus_for_user needs refactoring to use graph nodes."
            )

            # Simulate save result from the node
            save_node_state = initialize_state(
                None,
                topic=content_to_save["topic"],
                knowledge_level=content_to_save["level"],
                user_id=user_id,
            )
            save_node_state["generated_syllabus"] = (
                user_syllabus  # Put the cloned syllabus into a temporary state for the node
            )
            save_result = save_syllabus(cast(SyllabusState, save_node_state))
            saved_uid = save_result.get("saved_uid")

            if saved_uid is None:
                raise RuntimeError(
                    "Simulated save_syllabus node did not return a 'saved_uid'."
                )

            # Use the actual saved UID from now on
            actual_saved_uid = saved_uid
            user_syllabus["uid"] = (
                actual_saved_uid  # Ensure the dict reflects the actual saved UID
            )

            print(f"Cloned syllabus UID {actual_saved_uid} saved for user {user_id}.")

            # Update the agent's state to reflect the newly cloned syllabus
            if self.state:  # Check if state still exists
                self.state["generated_syllabus"] = user_syllabus
                self.state["existing_syllabus"] = None
                self.state["uid"] = actual_saved_uid
                self.state["user_id"] = user_id
                self.state["is_master"] = False
                self.state["parent_uid"] = parent_uid
                self.state["created_at"] = now
                self.state["updated_at"] = now

            # Add the database primary key (which is the UID in this case)
            user_syllabus["syllabus_id"] = actual_saved_uid

            return user_syllabus
        except Exception as e:
            # Use the generated UID for error reporting if save failed before getting saved_uid
            error_uid = generated_clone_uid
            print(f"Error cloning syllabus UID {error_uid} for user {user_id}: {e}")
            traceback.print_exc()
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
            # TODO: Implement delete_syllabus in SQLiteDatabaseService if needed. # pylint: disable=fixme
            # deleted = self.db_service.delete_syllabus(topic, knowledge_level, user_id) # Removed db_service
            # Deletion should also likely be a node if needed.
            deleted = False  # Assume deletion failed as method doesn't exist
            logger.warning(
                "Syllabus deletion is not implemented in SQLiteDatabaseService."
            )

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
