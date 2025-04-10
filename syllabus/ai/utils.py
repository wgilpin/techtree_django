"""Utility functions for the syllabus generation module."""

import inspect
import time
import asyncio # Import asyncio
import random
from typing import Callable, Any, Coroutine, Awaitable # Added imports, Coroutine, Awaitable
from google.api_core.exceptions import ResourceExhausted

# Added type annotations
async def call_with_retry( # Make the function async
    # Use a more general Awaitable type hint for the async function
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    **kwargs: Any
) -> Any:
    """Calls an async function with exponential backoff retry logic for ResourceExhausted errors."""
    retries = 0
    delay = initial_delay # Use the typed initial_delay
    while True:
        try:
            # Call the function, await if needed
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            else:
                return result
        except ResourceExhausted as e: # Only retry on ResourceExhausted
            retries += 1
            if retries > max_retries:
                func_name = getattr(func, '__name__', 'mock_object')
                print(f"Max retries ({max_retries}) exceeded for {func_name}.")
                raise e # Re-raise the ResourceExhausted error
            # Calculate delay with exponential backoff and jitter
            current_delay = delay * (2 ** (retries - 1)) + random.uniform(0, 1)
            func_name = getattr(func, '__name__', 'mock_object')
            print(
                f"ResourceExhausted error. Retrying {func_name} in "
                f"{current_delay:.2f} seconds... (Attempt {retries}/{max_retries})"
            )
            # Use asyncio.sleep for non-blocking delay
            await asyncio.sleep(current_delay)
        except Exception as e: # Catch and re-raise any other exception immediately
            func_name = getattr(func, '__name__', 'mock_object')
            print(f"Non-retryable error during {func_name} call: {e}")
            raise e
