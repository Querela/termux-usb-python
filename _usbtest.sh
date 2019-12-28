#!/bin/bash

# Base script, should be sym linked for each python script.
# Wrapper for Python script to source virtual environment and run script with
# supplied USB file descriptor argument.

# compute py script name
P=$0
F=$(basename -- "$P")
S=${F%.*}

echo "Run $S ..."

# actual script
cd /data/data/com.termux/files/home/tools/usb
source venv/bin/activate

python3 "$S" "$@"

deactivate
