#!/bin/bash

# Find and kill all processes whose name starts with "python"
echo "Searching for python processes..."

# Get list of python processes
pythonpids=$(tasklist.exe //FI "IMAGENAME eq python*" //FO CSV | grep -i "python" | cut -d',' -f2 | tr -d '"')

# Check if any processes were found
if [ -z "$pythonpids" ]; then
  echo "No python processes found."
else
  # Kill each process individually with proper formatting
  for pid in $pythonpids; do
    echo "Killing process with PID: $pid"
    taskkill.exe //F //PID "$pid"
  done
fi

# Find and kill all processes whose name is "node.exe"
echo "Searching for node processes..."

# Get list of node processes
nodepids=$(tasklist.exe //FI "IMAGENAME eq node.exe" //FO CSV | grep -i "node" | cut -d',' -f2 | tr -d '"')

# Check if any processes were found
if [ -z "$nodepids" ]; then
  echo "No node processes found."
else
  # Kill each process individually with proper formatting
  for pid in $nodepids; do
    echo "Killing process with PID: $pid"
    taskkill.exe //F //PID "$pid"
  done
fi

echo "Operation completed."
