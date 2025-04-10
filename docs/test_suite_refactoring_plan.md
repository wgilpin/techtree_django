# Test Suite Refactoring Plan: Transition to Synchronous Background Task System

---

## **Goals**

- Remove all async code and fixtures from tests.
- Rewrite async tests as synchronous tests.
- Maintain or improve test coverage of:
  - Background task creation in views
  - Task processing logic in `taskqueue/processors`
  - Task status API
  - AI node logic (rewritten as sync tests)
  - Error handling and edge cases
- Remove redundant or obsolete tests.

---

## **Plan**

### **1. Remove async from all tests**

- Remove all `@pytest.mark.asyncio` decorators.
- Change all `async def test_*` to `def test_*`.
- Replace `await` calls with direct calls or mocks.
- Replace `AsyncMock` with `Mock`.

---

### **2. Rewrite AI node tests**

- Files: `syllabus/test_ai_node_*.py`, `onboarding/test_ai.py`
- Rewrite as **sync tests** calling AI node functions synchronously.
- Adjust mocks accordingly.
- Focus on input/output correctness of nodes.

---

### **3. Rewrite service and processor tests**

- Files: 
  - `syllabus/test_syllabus_service.py`
  - `lessons/test_services_content.py`
  - `lessons/test_services_chat.py`
  - `lessons/test_services.py`
- Remove async code.
- Rewrite to test **sync background task processors** directly.
- Mock DB and external calls.
- Cover success, failure, and edge cases.

---

### **4. Rewrite view tests**

- Files:
  - `onboarding/test_generating_polling_views.py`
  - `lessons/test_view_change_difficulty.py`
- Use Django test client synchronously.
- Mock background task scheduling (`process_ai_task`).
- Verify task creation and response correctness.
- Test polling endpoints.

---

### **5. Clean up**

- Remove unused async fixtures/utilities.
- Remove pytest-asyncio dependency.
- Ensure no async code remains in tests.

---

### **6. Add new tests if needed**

- For new background task processors.
- For task status API.
- For error handling and retries.

---

## **Mermaid Diagram: New Test Architecture**

```mermaid
flowchart TD
    subgraph Views
        V1[Generate Syllabus View]
        V2[Generate Lesson Content View]
        V3[Lesson Interaction View]
    end

    subgraph Processors
        P1[process_syllabus_generation]
        P2[process_lesson_content]
        P3[process_lesson_interaction]
    end

    subgraph AI_Nodes
        N1[SyllabusAI (sync)]
        N2[LessonContentAI (sync)]
        N3[LessonInteractionGraph (sync)]
    end

    V1 -->|Mocks| P1
    V2 -->|Mocks| P2
    V3 -->|Mocks| P3

    P1 --> N1
    P2 --> N2
    P3 --> N3

    subgraph Tests
        T1[Test Views (sync)]
        T2[Test Processors (sync)]
        T3[Test AI Nodes (sync)]
    end

    T1 --> V1
    T1 --> V2
    T1 --> V3

    T2 --> P1
    T2 --> P2
    T2 --> P3

    T3 --> N1
    T3 --> N2
    T3 --> N3
```

---

## **Summary**

- Remove async from all tests.
- Rewrite AI node tests as sync, testing node logic directly.
- Rewrite service and processor tests as sync, testing new background task processors.
- Rewrite view tests to mock background task scheduling and test sync behavior.
- Remove redundant/obsolete async tests.
- Ensure comprehensive coverage of the new sync background task system.