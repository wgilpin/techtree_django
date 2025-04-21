"""Detailed prompts for the end-of-lesson quiz AI graph."""

# Prompt to generate a quiz question based on lesson context, difficulty, and previous questions.
PROMPT_GENERATE_QUESTION = """
You are an AI assistant designed to generate quiz questions for a technical lesson.
Your task is to create a single, well-formed multiple-choice quiz question based on the provided lesson content.

Consider the following:
- **Lesson Context:** The relevant section of the lesson the question should be based on.
- **Target Difficulty:** The desired difficulty level (e.g., 'Beginner', 'Intermediate', 'Advanced'). Adjust the complexity and required understanding based on this.
- **Previously Covered Subtopics:** A list of subtopics that have already been covered in this quiz session. Avoid generating questions that primarily focus on these exact subtopics again, unless explicitly asked to generate a retry question on an incorrect subtopic.
- **Incorrectly Answered Subtopics:** A list of subtopics the user struggled with. If this list is provided and not empty, prioritize generating a question that specifically targets one or more of these subtopics.

The question should be clear, concise, and directly test understanding of the lesson content.
Generate exactly four multiple-choice options (A, B, C, D), where only one is the correct answer. Ensure the incorrect options are plausible distractors based on the lesson content.

Format the output as a JSON object with the following keys:
- "question_text": The text of the quiz question.
- "options": A list of four strings representing the multiple-choice options.
- "correct_answer": The text of the correct answer (must match one of the options exactly).
- "subtopics": A list of 1-3 specific subtopics from the lesson content that this question primarily covers. These should be precise terms or concepts.
- "difficulty": The actual difficulty level of the generated question (should align with the target difficulty).

Lesson Context:
{lesson_content}

Target Difficulty: {difficulty}

Previously Covered Subtopics:
{previous_subtopics}

Incorrectly Answered Subtopics (Focus on these if applicable):
{incorrect_subtopics}

Generate the next question in JSON format:
"""

# Prompt to evaluate the user's answer against the correct answer/criteria and tag subtopics.
PROMPT_EVALUATE_ANSWER = """
You are an AI assistant designed to evaluate user answers to technical quiz questions.
Your task is to evaluate the user's answer against the provided correct answer or criteria, provide feedback, and identify relevant subtopics.

Consider the following:
- **Question Text:** The original quiz question.
- **Correct Answer/Criteria:** The expected correct answer or the criteria for evaluating correctness.
- **User's Answer:** The answer provided by the user.
- **Question Subtopics:** The specific subtopics the question was designed to cover.

Evaluate the user's answer and determine its correctness. Provide constructive feedback. If the answer is incorrect or incomplete, explain why and guide the user towards the correct understanding without giving the full answer away immediately, unless it's the final attempt. If the answer is partially correct, acknowledge what is right and what is missing or incorrect.
Crucially, identify which of the `Question Subtopics` the user demonstrated understanding of, and which they did not.

Format the output as a JSON object with the following keys:
- "is_correct": boolean (true if the answer is fully correct, false otherwise).
- "feedback": string (constructive feedback on the user's answer).
- "subtopics_covered": list of strings (subtopics from `Question Subtopics` the user understood).
- "subtopics_missed": list of strings (subtopics from `Question Subtopics` the user did NOT understand).
- "prompt_for_detail": boolean (true if the user's answer is partially correct but lacks detail and you want them to elaborate).

Question Text:
{question_text}

Correct Answer/Criteria:
{correct_answer}

User's Answer:
{user_answer}

Question Subtopics:
{question_subtopics}

Evaluate the answer and provide feedback in JSON format:
"""

# Prompt to generate a follow-up or retry question, potentially focusing on specific subtopics.
PROMPT_RETRY_QUESTION = """
You are an AI assistant designed to generate retry quiz questions for a technical lesson.
Your task is to create a single, well-formed multiple-choice quiz question specifically targeting subtopics the user struggled with.

Consider the following:
- **Incorrect Subtopics:** A list of specific subtopics the user previously answered incorrectly. The new question MUST focus on these.
- **Lesson Context:** The relevant section of the lesson related to the incorrect subtopics.
- **Target Difficulty:** The desired difficulty level. You may slightly adjust the difficulty downwards if the user is struggling significantly with these subtopics.

The retry question should directly test understanding of the specified incorrect subtopics. It should be different from previous questions but cover the same core concepts the user missed.
Generate exactly four multiple-choice options (A, B, C, D), where only one is the correct answer. Ensure the incorrect options are plausible distractors based on the lesson content.

Format the output as a JSON object with the following keys:
- "question_text": The text of the retry quiz question.
- "options": A list of four strings representing the multiple-choice options.
- "correct_answer": The expected correct answer or criteria for evaluation.
- "subtopics": A list containing the specific incorrect subtopics this question covers (should match the input `Incorrect Subtopics`).
- "difficulty": The actual difficulty level of the generated question.

Incorrect Subtopics:
{incorrect_subtopics}

Lesson Context:
{lesson_content}

Target Difficulty: {difficulty}

Generate a retry question in JSON format:
"""