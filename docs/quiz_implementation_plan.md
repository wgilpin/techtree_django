# End-of-Lesson Quiz Implementation Plan (Django + Background Tasks)

**Goal:** Implement the dynamic, non-persistent, end-of-lesson quiz feature as defined in section 4.4 of `docs/PRD.md`, integrating with the existing Django and `django-background-tasks` architecture.

**Plan Details:**

1. **Core Logic & Data (`core` app):**
    * **Data Model (`core/models.py`):** Ensure a boolean field like `lesson_completed` exists on the `UserProgress` model. If not, add it.
    * **Migrations:** Run `python manage.py makemigrations core` and `python manage.py migrate`.

2. **Quiz AI Logic (New `quiz` app or within `lessons` app):**
    * **LangGraph Definition (e.g., `quiz/ai/graph.py`):**
        * Define `QuizLangGraph` similar to existing graphs (`lessons/ai/graph.py`, `syllabus/ai/graph.py`).
        * **State:** Define the graph's state schema (e.g., `current_question_index`, `questions_asked`, `answers_given`, `incorrect_subtopics`, `difficulty`, `lesson_id`, `user_id`, `task_id`). This state needs to be serializable to be passed via task parameters.
        * **Nodes:** Define Python functions for graph nodes: `initialize_quiz`, `generate_question` (calls LLM), `evaluate_answer` (calls LLM, tags sub-topics), `check_completion`, `record_result`, `generate_retry_quiz` (calls LLM), `finalize_quiz`.
        * **Prompts:** Develop specific LLM prompts for quiz generation, evaluation, and retry logic.

3. **Background Task Integration (`taskqueue` app):**
    * **Task Type (`taskqueue/constants.py` or similar):** Define a new task type, e.g., `PROCESS_QUIZ_INTERACTION`.
    * **Task Model (`taskqueue/models.py`):** The existing `Task` model's `params` JSON field should suffice to store the necessary quiz context (current state, user answer, etc.). The `result` field will store the output (next question, feedback, final status).
    * **Task Processor (`taskqueue/processors/quiz_processor.py`):** Create this new file.
        * Define a function `process_quiz_task(task)`:
            * Deserializes quiz state and parameters from `task.params`.
            * Instantiates or loads the `QuizLangGraph`.
            * Invokes the appropriate graph step based on the current state/request.
            * Handles LLM calls via the graph nodes.
            * Serializes the output (next question, feedback, final status) and updated state into `task.result`.
            * If the quiz is successfully completed, updates `UserProgress.lesson_completed = True` directly or queues another small task for it.
            * Marks the task as complete.

4. **Frontend Interaction (Django `lessons` app):**
    * **Trigger (`lessons/templates/lessons/lesson_detail.html`):** Add a button/link with an HTMX POST attribute targeting a new Django view.
    * **Views (`lessons/views.py`):**
        * `start_quiz_view(request, lesson_id)`: Creates initial `Task`, returns HTMX partial with `task.id` and polling setup.
        * `submit_quiz_answer_view(request, lesson_id)`: Creates `Task` to process answer, returns HTMX partial with new `task.id` and polling setup.
        * `quiz_action_view(request, lesson_id)`: Handles "Retry"/"Abandon", creates appropriate `Task`, returns HTMX response.
        * `poll_quiz_status_view(request, task_id)`: Checks `Task` status. If complete, renders and returns HTMX partial with results. If pending/running, returns empty response to continue polling.
    * **URLs (`lessons/urls.py`):** Define URL patterns for `start_quiz`, `submit_quiz_answer`, `quiz_action`, and `poll_quiz_status`.
    * **Templates (`lessons/templates/lessons/partials/`):** Create/update HTMX partials for quiz flow (starting, question display, feedback, final results, polling triggers). Implement logic to clear quiz elements when abandoning or completing.

**Conceptual Flow Diagram:**

```mermaid
sequenceDiagram
    participant User
    participant Frontend (Django/HTMX)
    participant TaskQueue (DB)
    participant BackgroundWorker
    participant QuizLangGraph
    participant LLM
    participant UserProgress (DB)

    User->>Frontend: Clicks "Start Quiz"
    Frontend->>Frontend: HTMX POST to start_quiz_view
    Frontend->>TaskQueue: Create Task (PROCESS_QUIZ_INTERACTION, initial_state) -> returns task_id
    Frontend->>Frontend: Render HTMX partial (_quiz_start_polling.html, includes task_id, hx-get=poll_url(task_id))
    Frontend-->>User: Display Quiz Starting...

    BackgroundWorker->>TaskQueue: Fetch Task (task_id)
    BackgroundWorker->>QuizLangGraph: Run initial step (initialize_quiz)
    QuizLangGraph->>LLM: Generate first question
    LLM-->>QuizLangGraph: First Question
    QuizLangGraph-->>BackgroundWorker: Result (First Question, next_state)
    BackgroundWorker->>TaskQueue: Update Task (task_id, status=complete, result={question: ..., state: ...})

    Frontend->>Frontend: HTMX GET to poll_quiz_status_view(task_id)
    Frontend->>TaskQueue: Get Task(task_id) status & result
    TaskQueue-->>Frontend: Task complete, result={question: ..., state: ...}
    Frontend->>Frontend: Render HTMX partial (_quiz_question.html with question, state)
    Frontend-->>User: Display First Question & Answer Form

    User->>Frontend: Submits Answer
    Frontend->>Frontend: HTMX POST to submit_quiz_answer_view (answer, state)
    Frontend->>TaskQueue: Create Task (PROCESS_QUIZ_INTERACTION, answer, state) -> returns new_task_id
    Frontend->>Frontend: Render HTMX partial (_quiz_processing.html, includes new_task_id, hx-get=poll_url(new_task_id))
    Frontend-->>User: Display Processing...

    BackgroundWorker->>TaskQueue: Fetch Task (new_task_id)
    BackgroundWorker->>QuizLangGraph: Run evaluation step (evaluate_answer, state, answer)
    QuizLangGraph->>LLM: Evaluate Answer + Sub-topic Tag
    LLM-->>QuizLangGraph: Evaluation Result
    QuizLangGraph->>BackgroundWorker: Result (Evaluation Text, next_state, is_complete, is_success)
    alt Quiz Complete (Success)
        BackgroundWorker->>UserProgress: Update lesson_completed = True
    end
    BackgroundWorker->>TaskQueue: Update Task (new_task_id, status=complete, result={feedback:..., next_state:..., final_status:...})


    Frontend->>Frontend: HTMX GET to poll_quiz_status_view(new_task_id)
    Frontend->>TaskQueue: Get Task(new_task_id) status & result
    TaskQueue-->>Frontend: Task complete, result={feedback:..., next_state:..., final_status:...}
    Frontend->>Frontend: Render HTMX partial (_quiz_feedback.html or _quiz_final_result.html)
    Frontend-->>User: Display Evaluation / Next Question / Final Status + Options

    %% ... similar flows for retry/abandon actions triggering tasks ...
