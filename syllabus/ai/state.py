"""Defines the state dictionary for the syllabus generation graph."""

from typing import Dict, List, Optional, TypedDict, Any # Added Any

class SyllabusState(TypedDict):
    """TypedDict representing the state of the syllabus generation graph."""

    topic: str
    user_knowledge_level: (
        str  # 'beginner', 'early learner', 'good knowledge', or 'advanced'
    )
    existing_syllabus: Optional[Dict[str, Any]]  # Added type parameters
    search_results: List[str]  # Content snippets from web search
    generated_syllabus: Optional[
        Dict[str, Any] # Added type parameters
    ]  # Syllabus generated/updated by LLM in current run
    user_feedback: Optional[str]  # User feedback for syllabus revision
    syllabus_accepted: (
        bool  # Flag indicating user acceptance (not currently used by graph logic)
    )
    iteration_count: int  # Number of update iterations based on feedback
    user_id: Optional[str]  # ID of the user requesting the syllabus
    uid: Optional[str]  # Unique ID of the syllabus being worked on/generated
    is_master: Optional[bool]  # Whether the syllabus is a master template
    parent_uid: Optional[str]  # UID of the master syllabus if this is a user copy
    created_at: Optional[str]  # ISO format timestamp
    updated_at: Optional[str]  # ISO format timestamp
    user_entered_topic: Optional[str]  # The original topic string entered by the user
