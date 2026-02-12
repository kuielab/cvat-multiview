#!/bin/bash
#
# Insert Pre-label Bbox Annotations
#
# Wrapper script for insert_bbox_annotations.py
# Reads all_labels.json and inserts bbox annotations into CVAT tasks.
#
# Usage:
#   ./insert_prelabels.sh --user admin --password admin123 \
#       --data-dir /mnt/data --datasets multisensor_home1
#
#   # Dry-run mode
#   ./insert_prelabels.sh --user admin --password admin123 \
#       --data-dir /mnt/data --dry-run --limit 5

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/insert_bbox_annotations.py"

# Check if Python script exists
if [ ! -f "${PYTHON_SCRIPT}" ]; then
    echo "Error: Python script not found: ${PYTHON_SCRIPT}"
    exit 1
fi

# Find Python executable
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "${PYTHON}" ]; then
    echo "Error: Python not found. Please install Python 3."
    exit 1
fi

echo "Using Python: ${PYTHON}"
echo "Script: ${PYTHON_SCRIPT}"
echo ""

# Pass all arguments to Python script
exec "${PYTHON}" "${PYTHON_SCRIPT}" "$@"
