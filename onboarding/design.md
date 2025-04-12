# onboarding

**Name:** Onboarding Assessment and Syllabus Initialization

**Description:**  
This folder implements the onboarding assessment logic, user-facing views, and supporting services for evaluating a user's initial knowledge and generating a personalized syllabus. It provides the AI-driven assessment flow, question/answer handling, and the orchestration of syllabus creation based on assessment results. The code here enables new users to be assessed and onboarded into the learning platform with an appropriate starting point.

---

## Files

### admin.py

Minimal admin configuration for the onboarding app; no models are registered here.

- No public methods.

### ai.py

Encapsulates the AI logic for the onboarding assessment, including state management, question generation, answer evaluation, and final assessment calculation.

- `AgentState`: TypedDict representing the state for onboarding assessment.
- `_get_llm(model_key="FAST_MODEL", temperature=0.2)`: Gets the LLM instance based on settings.
- `TechTreeAI`
  - `__init__()`: Initializes the AI components and search tool.
  - `initialize_state(topic)`: Creates the initial state for a new assessment.
  - `perform_internet_search(state)`: Performs internet search based on the topic.
  - `generate_question(state)`: Generates the next assessment question.
  - `evaluate_answer(state, answer)`: Evaluates the user's answer.
  - `should_continue(state)`: Determines if the assessment should continue.
  - `calculate_final_assessment(state)`: Calculates the final assessment results.

### logic.py

Implements the business logic for onboarding assessment, including question flow, answer handling, and difficulty adjustment.

- `get_ai_instance()`: Instantiates the AI logic class.
- `generate_next_question(assessment_state, ai_instance, settings)`: Generates the next question and updates assessment state.
- `handle_normal_answer(assessment_state, ai_instance, answer, settings)`: Updates assessment state for a normal answer submission.
- `handle_skip_answer(assessment_state, settings)`: Updates assessment state for a skipped answer.

### prompts.py

Defines prompt templates for the onboarding AI graph, including assessment, question generation, answer evaluation, and search query prompts.

- No public methods.

### urls.py

URL configuration for the onboarding app, mapping URL patterns to assessment, answer submission, syllabus initiation, and polling views.

- No public methods.

### views.py

Implements the main views for the onboarding app, including assessment start, answer submission, skipping, syllabus initiation, and polling.

- `get_session_value(session, key, default=None)`: Asynchronously gets a value from the session.
- `set_session_value(session, key, value)`: Asynchronously sets a value in the session.
- `del_session_key(session, key)`: Asynchronously deletes a key from the session.
- `create_user_assessment(**kwargs)`: Asynchronously creates a UserAssessment record.
- `start_assessment_view(request, topic)`: Starts a new onboarding assessment for a given topic.
- `submit_answer_view(request)`: Processes a user's submitted answer during an assessment.
- `dict_to_agent_state(d)`: Helper to coerce a dict to AgentState TypedDict.
- `finalize_assessment_and_trigger_syllabus_task(request, user, assessment_state)`: Finalizes assessment, saves result, and creates syllabus generation task.
- `assessment_page_view(request, topic)`: Renders the main assessment page.
- `skip_assessment_view(request)`: Handles the request to skip the onboarding assessment.
- `initiate_syllabus_view(request)`: Initiates syllabus generation after assessment completion.
- `generating_syllabus_view(request, syllabus_id)`: Renders the page indicating syllabus generation is in progress.
- `poll_syllabus_status_view(request, syllabus_id)`: Polls the status of syllabus generation.
