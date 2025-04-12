# lessons/ai

**Name:** Lesson Interaction AI Graph and Node Logic

**Description:**  
This folder implements the AI-driven logic for lesson interactions, including the orchestration of chat, exercise, and assessment flows using a LangGraph workflow. It defines the state structure, prompt templates, and node functions for intent classification, chat response, exercise/assessment generation, and answer evaluation. The code here enables dynamic, context-aware lesson experiences powered by LLMs.

---

## Files

### lesson_graph.py
Defines and manages the LangGraph workflow for lesson interactions, including node orchestration and routing.
- `_route_message_logic(state)`: Determines the next node based on the current interaction mode.
- `LessonInteractionGraph`
  - `__init__()`: Initializes and compiles the lesson interaction graph.
  - `_create_workflow()`: Defines the structure (nodes and edges) of the lesson interaction graph.
  - `process_chat_turn(current_state, history_context)`: Processes one turn of the conversation using the compiled graph.

### nodes.py
Implements the node functions for the lesson interaction graph, including intent classification, chat, exercise, assessment, and evaluation logic.
- `_truncate_history(history)`: Truncates conversation history for prompt context.
- `_format_history_for_prompt(history)`: Formats conversation history for prompts.
- `_get_llm(temperature=0.2)`: Initializes and returns the LangChain LLM model.
- `_parse_llm_json_response(response)`: Attempts to parse a JSON object from the LLM response text.
- `_map_intent_to_mode(intent_str, state)`: Maps the classified intent string to an interaction mode.
- `classify_intent(state)`: Classifies the user's intent and updates the state.
- `generate_chat_response(state)`: Generates a chat response from the AI.
- `generate_new_exercise(state)`: Generates a new, unique exercise for the lesson.
- `_prepare_evaluation_context(active_exercise, active_assessment)`: Prepares the context dictionary for the evaluation prompt.
- `evaluate_answer(state)`: Evaluates the user's submitted answer.
- `generate_new_assessment(state)`: Generates a new assessment question.

### prompts.py
Defines prompt templates for the lesson AI components, including chat, exercise, assessment, and intent classification.
- No public methods.

### state.py
Defines the state dictionary structure for the lesson interaction AI graph.
- No public methods.