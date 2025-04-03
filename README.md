# Tech Tree Django Project

This project is a Django-based web application for adaptive learning, leveraging AI for syllabus generation and interactive lessons. It uses the Gemini API, Tavily API for internet search, and LangGraph for managing AI workflows.

## What it does

The Tech Tree application provides an adaptive learning platform with the following core features:

1.  **User Onboarding:** Guides new users through an initial assessment to gauge their knowledge level.
2.  **Syllabus Generation:**
    *   Allows users to specify a topic of interest.
    *   Searches the internet (via Tavily) and potentially internal databases for relevant information.
    *   Uses the Gemini API and LangGraph to generate a structured learning syllabus with modules and lessons.
    *   Allows for syllabus refinement and updates.
3.  **Interactive Lessons:**
    *   Presents lesson content based on the generated syllabus.
    *   Includes AI-powered features like:
        *   Generating exercises and assessments tailored to the lesson.
        *   Evaluating user answers and providing feedback.
        *   Generating chat responses to user queries within the lesson context.
        *   Adapting the difficulty or content based on user performance (though the exact adaptation logic might vary based on implementation).
4.  **User Authentication:** Standard Django user registration and login.
5.  **Dashboard:** Provides users with an overview of their progress.

## Prerequisites

-   Python 3.12 or higher
-   A Google API key with access to the Gemini API
-   A Tavily API key for internet search functionality (get one at [tavily.com](https://tavily.com))
-   Required Python packages (see `pyproject.toml` for the full list), including:
    -   `django`
    -   `google-generativeai`
    -   `langgraph`
    -   `tavily-python`
    -   `django-environ`
    -   `python-dotenv`

## Setup

1.  **Clone the repository:**

    ```bash
    # Replace with the actual repository URL if applicable
    git clone <your-repository-url>
    cd techtree_django_project
    ```

2.  **Create and activate a virtual environment:**

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

3.  **Install dependencies:**

    ```bash
    uv pip install -r pyproject.toml --all-extras
    # or install main and dev dependencies separately
    # uv pip install -r pyproject.toml
    # uv pip install -r pyproject.toml --extra dev
    ```

4.  **Create a `.env` file:**

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

    # Optional Gemini Model Override
    # GEMINI_MODEL=gemini-1.5-pro-latest
    ```

    **Important:**
    *   Replace `'your-super-secret-django-key'` with a strong, unique secret key. You can generate one using Django's utilities or online tools.
    *   Configure `DATABASE_URL` if you are using a database other than the default SQLite (e.g., PostgreSQL, MySQL).
    *   Set `DEBUG=False` in a production environment.

5.  **Apply database migrations:**

    ```bash
    python manage.py migrate
    ```

6.  **Create a superuser (optional but recommended for accessing the admin interface):**

    ```bash
    python manage.py createsuperuser
    ```
    Follow the prompts to set a username, email, and password.

## Running the application

1.  **Start the Django development server:**

    ```bash
    python manage.py runserver
    ```

2.  **Access the application:**

    Open your web browser and navigate to `http://127.0.0.1:8000/` (or the address provided by `runserver`).

3.  **Access the Django admin interface (optional):**

    Navigate to `http://127.0.0.1:8000/admin/` and log in with the superuser credentials you created.