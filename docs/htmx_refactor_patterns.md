# HTMX + Websockets Refactor Patterns for Django

This document summarizes the patterns and best practices established during the refactor of `lesson_detail.html` to use HTMX and the HTMX websockets extension with Django Channels. Use these patterns to migrate other dynamic features in the project to a modern, real-time, and declarative approach.

---

## 1. HTMX Attribute Patterns

### a. HTMX HTTP Requests
- Use `hx-get`, `hx-post`, or `hx-trigger` on buttons/links/forms to declaratively trigger server actions.
- Use `hx-indicator` to show loading spinners.
- Use `hx-confirm` for confirmation dialogs.
- Example:
  ```html
  <button
    hx-post="{% url 'some:view' %}"
    hx-indicator="#spinner"
    hx-confirm="Are you sure?">
    Do Action
  </button>
  ```

### b. HTMX Websockets
- Use `hx-ws="connect:/ws/lesson/{{ lesson.pk }}/chat/"` on a container to open a websocket connection.
- Use `hx-ws="send"` on a form to send its data over the websocket.
- The backend (Django Channels consumer) should join a group and send HTML partials to the client for DOM updates.

---

## 2. Template Structure

- Place websocket connection attributes on the main content/chat container.
- Use HTMX swaps (`hx-swap`) to control how/where content is updated.
- Render all dynamic content (messages, tasks, content status) as server-side HTML partials.

---

## 3. JavaScript Integration

- Remove legacy AJAX and polling JS.
- Use a single event listener for `htmx:afterSwap` to trigger any post-processing (e.g., MathJax rendering):
  ```js
  document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail && evt.detail.target && (
      evt.detail.target.id === 'lesson-content-area' ||
      evt.detail.target.id === 'chat-history'
    )) {
      renderMath(evt.detail.target);
    }
  });
  ```

---

## 4. Django Backend Patterns

- Use Django Channels consumers for each websocket endpoint.
- Consumers should:
  - Join a group based on the resource (e.g., lesson_id).
  - Relay backend updates to the group using `self.channel_layer.group_send`.
  - Send HTML partials to the client for direct DOM swapping.
- Views should:
  - Detect HTMX requests (`request.htmx`).
  - Return `HX-Redirect` headers for navigation.
  - Return partials for in-place updates.

---

## 5. Example: Adding HTMX/Websockets to a New Feature

1. **Frontend**: Add `hx-ws="connect:/ws/..."` to the relevant container and `hx-ws="send"` to the form.
2. **Backend**: Create a Channels consumer that joins a group and relays updates.
3. **Views/Tasks**: On state changes, send HTML partials to the group.
4. **Templates**: Render all dynamic content as partials for HTMX swaps.
5. **JS**: Use `htmx:afterSwap` for any post-processing (e.g., math rendering).

---

## 6. Testing

- Test websocket connections and group logic using Channels' test utilities.
- Test HTMX swaps and partial rendering using Django's test client and template rendering.

---

## 7. Further Reading

- [HTMX Documentation](https://htmx.org/docs/)
- [HTMX Websockets Extension](https://v1.htmx.org/extensions/web-sockets/)
- [Django Channels](https://channels.readthedocs.io/en/latest/)
- [django-htmx](https://django-htmx.readthedocs.io/en/latest/)

---

**Apply these patterns to all dynamic features for a modern, maintainable, and real-time Django application.**