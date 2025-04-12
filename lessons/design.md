# lessons

**Name:** Lessons App Logic and User Interaction

**Description:**  
This folder implements the business logic, user interaction handling, and service layers for lesson delivery in the application. It provides the mechanisms for lesson content generation, user progress tracking, chat and exercise handling, and state management. The code here orchestrates how users interact with lessons, how lesson content is generated and fetched, and how lesson state is initialized and updated.

---

## Files

### admin.py
Minimal admin configuration for the lessons app; most model registrations are handled in the core app.
- No public methods.

### apps.py
Django app configuration for the lessons app.
- No public methods.

### content_service.py
Service layer for generating and fetching lesson exposition content using LLMs.
- `_get_llm()`: Initializes and returns the LangChain LLM model based on settings.
- `_fetch_syllabus_structure(syllabus)`: Fetches and formats the syllabus structure for prompt generation.

### interaction_service.py
Service layer for handling user interactions within lessons, including chat, exercises, and assessments.
- `handle_chat_message(user, progress, user_message_content, submission_type='chat')`: Processes a user's message or submission during a lesson using the AI graph and updates state/history.

### services.py
Legacy service module for the lessons app; all substantive logic has been refactored into more specific service modules.
- No public methods.

### state_service.py
Service layer for managing lesson state and history, including initialization and updates.
- `initialize_lesson_state(user, lesson, lesson_content)`: Initializes the lesson state for a new UserProgress record.

### urls.py
URL configuration for the lessons app, mapping URL patterns to views for lesson detail, interaction, content generation, and difficulty changes.
- No public methods.

### views.py
Implements the main views for the lessons app, including lesson detail display, user interaction handling, content generation, and difficulty changes.
- `clean_exposition_string(text)`: Decodes and cleans up exposition text for display.
- `lesson_detail(request, syllabus_id, module_index, lesson_index)`: Displays a specific lesson, its content, and conversation history.
- `handle_lesson_interaction(request, syllabus_id, module_index, lesson_index)`: Handles user POST interactions (questions, answers) with a lesson.
- `generate_lesson_content(request, syllabus_id, module_index, lesson_index)`: Triggers generation of lesson content.
- `check_lesson_content_status(request, syllabus_id, module_index, lesson_index)`: Checks the status of lesson content generation.
- `change_difficulty_view(request, syllabus_id)`: Handles requests to change the difficulty of a syllabus.