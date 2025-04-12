# syllabus

**Name:** Syllabus Management and Display

**Description:**  
This folder handles the logic related to syllabus management, including retrieval, formatting, and display. It provides services to interact with syllabus data and views to render syllabus details, module details, and lesson details based on the status of background generation tasks.

---

## Files

### admin.py
Minimal admin configuration for the syllabus app; most model registrations are handled in the core app.
- No public methods.

### apps.py
Django app configuration for the syllabus app.
- No public methods.

### services.py
Service layer for handling syllabus logic, including retrieval, formatting, and interaction with the SyllabusAI graph.
- `SyllabusService`
  - `_get_syllabus_ai_instance()`: Creates and returns an instance of the SyllabusAI.
  - `_format_syllabus_dict(syllabus_obj)`: Formats a Syllabus ORM object into a dictionary structure synchronously.
  - `get_syllabus_by_id(syllabus_id)`: Retrieves a specific syllabus by its primary key (UUID) synchronously.
  - `get_module_details_sync(syllabus_id, module_index)`: Retrieves details for a specific module within a syllabus synchronously.
  - `get_lesson_details_sync(syllabus_id, module_index, lesson_index)`: Retrieves details for a specific lesson within a syllabus module synchronously.
  - `get_or_generate_syllabus(topic, level, user)`: Synchronously gets or generates a syllabus for the given topic and level.

### urls.py
URL configuration for the syllabus app, mapping URL patterns to views for landing, generation, detail pages, and waiting pages.
- No public methods.

### views.py
Implements the views for the syllabus app, handling syllabus landing, generation triggering, detail display (syllabus, module, lesson), and waiting pages.
- `syllabus_landing(request)`: Placeholder view for the main syllabus page.
- `generate_syllabus_view(request)`: Handles syllabus generation by creating a background task and redirecting.
- `syllabus_detail(request, syllabus_id)`: Displays the details of a specific syllabus, based on background task status.
- `module_detail(request, syllabus_id, module_index)`: Displays the details of a specific module, based on background task status.
- `lesson_detail(request, syllabus_id, module_index, lesson_index)`: Displays the details of a specific lesson, based on background task status.
- `wait_for_generation(request, syllabus_id)`: Shows a waiting page while syllabus is being generated.