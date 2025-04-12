# Tech Tree

This project is a Django-based web application for adaptive learning, leveraging AI for syllabus generation and interactive lessons. It uses the Gemini API, Tavily API for internet search, and LangGraph for managing AI workflows. The system is designed for extensibility, maintainability, and asynchronous operation using background tasks.

---

## What it does

The Tech Tree application provides an adaptive learning platform with the following core features:

1. **User Onboarding:** Guides new users through an initial AI-powered assessment to gauge their knowledge level and generate a personalized syllabus.
2. **Syllabus Generation:**
    * Users specify a topic of interest.
    * The system searches the internet (via Tavily) and internal databases for relevant information.
    * Uses the Gemini API and LangGraph to generate a structured learning syllabus with modules and lessons.
    * Allows for syllabus refinement and updates.
3. **Interactive Lessons:**
    * Presents lesson content based on the generated syllabus.
    * Includes AI-powered features like:
        * Generating exercises and assessments tailored to the lesson.
        * Evaluating user answers and providing feedback.
        * Generating chat responses to user queries within the lesson context.
        * Adapting the difficulty or content based on user performance.
    * All major AI operations (syllabus generation, lesson content, onboarding assessment) are handled asynchronously via background tasks.
4. **User Authentication:** Standard Django user registration and login.
5. **Dashboard:** Provides users with an overview of their progress.
6. **Admin Interface:** Django admin for managing users, syllabi, lessons, and background tasks.

---

## Prerequisites

* Python 3.12 or higher
* A Google API key with access to the Gemini API
* A Tavily API key for internet search functionality (get one at [tavily.com](https://tavily.com))
* [uv](https://github.com/astral-sh/uv) for environment and dependency management (recommended)
* Required Python packages (see `pyproject.toml` for the full list), including:
  * `django`
  * `django-environ`
  * `google-generativeai`
  * `langgraph`
  * `langchain-community`
  * `tavily-python`
  * `django-background-tasks`
  * `python-dotenv`
  * `beautifulsoup4`
  * `markdown`, `mistune`, `pydantic`, `pyjwt`, `pymdown-extensions`, `python-jose[cryptography]`, `requests`
  * Type stubs and dev tools (see dev dependencies in `pyproject.toml`)

---

## Setup

1. **Clone the repository:**

    ```bash
    # Replace with the actual repository URL if applicable
    git clone <your-repository-url>
    cd techtree_django_project
    ```

2. **Create and activate a virtual environment:**

    It's highly recommended to use `uv` for managing virtual environments and dependencies.

    **Using `uv` (recommended):**

    If you don't have `uv` installed, install it first (e.g., `pip install uv`).

    ```bash
    uv venv
    # Activate the environment (use the command appropriate for your shell)
    # Example for bash/zsh:
    source .venv/bin/activate
    # Example for Windows cmd:
    # .venv\Scripts\activate
    # Example for Windows Powershell:
    # .venv\Scripts\Activate.ps1
    ```

3. **Install dependencies:**

    ```bash
    uv pip install -r pyproject.toml
    # For development dependencies (tests, type checking, etc.):
    uv pip install -r pyproject.toml --extra dev
    ```

    The full list of dependencies is managed in `pyproject.toml`.

4. **Create a `.env` file:**

    Create a file named `.env` in the root directory (`techtree_django_project`). Copy the contents of `.env.example` (if one exists) or add the following, replacing placeholders with your actual keys and settings:

    ```dotenv
    # Django Settings
    SECRET_KEY='your-super-secret-django-key' # CHANGE THIS! Generate a strong random key
    DEBUG=True # Set to False in production
    ALLOWED_HOSTS=localhost,127.0.0.1 # Add production hosts if needed

    # Database URL (Example for PostgreSQL, adjust as needed)
    # DATABASE_URL=postgres://user:password@host:port/dbname
    # Or leave blank to use the default SQLite configuration in settings.py for development

    # Required API Keys
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY
    TAVILY_API_KEY=YOUR_TAVILY_API_KEY

    # Optional LangSmith Tracing
    # LANGSMITH_TRACING=true
    # LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
    # LANGSMITH_API_KEY=YOUR_LANGSMITH_API_KEY

    # Optional Gemini Model Selection
    FAST_MODEL=gemini-1.5-pro-latest
    LARGE_MODEL=gemini-1.5-pro-latest
    ```

    **Important:**
    * Replace `'your-super-secret-django-key'` with a strong, unique secret key. You can generate one using Django's utilities or online tools.
    * Configure `DATABASE_URL` if you are using a database other than the default SQLite (e.g., PostgreSQL, MySQL).
    * Set `DEBUG=False` in a production environment.

    **For local development: Using Google Application Default Credentials (ADC)**

    For Google Cloud services like Gemini, using Application Default Credentials (ADC) is often the recommended approach for authentication, especially during local development, as it avoids needing to manage API keys directly in `.env` files.

    To set up ADC:

    1. **Install the Google Cloud CLI (`gcloud`):** Follow the instructions at [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install).
    2. **Log in to ADC:** Run the following command in your terminal and follow the browser prompts to authenticate with your Google account:

        ```bash
        gcloud auth application-default login
        ```

    Once ADC is configured, Google client libraries (including the one used by `langchain-google-genai`) will automatically detect and use these credentials. You might still need the `GEMINI_API_KEY` in your `.env` if other parts of the application rely on it directly via Django settings, but for direct Google library calls, ADC should take precedence.

    See the official guide for more details: [Set up Application Default Credentials for local development](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment)

5. **Apply database migrations:**

    ```bash
    python manage.py migrate
    ```

6. **Create a superuser (optional but recommended for accessing the admin interface):**

    ```bash
    python manage.py createsuperuser
    ```

    Follow the prompts to set a username, email, and password.

---

## Running the application

### 1. Start the Django development server

```bash
python manage.py runserver
```

### 2. Start the background task worker

The application uses [django-background-tasks](https://django-background-tasks.readthedocs.io/) for asynchronous processing of AI operations. You must run the background worker in a separate terminal for background tasks (syllabus generation, lesson content, onboarding assessment, etc.) to be processed:

```bash
python manage.py process_tasks
```

* You can run both the server and the worker at the same time in separate terminals.
* If you need to stop all Python processes (including the server and worker) on Windows, you can use the provided script:

```bash
./kill_servers.sh
```

### 3. Access the application

Open your web browser and navigate to `http://127.0.0.1:8000/` (or the address provided by `runserver`).

### 4. Access the Django admin interface (optional)

Navigate to `http://127.0.0.1:8000/admin/` and log in with the superuser credentials you created.

---

## Static Files

* Static files (CSS, JavaScript, images) are served from the `static/` directory.
* Additional static file directories are configured in `settings.py` via `STATICFILES_DIRS`.

---

## Project Structure and Design Documentation

* Each major app folder contains a `design.md` file with detailed design information.
* The file `docs/design_overview.md` provides a high-level summary of the application's architecture and responsibilities of each app.
* See these files for guidance on contributing or extending the system.

---

## Background Tasks and Asynchronous AI Operations

* All major AI operations (syllabus generation, lesson content, onboarding assessment) are handled asynchronously using the `taskqueue` app and `django-background-tasks`.
* The `taskqueue` app manages background task models, processing logic, and monitoring views.
* See `taskqueue/design.md` and `taskqueue/processors/design.md` for details.

---

## Model Selection and Configuration

* The application supports model selection for LLMs via environment variables (`FAST_MODEL`, `LARGE_MODEL`), which can be set in your `.env` file.

---

## Testing

* The project uses `pytest` and `pytest-django` for testing.
* Test discovery patterns are set in `pyproject.toml`.
* To run the test suite:

    ```bash
    pytest
    ```

---

## License

Copyright 2025 Will Gilpin
