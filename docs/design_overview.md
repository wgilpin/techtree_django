# Application Design Summary

This document provides a high-level overview of the different components of the TechTree Django application, summarizing the responsibilities of each major folder containing Python code.

A more detailed `design.md` is found in each subfolder with python code.

---

## core

**Name:** Core Application Logic and Data Models

**Description:**
This folder contains the foundational logic, data models, and shared utilities for the application. It defines the primary database schema, core business logic, exception handling, constants, and the main views and URL routing for the core app. The code here is responsible for representing users, syllabi, modules, lessons, lesson content, user progress, and conversation history, as well as providing the main entry points for the core app's web interface.

---

## lessons

**Name:** Lessons App Logic and User Interaction

**Description:**
This folder implements the business logic, user interaction handling, and service layers for lesson delivery in the application. It provides the mechanisms for lesson content generation, user progress tracking, chat and exercise handling, and state management. The code here orchestrates how users interact with lessons, how lesson content is generated and fetched, and how lesson state is initialized and updated.

---

## lessons/ai

**Name:** Lesson Interaction AI Graph and Node Logic

**Description:**
This folder implements the AI-driven logic for lesson interactions, including the orchestration of chat, exercise, and assessment flows using a LangGraph workflow. It defines the state structure, prompt templates, and node functions for intent classification, chat response, exercise/assessment generation, and answer evaluation. The code here enables dynamic, context-aware lesson experiences powered by LLMs.

---

## onboarding

**Name:** Onboarding Assessment and Syllabus Initialization

**Description:**
This folder implements the onboarding assessment logic, user-facing views, and supporting services for evaluating a user's initial knowledge and generating a personalized syllabus. It provides the AI-driven assessment flow, question/answer handling, and the orchestration of syllabus creation based on assessment results. The code here enables new users to be assessed and onboarded into the learning platform with an appropriate starting point.

---

## syllabus

**Name:** Syllabus Management and Display

**Description:**
This folder handles the logic related to syllabus management, including retrieval, formatting, and display. It provides services to interact with syllabus data and views to render syllabus details, module details, and lesson details based on the status of background generation tasks.

---

## syllabus/ai

**Name:** Syllabus Generation AI Graph and Node Logic

**Description:**
This folder implements the AI-driven logic for syllabus generation, including the orchestration of database search, internet search, and LLM-based generation/update using a LangGraph workflow. It defines the state structure, prompt templates, configuration, and node functions for creating and refining syllabi.

---

## taskqueue

**Name:** Background Task Queue Management

**Description:**
This folder manages the background task queue system for handling asynchronous AI operations. It defines the task model, task execution logic, and views for monitoring task status and the overall queue health. The code here enables long-running AI processes (like syllabus generation, content creation, and interactions) to run without blocking user requests.

---

## taskqueue/processors

**Name:** Background Task Processors

**Description:**
This folder contains the synchronous processing logic for different types of background AI tasks defined in the `taskqueue` app. Each processor handles a specific task type (e.g., lesson interaction, content generation, syllabus generation, onboarding assessment) by interacting with the relevant AI services and updating the database state.

---

## techtree_django

**Name:** Django Project Configuration

**Description:**
This folder contains the main configuration files for the Django project, including settings, root URL configuration, and WSGI/ASGI entry points. It defines how the different apps are connected, how the project runs, and global settings like database configuration, installed apps, middleware, static files, and logging.

---
