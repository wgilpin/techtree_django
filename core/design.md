# core

**Name:** Core Application Logic and Data Models

**Description:**  
This folder contains the foundational logic, data models, and shared utilities for the application. It defines the primary database schema, core business logic, exception handling, constants, and the main views and URL routing for the core app. The code here is responsible for representing users, syllabi, modules, lessons, lesson content, user progress, and conversation history, as well as providing the main entry points for the core app's web interface.

---

## Files

### admin.py
Admin configuration for the core application's models, customizing how they appear and are managed in the Django admin interface.
- `ConversationHistoryAdmin`
  - `get_user(obj)`: Returns the username associated with the conversation message.
  - `get_lesson(obj)`: Returns the lesson title associated with the conversation message.
  - `rendered_content(obj)`: Returns the message content for display.
- `LessonContentAdmin`
  - `display_module_title_lesson_number(obj)`: Returns the module title and lesson number for a lesson content object.

### constants.py
Defines difficulty levels and mappings used throughout the application, and provides a utility for difficulty transitions.
- `get_lower_difficulty(current_level)`: Returns the next lower difficulty level, or None if already at the lowest.

### exceptions.py
Custom exception utilities and base exception classes for the application, with helpers for logging and raising errors.
- `log_and_propagate(new_exception_type, new_exception_message, original_exception, ...)`: Logs an error and raises a new exception, chaining the original.
- `log_and_raise_new(exception_type, exception_message, ...)`: Logs an error and raises a new exception, optionally breaking the exception chain.

### models.py
Defines the core database models for users, assessments, syllabi, modules, lessons, lesson content, user progress, and conversation history.
- No public methods except dunder methods (see model fields for structure).

### urls.py
URL configuration for the core app, mapping URL patterns to views.
- No public methods.

### views.py
Implements the main views for the core app, including the home page, dashboard, and user registration.
- `index(request)`: Renders the home page or redirects authenticated users to the dashboard.
- `dashboard(request)`: Renders the dashboard for logged-in users, showing their courses and progress.
- `register(request)`: Handles user registration using Django's UserCreationForm.