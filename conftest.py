"""
Pytest configuration file.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest
from django.conf import settings


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """
    Disable file logging during test runs by directly removing the specific
    TimedRotatingFileHandler instance from the root logger.
    """
    try:
        # Construct the expected log file path from settings
        log_file_path = None
        if hasattr(settings, "BASE_DIR"):
            log_file_path = settings.BASE_DIR / "techtree_django.log"
        else:
            # Fallback if BASE_DIR isn't defined early enough (less likely with Django)
            log_file_path = Path(__file__).resolve().parent / "techtree_django.log"
            print(
                f"pytest_configure: Warning - settings.BASE_DIR not found, guessing log path: {log_file_path}"
            )

        root_logger = logging.getLogger(__name__)
        handler_to_remove = None

        # Iterate through a copy of handlers as we might modify the list
        for handler in root_logger.handlers[:]:
            if isinstance(handler, TimedRotatingFileHandler):
                # Check if the handler's baseFilename matches our target log file
                # Use os.path.abspath to normalize paths for comparison
                try:
                    handler_path = os.path.abspath(handler.baseFilename)
                    target_path = os.path.abspath(log_file_path)
                    if handler_path == target_path:
                        handler_to_remove = handler
                        break  # Found the handler
                except Exception as path_e:
                    print(
                        f"pytest_configure: Error comparing handler path '"
                        f"{getattr(handler, 'baseFilename', 'N/A')}' with target '{log_file_path}': {path_e}"
                    )

        if handler_to_remove:
            print(
                f"pytest_configure: Found file handler for {log_file_path}. Removing it."
            )
            root_logger.removeHandler(handler_to_remove)
            # Optional: Close the handler to release file lock if necessary
            try:
                handler_to_remove.close()
            except Exception as close_e:
                print(f"pytest_configure: Error closing removed handler: {close_e}")
        else:
            print(
                f"pytest_configure: Did not find specific file handler for {log_file_path} on root logger."
            )

    except Exception as e:
        # Use pytest's warning system for better visibility during test setup
        config.warn(
            "CONF_LOGGING_ERROR", f"Error configuring logging in pytest_configure: {e}"
        )
