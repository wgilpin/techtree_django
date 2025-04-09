"""
Service layer for the lessons app.

This module previously contained business logic for lessons, but functionality
has been refactored into more specific service modules:
- lessons.content_service: Handles fetching and generating lesson content.
- lessons.state_service: Manages lesson state and progress.
- lessons.interaction_service: Processes user interactions (chat, submissions).
"""

import logging

# Import necessary for potential future functions or if other modules rely on this logger
logger = logging.getLogger(__name__)

# All substantive functions have been moved to:
# - lessons.content_service.py
# - lessons.state_service.py
# - lessons.interaction_service.py
