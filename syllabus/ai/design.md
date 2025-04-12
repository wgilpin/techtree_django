# syllabus/ai

**Name:** Syllabus Generation AI Graph and Node Logic

**Description:**  
This folder implements the AI-driven logic for syllabus generation, including the orchestration of database search, internet search, and LLM-based generation/update using a LangGraph workflow. It defines the state structure, prompt templates, configuration, and node functions for creating and refining syllabi.

---

## Files

### config.py
Handles configuration for external APIs (Gemini, Tavily) used in syllabus generation, loading keys from Django settings.
- No public methods.

### nodes.py
Implements the node functions for the syllabus generation LangGraph, handling state initialization, database search, internet search, LLM generation/update, validation, and saving.
- `initialize_state(_, topic, knowledge_level, user_id)`: Initializes the graph state with topic, knowledge level, and user ID.
- `search_database(state)`: Searches the database for an existing syllabus matching the criteria using Django ORM.
- `search_internet(state, tavily_client)`: Performs a web search using Tavily to gather context.
- `_parse_llm_json_response(response_text)`: Attempts to parse a JSON object from the LLM response text.
- `_validate_syllabus_structure(syllabus, context)`: Performs basic validation on the syllabus dictionary structure.
- `generate_syllabus(state, llm_model)`: Generates a new syllabus using the LLM based on search results.
- `update_syllabus(state, feedback, llm_model)`: Updates the current syllabus based on user feedback using the LLM.
- `_validate_syllabus_dict(syllabus_dict)`: Validates required keys and structure of a syllabus dictionary before saving.
- `_get_user_obj(user_id)`: Retrieves the User object based on the provided ID.
- `_get_or_create_syllabus_instance(state, syllabus_dict, user_obj, ...)`: Gets or creates the Syllabus ORM instance.
- `_save_modules_and_lessons(syllabus_instance, modules_data)`: Saves the modules and lessons for a given syllabus instance.
- `save_syllabus(state)`: Saves the current syllabus (generated or existing) to the database.
- `end_node(state)`: Terminal node for the graph, returns the state unchanged.

### nodes_old.py
(Legacy) Implements older versions of node functions for the syllabus generation LangGraph.
- `initialize_state(_, topic, knowledge_level, user_id)`: Initializes the graph state.
- `search_database(state, db_service)`: Searches the database for an existing syllabus.
- `search_internet(state, tavily_client)`: Performs a web search using Tavily.
- `_parse_llm_json_response(response_text)`: Parses JSON from LLM response.
- `_validate_syllabus_structure(syllabus, context)`: Validates syllabus structure.
- `generate_syllabus(state, llm_model)`: Generates a new syllabus using the LLM.
- `update_syllabus(state, feedback, llm_model)`: Updates the syllabus based on feedback.
- `save_syllabus(state, db_service)`: Saves the syllabus to the database.
- `end_node(_)`: Terminal node for the graph.

### prompts.py
Defines prompt templates for syllabus generation and updates.
- No public methods.

### state.py
Defines the state dictionary structure (TypedDict) for the syllabus generation graph.
- No public methods.

### syllabus_graph.py
Defines and manages the LangGraph workflow for syllabus generation, orchestrating node execution.
- `SyllabusAI`
  - `__init__()`: Initializes the SyllabusAI graph and stores dependencies.
  - `_create_workflow()`: Defines the structure (nodes and edges) of the syllabus LangGraph workflow.
  - `_should_search_internet(state)`: Conditional Edge: Determines if web search is needed.
  - `initialize(topic, knowledge_level, user_id)`: Initializes the internal state for a new run.
  - `get_or_create_syllabus()`: Retrieves an existing syllabus or orchestrates the creation of a new one.
  - `update_syllabus(feedback)`: Updates the current syllabus based on user feedback.
  - `get_or_create_syllabus_sync()`: Synchronous alias for get_or_create_syllabus (for test compatibility).
  - `save_syllabus()`: Saves the current syllabus in the state to the database.
  - `get_syllabus()`: Returns the current syllabus dictionary held in the agent's state.
  - `clone_syllabus_for_user(user_id)`: Clones the current syllabus in the state for a specific user.
  - `delete_syllabus()`: Deletes the syllabus corresponding to the current state from the database.

### utils.py
Provides utility functions, including a retry mechanism for function calls.
- `call_with_retry(func, *args, max_retries, initial_delay, **kwargs)`: Calls a function with exponential backoff retry logic.