"""Defines and manages the LangGraph workflow for lesson interactions."""

import logging
from typing import Any, Dict, List, cast, Optional

from langgraph.graph import StateGraph, END

from .state import LessonState
from . import nodes # Import our ported nodes

logger = logging.getLogger(__name__)

# Helper function for routing based on state (ported)
def _route_message_logic(state: LessonState) -> str:
    """Determines the next node based on the current interaction mode."""
    # Use the mode set by classify_intent node
    mode = state.get("current_interaction_mode", "chatting")
    if mode == "request_exercise":
        return "generate_new_exercise"
    if mode == "request_assessment":
        return "generate_new_assessment"
    if mode == "submit_answer":
        return "evaluate_answer"
    # Default to chatting
    return "generate_chat_response"


class LessonInteractionGraph:
    """Encapsulates the LangGraph for lesson interactions (chat, exercises, etc.)."""

    def __init__(self) -> None:
        """Initializes the LessonInteractionGraph."""
        self.workflow = self._create_workflow()
        self.graph = self.workflow.compile()
        logger.info("Lesson interaction graph compiled.")

    def _create_workflow(self) -> StateGraph:
        """Defines the structure (nodes and edges) of the lesson interaction graph."""
        workflow = StateGraph(LessonState)

        # Add nodes using the imported functions from nodes.py
        workflow.add_node("classify_intent", nodes.classify_intent)
        workflow.add_node("generate_chat_response", nodes.generate_chat_response)
        workflow.add_node("generate_new_exercise", nodes.generate_new_exercise)
        workflow.add_node("evaluate_answer", nodes.evaluate_answer)
        workflow.add_node("generate_new_assessment", nodes.generate_new_assessment)
        # Entry point for a chat turn
        workflow.set_entry_point("classify_intent")

        # Conditional routing after classifying intent
        workflow.add_conditional_edges(
            "classify_intent",
            _route_message_logic,
            {
                "generate_chat_response": "generate_chat_response",
                "generate_new_exercise": "generate_new_exercise",
                "evaluate_answer": "evaluate_answer",
                "generate_new_assessment": "generate_new_assessment",
            },
        )

        # Edges leading back to the end after processing
        workflow.add_edge("generate_chat_response", END)
        workflow.add_edge("generate_new_exercise", END) # Exercise generation also leads to END for this turn
        workflow.add_edge("evaluate_answer", END) # Evaluation also leads to END
        workflow.add_edge("generate_new_assessment", END) # Assessment generation also leads to END

        return workflow

    def process_chat_turn(
        self, current_state: LessonState, history_context: List[Dict[str, str]]
    ) -> LessonState:
        """
        Processes one turn of the conversation using the compiled graph.

        Args:
            current_state: The current state dictionary for the lesson interaction.
            history_context: The conversation history to provide context.

        Returns:
            The updated LessonState dictionary after processing the turn.
        """
        if not self.graph:
            raise RuntimeError("Graph not compiled.")


        # Prepare input state for the graph, adding history context
        # The graph nodes expect 'history_context'
        input_state_dict: Dict[str, Any] = {
            **current_state,
            "history_context": history_context,
        }

        # Invoke the chat graph
        # Stream allows observing intermediate steps if needed later
        final_state_updates: Dict[str, Any] = {}
        try:
             # Use invoke for simpler final state retrieval
            final_state_updates = self.graph.invoke(input_state_dict, {"recursion_limit": 10})

        except Exception as e:
            logger.error("Error during graph execution in process_chat_turn: %s", e, exc_info=True)
            # Return current state with error message
            current_state["error_message"] = f"Graph execution failed: {e}"
            return current_state

        # LangGraph's invoke typically returns the full final state for the given StateGraph type
        if not isinstance(final_state_updates, dict):
             logger.error("Graph invoke did not return a dictionary. Returning original state with error.")
             current_state["error_message"] = "Graph execution returned unexpected type."
             # Ensure history_context is removed even on error return
             current_state.pop('history_context', None)
             return current_state

        final_state_dict = final_state_updates

        # Remove the temporary keys used for graph invocation context
        final_state_dict.pop('history_context', None)

        # Cast final dict back to LessonState
        final_state: LessonState = cast(LessonState, final_state_dict)

        return final_state

# Example instantiation (optional, for testing)
# lesson_ai_graph = LessonInteractionGraph()