#!/bin/bash

# Kill existing servers
echo "Running kill_servers.sh..."
./kill_servers.sh
echo "kill_servers.sh finished."

echo "Starting Django server in a new terminal window..."
# Note: This command attempts to open a new terminal window.
# Depending on your system configuration, it might open an external
# Git Bash or Command Prompt window, not necessarily a VS Code integrated terminal.
start "Django Server" bash -c "echo '--- Starting Django Server ---'; python manage.py runserver; echo; echo '--- Django Server exited. Press Enter to close window. ---'; read"

echo "Starting background task processor in a new terminal window..."
# Note: This command attempts to open a new terminal window.
# Depending on your system configuration, it might open an external
# Git Bash or Command Prompt window, not necessarily a VS Code integrated terminal.
start "Task Processor" bash -c "echo '--- Starting Task Processor ---'; python manage.py process_tasks; echo; echo '--- Task Processor exited. Press Enter to close window. ---'; read"

echo "run.sh script finished initiating processes."