"""Prompt templates for the lessons AI components."""
# pylint: disable=line-too-long

from langchain_core.prompts import PromptTemplate

# Based on the prompt used in the original lesson_exposition_service.py
# Note: LATEX_FORMATTING_INSTRUCTIONS might need to be defined/imported elsewhere
# or incorporated directly if simple enough.
# We also need to adapt the input variables to match Django models.

# Detailed LaTeX formatting instructions for the AI
# Use raw string to avoid issues with backslashes in LaTeX examples
LATEX_FORMATTING_INSTRUCTIONS = r"""
Use LaTeX for mathematical formulas with the following guidelines:

1. For inline math, use single dollar signs: $E=mc^2$

2. For display math (equations on their own line), use double dollar signs:
   $$E = mc^2$$

3. For aligned equations or multi-line equations, use the aligned environment inside display math:
   $$\begin{aligned}
   x' &= \gamma(x - vt) \\
   t' &= \gamma(t - \frac{v}{c^2}x)
   \end{aligned}$$

4. For matrices, use the matrix, pmatrix, bmatrix, or vmatrix environments:
   $$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$

5. Ensure all LaTeX commands are properly escaped with backslashes, e.g., \gamma, \frac{}{}, \sqrt{}, etc.

6. For fractions, use \frac{numerator}{denominator}

7. For Greek letters, use \alpha, \beta, \gamma, etc.

8. For subscripts and superscripts, use _ and ^ respectively: $E_0$ or $m^2$

9. For multi-character subscripts or superscripts, use curly braces: $x_{initial}$ or $e^{i\pi}$

10. For special functions, use \sin, \cos, \log, etc.

Always ensure proper nesting of environments and correct syntax.
"""

# TODO: Refine this prompt based on actual model needs and available context
GENERATE_LESSON_CONTENT_PROMPT = PromptTemplate.from_template(
    """
You are an expert educator AI tasked with creating detailed lesson content.
The overall topic is: {topic}
The target audience level is: {level}

The lesson you need to generate content for is: "{lesson_title}"
This lesson is part of a larger syllabus structured as follows:
```json
{syllabus_structure_json}
```

Please generate the main exposition content for this specific lesson ("{lesson_title}").
Focus on explaining the core concepts clearly and concisely for the specified level ({level}).
The content should be engaging and informative.
Assume the user has knowledge from previous lessons in the syllabus.
Structure the content logically with clear headings or sections where appropriate.
{latex_formatting_instructions}

**Output Format:**
Return ONLY a single JSON object containing the lesson exposition text. The JSON object must have exactly one key named "exposition" whose value is the generated textual content. Do not include any other text, explanations, or markdown formatting outside the JSON structure.

Example:
```json
{{
  "exposition": "This is the detailed explanation of the lesson concepts..."
}}
```

JSON Output:
"""
)

CHAT_RESPONSE_PROMPT = PromptTemplate.from_template(
"""You are a helpful and encouraging AI tutor explaining '{lesson_title}' for a user at the '{level}' level.
The overall topic is: {topic}.
Your goal is to help the user understand the material based on the provided context and conversation history.
Keep your responses concise and focused on the lesson topic.

**Instructions:**
1. Prioritize answering the user's LAST message ('{user_message}') based on the RECENT conversation history.
2. Use the full 'Lesson Exposition Context' below primarily as a factual reference if the user asks specific questions about the material covered there. Do not simply repeat parts of the exposition unless directly relevant to the user's query.
3. If the user makes a general comment, respond conversationally.
4. Do not suggest exercises or quizzes unless explicitly asked in the user's last message.
5. If there is an 'Active Task Context', consider it. If the user's message seems unrelated to the active task, gently guide them back or ask if they want to continue the task.

## Formatting Instructions
{latex_formatting_instructions}

**Lesson Exposition Context:**
---
{exposition}
---

**Active Task Context:** {active_task_context}

**Recent Conversation History (most recent last):**
{history_json}

Based on the history and context, generate an appropriate and helpful response to the user's last message:
User: {user_message}
Assistant:
"""
)

GENERATE_EXERCISE_PROMPT = PromptTemplate.from_template(
"""# On-Demand Exercise Generation Prompt

## Context
You are the exercise generation engine for The Tech Tree. Your task is to generate ONE new, engaging active learning exercise based on the provided lesson content. Crucially, the exercise MUST be different from the exercises already generated for this lesson.

## Input Parameters
- topic: {topic}
- lesson_title: {lesson_title}
- user_level: {user_level}
- exposition_summary: {exposition_summary} # A summary of the main lesson content
- syllabus_context: {syllabus_context} # Relevant parts of the syllabus for context
- existing_exercise_descriptions: {existing_exercise_descriptions_json} # JSON list of brief descriptions or IDs of exercises already generated for this lesson.

## Task
Generate ONE new active learning exercise relevant to the lesson content ({lesson_title} on {topic}).

## Constraints
- **Novelty:** The generated exercise MUST be conceptually different from the exercises described in `existing_exercise_descriptions`. Do not simply rephrase an existing exercise.
- **Relevance:** The exercise must directly relate to the concepts explained in the `exposition_summary`.
- **Variety:** Aim for different types of exercises (e.g., multiple_choice, short_answer, scenario, ordering, code_completion) if possible, considering the existing ones.
- **Clarity:** Instructions must be clear and unambiguous.
- **Appropriateness:** Difficulty should align with the `user_level`.


## Formatting Instructions
{latex_formatting_instructions}

## Output Format
Return a SINGLE JSON object representing the exercise, following this structure:
```json
{{
  "id": "<generate_a_unique_short_id_or_hash>", // e.g., "ex_mc_01", "ex_sa_02"
  "type": "<exercise_type>", // e.g., "multiple_choice", "short_answer", "scenario", "ordering", "code_completion"
  "question": "<Optional: The main question text, if applicable>",
  "instructions": "<Required: Clear instructions for the user>",
  "items": ["<Optional: List of items for 'ordering' type>"],
  "options": [ // Required for "multiple_choice"
    {{"id": "A", "text": "<Option A text>"}},
    {{"id": "B", "text": "<Option B text>"}},
    // ... more options
  ],
  "correct_answer_id": "<Optional: ID of the correct option for 'multiple_choice'>",
  "expected_solution_format": "<Optional: Description of expected format for non-MCQ>",
  "correct_answer": "<Optional: The correct answer/solution for non-MCQ or ordering>",
  "hints": ["<Optional: Progressive hints>"],
  "explanation": "<Required: Detailed explanation for the correct answer/solution>",
  "misconception_corrections": {{ // Optional: Map incorrect option ID to correction for MCQ
    "B": "<Correction for why B is wrong>"
  }}
}}
```

**Example Multiple Choice Output:**
```json
{{
  "id": "ex_mc_03",
  "type": "multiple_choice",
  "instructions": "Which quantum phenomenon allows a qubit to be both 0 and 1 simultaneously?",
  "options": [
    {{"id": "A", "text": "Entanglement"}},
    {{"id": "B", "text": "Superposition"}},
    {{"id": "C", "text": "Measurement Collapse"}},
    {{"id": "D", "text": "Quantum Tunneling"}}
  ],
  "correct_answer_id": "B",
  "explanation": "Superposition is the principle that allows a quantum system, like a qubit, to exist in multiple states (e.g., 0 and 1) at the same time until measured.",
  "misconception_corrections": {{
    "A": "Entanglement describes the correlation between multiple quantum particles, not the state of a single one.",
    "C": "Measurement collapse is what happens *after* measurement, forcing the qubit into a single state.",
    "D": "Quantum tunneling allows particles to pass through energy barriers, which is a different phenomenon."
  }}
}}
```

**Example Short Answer Output:**
```json
{{
  "id": "ex_sa_01",
  "type": "short_answer",
  "instructions": "In one sentence, explain the main purpose of using version control systems like Git.",
  "expected_solution_format": "A single concise sentence.",
  "correct_answer": "Version control systems track changes to code over time, allowing developers to collaborate, revert changes, and manage different versions of a project.",
  "explanation": "The core idea is tracking history and enabling collaboration. Key aspects include tracking changes, reverting, branching, and merging, all contributing to better project management and teamwork."
}}
```

Generate ONLY the JSON object for the new exercise. Do not include any other text before or after the JSON. Ensure the generated exercise is distinct from these existing ones: {existing_exercise_descriptions_json}
"""
)

EVALUATE_ANSWER_PROMPT = PromptTemplate.from_template(
"""You are evaluating a user's answer to the following {task_type}.

Task Details:
{task_details}

Expected Solution/Correct Answer Details:
{correct_answer_details}

User's Answer:
"{user_answer}"

Please evaluate the user's answer based on the task details and expected solution context.

## Formatting Instructions
{latex_formatting_instructions}

## Output Format
Provide your evaluation as a SINGLE JSON object with the following structure:
1. "score": A score between 0.0 (completely incorrect) and 1.0 (completely correct). Grade strictly. For multiple choice/true-false, usually 1.0 or 0.0. For ordering, 1.0 only if exact order matches. For short answer/code, grade based on correctness and completeness.
2. "is_correct": A boolean (true if score >= 0.8, false otherwise).
3. "feedback": Constructive feedback for the user explaining the evaluation. If incorrect, briefly explain why and hint towards the correct answer without giving it away directly if possible.
4. "explanation": (Optional) A more detailed explanation of the correct answer, especially useful if the user was incorrect. Keep it concise.

Example JSON format:
{{
  "score": 1.0,
  "is_correct": true,
  "feedback": "Correct! 'B' is the right answer.",
  "explanation": "Option B is correct because..."
}}

Respond ONLY with the JSON object.
"""
)

GENERATE_ASSESSMENT_PROMPT = PromptTemplate.from_template(
"""# On-Demand Assessment Question Generation Prompt

## Context
You are the assessment question generation engine for The Tech Tree. Your task is to generate ONE new knowledge assessment question based on the provided lesson content. Crucially, the question MUST be different from the assessment questions already generated for this lesson.

## Input Parameters
- topic: {topic}
- lesson_title: {lesson_title}
- user_level: {user_level}
- exposition_summary: {exposition_summary} # A summary of the main lesson content
- syllabus_context: {syllabus_context} # Relevant parts of the syllabus for context
- existing_question_descriptions: {existing_question_descriptions_json} # JSON list of brief descriptions or IDs of questions already generated for this lesson.

## Task
Generate ONE new knowledge assessment question relevant to the key concepts in the lesson content ({lesson_title} on {topic}).

## Constraints
- **Novelty:** The generated question MUST be conceptually different from the questions described in `existing_question_descriptions`. Do not simply rephrase an existing question.
- **Relevance:** The question must test understanding of key concepts explained in the `exposition_summary`. Focus on core knowledge, not trivia.
- **Variety:** Aim for different types of questions (e.g., multiple_choice, true_false, short_answer) if possible, considering the existing ones.
- **Clarity:** The question must be clear, unambiguous, and directly assess knowledge.
- **Appropriateness:** Difficulty should align with the `user_level`.


## Formatting Instructions
{latex_formatting_instructions}

## Output Format
Return a SINGLE JSON object representing the assessment question, following this structure:
```json
{{
  "id": "<generate_a_unique_short_id_or_hash>", // e.g., "quiz_mc_01", "quiz_tf_02"
  "type": "<question_type>", // e.g., "multiple_choice", "true_false", "short_answer"
  "question_text": "<Required: The text of the assessment question>",
  "options": [ // Required for "multiple_choice" / "true_false"
    {{"id": "A", "text": "<Option A text>"}},
    {{"id": "B", "text": "<Option B text>"}},
    // ... more options or just True/False
  ],
  "correct_answer_id": "<Optional: ID of the correct option for 'multiple_choice'/'true_false'>",
  "correct_answer": "<Optional: The correct answer for 'short_answer'>",
  "explanation": "<Required: Explanation for why the answer is correct>",
  "confidence_check": false // Default to false, can be overridden if needed
}}
```

**Example Multiple Choice Output:**
```json
{{
  "id": "quiz_mc_02",
  "type": "multiple_choice",
  "question_text": "What is the primary benefit of using asynchronous programming in web development?",
  "options": [
    {{"id": "A", "text": "It makes the code run faster on the server."}},
    {{"id": "B", "text": "It allows the user interface to remain responsive during long-running operations."}},
    {{"id": "C", "text": "It reduces the amount of memory used by the application."}},
    {{"id": "D", "text": "It simplifies database queries."}}
  ],
  "correct_answer_id": "B",
  "explanation": "Asynchronous programming prevents long-running tasks (like network requests) from blocking the main thread, ensuring the user interface remains interactive.",
  "confidence_check": false
}}
```

**Example True/False Output:**
```json
{{
  "id": "quiz_tf_01",
  "type": "true_false",
  "question_text": "In Python, lists are immutable data structures.",
  "options": [
      {{"id": "True", "text": "True"}},
      {{"id": "False", "text": "False"}}
  ],
  "correct_answer_id": "False",
  "explanation": "Python lists are mutable, meaning their contents can be changed after creation. Tuples are an example of immutable sequences in Python.",
  "confidence_check": false
}}
```

Generate ONLY the JSON object for the new assessment question. Do not include any other text before or after the JSON. Ensure the generated question is distinct from these existing ones: {existing_question_descriptions_json}
"""
)

# Add other prompts for chat, exercises, assessment later as needed.

INTENT_CLASSIFICATION_PROMPT = PromptTemplate.from_template(
"""Analyze the user's latest message in the context of the conversation history to determine their intent.
The user is currently in a general chat mode within an educational lesson about "{lesson_title}" (Topic: {topic}, Level: {level}).

Conversation History (most recent last, limited context):
{history_json}

User's latest message: "{user_input}"

Current Lesson Exposition Summary (first 500 chars):
{exposition_summary}

Current Active Task (Exercise or Assessment): {active_task_context}

Possible intents:
- "chatting": User is asking a general question, making a comment, seeking clarification, or engaging in off-topic chat.
- "request_exercise": User explicitly wants to do a learning exercise or task related to the lesson.
- "request_assessment": User explicitly wants to start or take the lesson quiz/assessment.
- "submit_answer": User is providing an answer to the currently active exercise or assessment question.

Based *only* on the user's latest message and the immediate context, what is the most likely intent?
Respond with ONLY a JSON object containing the key "intent" and one of the possible intent values listed above (chatting, request_exercise, request_assessment, submit_answer). Include a brief "reasoning" key explaining your choice.
Example: {{"intent": "request_exercise", "reasoning": "User explicitly asked for an exercise."}}

JSON Response:
"""
)