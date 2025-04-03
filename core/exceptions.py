"""
Custom exception utilities for the application.
"""

import logging
from typing import Any, NoReturn, Type

# Get a logger for this module, although typically the calling module's logger is used.
logger = logging.getLogger(__name__)

# Helper functions for logging and raising exceptions

def log_and_propagate(
    new_exception_type: Type[Exception],
    new_exception_message: str,
    original_exception: Exception,  # Make original exception mandatory for chaining
    exc_info: bool = True,
    **log_extras: Any,
) -> NoReturn:
    """
    Logs an error message and then raises a specified exception, ensuring the
    original exception is chained (using 'from original_exception').

    Args:
        new_exception_type: The type of exception to raise.
        new_exception_message: The message for the new exception.
        original_exception: The exception that triggered this call, to be chained.
        exc_info: Whether to include exception info (stack trace) in the log.
        **log_extras: Additional key-value pairs to include in the log record.

    Raises:
        new_exception_type: Always raises an exception of this type.
    """
    log_message = f"{new_exception_message}: {original_exception}"
    # Use the logger obtained for this module or rely on root logger config
    logger.error(log_message, exc_info=exc_info, extra=log_extras if log_extras else None)
    raise new_exception_type(new_exception_message) from original_exception


def log_and_raise_new(
    exception_type: Type[Exception],
    exception_message: str,
    break_chain: bool = False,  # Control 'from None'
    exc_info: bool = True,
    **log_extras: Any,
) -> NoReturn:
    """
    Logs an error message and then raises a specified exception, optionally
    breaking the exception chain (using 'from None' if break_chain is True).

    Args:
        exception_type: The type of exception to raise.
        exception_message: The message for the new exception.
        break_chain: If True, raise the new exception using 'from None'.
                     If False (default), the original context is preserved implicitly.
        exc_info: Whether to include exception info (stack trace) in the log.
        **log_extras: Additional key-value pairs to include in the log record.

    Raises:
        exception_type: Always raises an exception of this type.
    """
    log_message = exception_message
    # Use the logger obtained for this module or rely on root logger config
    logger.error(log_message, exc_info=exc_info, extra=log_extras if log_extras else None)

    if break_chain:
        raise exception_type(exception_message) from None

    raise exception_type(exception_message)



# --- Custom Application Exceptions ---

class ApplicationError(Exception):
    """Base class for application-specific errors."""
    pass


class NotFoundError(ApplicationError):
    """Raised when a requested resource is not found."""
    pass


class ExternalServiceError(ApplicationError):
    """Raised when an external service (e.g., AI API) fails."""
    pass


class ConfigurationError(ApplicationError):
    """Raised for configuration-related issues."""
    pass


class DataValidationError(ApplicationError):
    """Raised when data validation fails (e.g., from AI response)."""
    pass


# Example Custom Exception (can add others here later if needed)
# class InternalDataValidationError(Exception):
#     """
#     Raised when data from an internal source (DB, AI, etc.) fails validation.
#     """
#     def __init__(self, message: str, original_exception: Exception | None = None):
#         super().__init__(message)
#         self.original_exception = original_exception
#         self.message = message

#     def __str__(self) -> str:
#         if self.original_exception:
#             return f"{self.message}: {self.original_exception}"
#         return self.message