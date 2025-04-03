"""Stores prompt templates for syllabus generation and updates."""

# Note: Using .format() for compatibility if these are used outside f-strings.

GENERATION_PROMPT_TEMPLATE = """
You are an expert curriculum designer creating a
comprehensive syllabus for the topic: {topic}.

The user's knowledge level is: {knowledge_level}

Use the following information from internet searches to create
an accurate and up-to-date syllabus:

{search_context}

Create a syllabus with the following structure:
1. Topic name (should accurately reflect '{topic}')
2. Level (must be one of: 'beginner', 'early learner', 'good knowledge', 'advanced', appropriate for '{knowledge_level}')
3. Duration (e.g., "4 weeks", "6 sessions")
4. 3-5 Learning objectives (clear, measurable outcomes starting with action verbs)
5. Modules (organized logically, e.g., by week or unit, minimum 2 modules)
6. Lessons within each module (clear titles, minimum 3 lessons per module)

Tailor the syllabus content and depth to the user's knowledge level:
- For 'beginner': Focus on foundational concepts and gentle introduction. Avoid jargon where possible or explain it clearly.
- For 'early learner': Include basic concepts but move more quickly to intermediate topics. Introduce core terminology.
- For 'good knowledge': Focus on intermediate to advanced topics, assuming basic knowledge. Use standard terminology.
- For 'advanced': Focus on advanced topics, cutting-edge developments, and specialized areas. Use precise terminology.

For theoretical topics (like astronomy, physics, ethics, etc.),
    focus learning objectives on understanding, analysis, and theoretical applications
    rather than suggesting direct practical manipulation of objects or phenomena
    that cannot be directly accessed or manipulated.

Format your response ONLY as a valid JSON object with the following structure:
{{
  "topic": "Topic Name",
  "level": "Level",
  "duration": "Duration",
  "learning_objectives": ["Objective 1", "Objective 2", ...],
  "modules": [
    {{
      "week": 1, // or "unit": 1
      "title": "Module Title",
      "lessons": [
        {{ "title": "Lesson 1 Title" }},
        {{ "title": "Lesson 2 Title" }},
        ...
      ]
    }},
    ...
  ]
}}

Ensure the syllabus is comprehensive, well-structured, and follows a
logical progression appropriate for the user's knowledge level.
The JSON output must be valid and complete. Do not include any text before or after the JSON object.
"""


UPDATE_PROMPT_TEMPLATE = """
You are an expert curriculum designer updating a syllabus for the topic: {topic}.

The user's knowledge level is: {knowledge_level}

Here is the current syllabus:
{syllabus_json}

The user has provided the following feedback:
{feedback}

Update the syllabus JSON object to address the user's feedback while ensuring it remains
appropriate for their knowledge level ({knowledge_level}). Maintain the exact same JSON structure as the input.
Ensure the 'level' field remains one of: 'beginner', 'early learner', 'good knowledge', 'advanced'.
Ensure 'modules' is a list of objects, each with 'title' and a non-empty list of 'lessons' (each lesson having a 'title').

Format your response ONLY as the updated, valid JSON object. Do not include any text before or after the JSON object.
"""
