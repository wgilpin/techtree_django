# Django Rewrite Plan for TechTree Application

This document outlines the plan to rewrite the existing Flask frontend and FastAPI backend into a unified Django monolithic application. The primary motivation is to simplify the architecture and eliminate the complexities of maintaining a separate API contract between the frontend and backend.

**Guiding Principle:** Start the new Django project in a clean, separate directory to ensure isolation from the existing codebase during development.

---

**Phase 1: Project Setup & Core Foundation**

1.  **Initialize Django Project:**
    *   **Create a new, separate directory** for the Django project (e.g., `mkdir ../techtree_django && cd ../techtree_django` or `mkdir django_app && cd django_app` relative to the current project root). This isolates the new codebase.
    *   Initialize the project structure within this new directory: `django-admin startproject techtree_django .`
    *   Create a core Django app for shared functionality: `python manage.py startapp core`.
2.  **Configure Settings (`settings.py`):**
    *   Set up database connection (likely SQLite initially, matching the current setup). Confirm the exact path/name of the current SQLite database file (`backend/techtree_db.json` seems incorrect, likely `backend/services/some_db_name.sqlite` - **needs verification**).
    *   Configure `INSTALLED_APPS` (add `'core'`), `MIDDLEWARE`, `TEMPLATES` (pointing to the existing `frontend/templates` directory initially, adapting settings as needed).
    *   Configure `STATIC_URL` and `STATICFILES_DIRS` (pointing to `frontend/static` initially).
3.  **Dependency Management (`pyproject.toml`):**
    *   Navigate to the new Django project directory.
    *   Initialize `uv`: `uv init`.
    *   Add Django: `uv add django`.
    *   Add other necessary core dependencies (e.g., `django-environ`).
    *   Add AI-related dependencies (`langchain`, `langgraph`, etc. - copy versions from the original `pyproject.toml`).
    *   Ensure Flask, FastAPI, and their specific dependencies (e.g., `uvicorn`) are *not* added.
4.  **Define Core Models (`core/models.py`):**
    *   Translate the existing database schema (likely defined implicitly or in `backend/services/schema.sql`) and Pydantic models (`backend/models.py`) into Django ORM models. Focus on core entities like Users, Syllabuses, Lessons, Progress first.
    *   Define relationships (ForeignKey, ManyToManyField, OneToOneField).
5.  **Database Migrations:**
    *   Run `python manage.py makemigrations` to create initial database schema migrations based on the Django models.
    *   Run `python manage.py migrate` to apply the schema to a *new*, clean database for the Django project.
6.  **Data Migration Strategy:**
    *   Plan how to transfer data from the *existing* SQLite database into the *new* Django-managed schema.
    *   This will likely involve writing a custom Django management command (`python manage.py <custom_migrate_data>`) that:
        *   Connects to the *old* database file.
        *   Reads data table by table.
        *   Transforms data as needed to fit the new Django model structure.
        *   Populates the new models using the Django ORM (`YourModel.objects.create(...)` or `bulk_create`).
        *   Requires careful handling of relationships (e.g., migrating users first, then objects referencing users) and potential data type differences.

---

**Phase 2: Authentication & Basic Structure**

1.  **Implement Authentication:**
    *   Leverage Django's built-in `django.contrib.auth` system.
    *   Create views (`core/views.py`) for user registration, login, logout using Django's class-based views or function-based views.
    *   Create Django forms (`core/forms.py`) for registration and login.
    *   Adapt existing templates (`frontend/templates/login.html`, `frontend/templates/register.html`) using Django template tags (`{% csrf_token %}`, `{{ form.as_p }}`, `{% url %}`) and forms. Copy these templates into `core/templates/registration/`.
    *   Ensure password hashing compatibility or plan for password resets during data migration.
2.  **Set Up Base Templates & Static Files:**
    *   Copy `frontend/templates/base.html` to `core/templates/base.html`.
    *   Adapt `base.html` to use Django template tags (e.g., `{% load static %}`, `{% url %}`, `{% block %}`).
    *   Copy `frontend/static/` contents into the Django project's configured static files directory (e.g., `core/static/core/`).
    *   Ensure static CSS/JS are correctly loaded using `{% static 'path/to/file' %}`.
3.  **Create Core Views/URLs:**
    *   Set up basic URL routing in `techtree_django/urls.py` and include `core.urls`.
    *   Create `core/urls.py`.
    *   Create a simple dashboard view (`core/views.py`) requiring login (`@login_required` decorator or `LoginRequiredMixin`).
    *   Adapt `frontend/templates/dashboard.html` (copy to `core/templates/core/dashboard.html`) for Django context.

---

**Phase 3: Feature Porting (Iterative)**

*   *For each major feature (Onboarding, Syllabus, Lessons):*
    1.  **Create Django App:** `python manage.py startapp <feature_name>` (e.g., `lessons`). Add it to `INSTALLED_APPS`.
    2.  **Define Feature Models:** Add any feature-specific models to the app's `models.py` and run `makemigrations/migrate`.
    3.  **Port Backend Logic:**
        *   Translate logic from the corresponding FastAPI service (`backend/services/<feature>_service.py`) into Django views (`<feature_name>/views.py`) or potentially a separate service layer (`<feature_name>/services.py`) within the Django app.
        *   Use the Django ORM for all database interactions.
    4.  **Port Frontend Logic:**
        *   Translate logic from the corresponding Flask blueprint (`frontend/<feature>/<feature>.py`) into the Django app's `views.py`.
        *   Define URL patterns in the app's `urls.py` and include them in the main project `urls.py`.
    5.  **Adapt Templates:**
        *   Copy relevant templates (e.g., `frontend/templates/<feature>.html`) into the Django app's `templates/<feature_name>/` directory.
        *   Update templates to use Django template syntax, context variables passed from views, and Django forms if applicable.
    6.  **Integrate AI Components:**
        *   Identify the AI logic (`backend/ai/<feature>/*`) associated with the feature.
        *   Refactor AI logic into reusable functions/classes, potentially within the Django app (`<feature_name>/ai.py`) or a shared `ai` app.
        *   Call the relevant LangGraph/AI functions from within Django views. **Use Django's async views (`async def my_view(...)`)** to properly handle the async nature of the AI components without blocking the server.
        *   Pass necessary data from the Django request/models to the AI functions and handle the results appropriately for display in templates.

---

**Phase 4: Testing & Refinement**

1.  **Port Existing Tests:**
    *   Adapt tests from `backend/tests/` to use Django's testing framework (`django.test.TestCase` or `pytest-django`).
    *   Update API/service calls to interact with Django views (`self.client.get/post`) or directly call service functions.
    *   Adapt database fixtures and setup/teardown logic for the Django test runner and ORM.
2.  **Write New Tests:**
    *   Add tests for Django-specific components: views (testing context, template used, status codes), forms, model methods, template rendering logic.
    *   Ensure adequate coverage for the ported logic and AI integrations within the Django context.
3.  **Static Analysis:**
    *   Configure and run `mypy .` regularly within the Django project directory to catch type errors.
    *   Use linters like `ruff` or `flake8`.
4.  **Refinement:**
    *   Address any issues found during testing.
    *   Optimize Django ORM queries (`select_related`, `prefetch_related`).
    *   Ensure consistent coding style and adherence to Django best practices.

---

**Phase 5: Deployment**

1.  **Configure Production Settings:**
    *   Use `django-environ` or environment variables for sensitive settings (`SECRET_KEY`, `DATABASE_URL`).
    *   Set `DEBUG = False`.
    *   Configure `ALLOWED_HOSTS`.
    *   Set up static file serving for production (e.g., using WhiteNoise or `python manage.py collectstatic` for a web server like Nginx).
2.  **Choose ASGI Server:**
    *   Select and configure an ASGI server like Gunicorn (with Uvicorn workers: `gunicorn myproject.asgi:application -k uvicorn.workers.UvicornWorker`) or Daphne to run the async Django application.
3.  **Update Deployment Scripts:**
    *   Modify `start.sh` or other deployment mechanisms to:
        *   Navigate to the new Django project directory.
        *   Install dependencies using `uv sync` (if using lock files) or `uv pip install -r requirements.txt`.
        *   Run database migrations (`python manage.py migrate`).
        *   Collect static files (`python manage.py collectstatic --noinput`).
        *   Run the chosen ASGI server.

---

**Visual Plan (Mermaid):**

```mermaid
graph TD
    A[Phase 1: Setup & Core Models] --> B(Define Models & Migrations);
    B --> C(Configure Settings);
    C --> D(Plan Data Migration);

    D --> E[Phase 2: Auth & Base UI];
    E --> F(Implement Auth Views/Templates);
    F --> G(Adapt Base Template & Static Files);

    G --> H[Phase 3: Feature Porting (Iterative)];
    H -- Onboarding --> I(Port Onboarding App);
    H -- Syllabus --> J(Port Syllabus App);
    H -- Lessons --> K(Port Lessons App);
    I --> L(Integrate AI);
    J --> L;
    K --> L;

    L --> M[Phase 4: Testing & Refinement];
    M --> N(Port/Write Tests);
    N --> O(Run Mypy/Linters);
    O --> P(Refine Code);

    P --> Q[Phase 5: Deployment];
    Q --> R(Configure Production Settings);
    R --> S(Set up ASGI Server);
    S --> T(Update Deployment Scripts);

    subgraph Feature Porting Cycle
        direction LR
        FP1(Create App) --> FP2(Define Models);
        FP2 --> FP3(Port Backend Logic);
        FP3 --> FP4(Port Frontend Logic);
        FP4 --> FP5(Adapt Templates);
        FP5 --> FP6(Integrate AI);
    end

    H --> FP1;
    FP6 --> H;

```

---

**Key Considerations & Risks:**

*   **Data Migration:** Accuracy is paramount. Requires careful planning, scripting, and verification. Test thoroughly on a copy of the production data.
*   **AI Integration:** Ensure async AI calls are non-blocking using Django's `async def` views. Monitor performance.
*   **Effort Estimation:** This is a substantial rewrite. Allocate adequate time and resources.
*   **Testing:** Comprehensive testing (ported and new) is crucial for a successful migration.
*   **Database Schema Verification:** Double-check the *actual* current schema before defining Django models.