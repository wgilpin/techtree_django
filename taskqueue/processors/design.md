# taskqueue/processors

**Name:** Background Task Processors

**Description:**  
This folder contains the synchronous processing logic for different types of background AI tasks defined in the `taskqueue` app. Each processor handles a specific task type (e.g., lesson interaction, content generation, syllabus generation, onboarding assessment) by interacting with the relevant AI services and updating the database state.

---

## Files

### interaction_processor.py
Synchronous processor for handling lesson interaction tasks (chat, answers) from the background queue.
- `process_lesson_interaction(task)`: Processes a lesson interaction task, invoking the lesson AI graph and updating state/history.

### lesson_processor.py
Synchronous processor for handling lesson content generation tasks from the background queue.
- `process_lesson_content(task)`: Processes a lesson content generation task, invoking the content service and saving the result.

### onboarding_processor.py
Synchronous processor for handling onboarding assessment tasks (answer evaluation, next question generation) from the background queue.
- `process_onboarding_assessment(task)`: Processes an onboarding assessment task, calling the appropriate logic functions.

### syllabus_utils.py
Synchronous processor for handling syllabus generation tasks from the background queue. (Note: Previously might have been syllabus_processor.py)
- `process_syllabus_generation(task)`: Processes a syllabus generation task, invoking the syllabus AI graph and saving the result.