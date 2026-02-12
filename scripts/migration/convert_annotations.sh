#!/bin/bash
#
# Master -> Refactor annotation coordinate converter (shell wrapper)
#
# Converts annotation coordinates from master's fake 1920x1080 task space
# to the actual video dimensions used by refactor.
#
# Usage:
#   # Auto-detect dimensions and upload:
#   ./scripts/migration/convert_annotations.sh annotations.xml --job-id 7 --user admin --password admin123 --upload
#
#   # Manual dimensions:
#   ./scripts/migration/convert_annotations.sh annotations.xml --target-w 320 --target-h 240
#
#   # Custom output path:
#   ./scripts/migration/convert_annotations.sh annotations.xml -o output.xml --job-id 7 --user admin --password admin123
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/convert_annotation_coords.py"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

usage() {
    cat <<'EOF'
Usage: convert_annotations.sh <input.xml> [options]

Options:
  -o, --output FILE     Output file (default: <input>_converted.xml)
  --target-w WIDTH      Target width
  --target-h HEIGHT     Target height
  --job-id ID           CVAT job ID (auto-detect dimensions)
  --server URL          CVAT server URL (default: http://localhost:8080)
  --user USERNAME       CVAT username
  --password PASSWORD   CVAT password
  --cookies FILE        Path to cookies.txt
  --upload              Upload to CVAT after conversion
  -h, --help            Show this help

Examples:
  # Auto-detect + upload (recommended):
  ./scripts/migration/convert_annotations.sh annotations.xml --job-id 7 --user admin --password admin123 --upload

  # Manual dimensions:
  ./scripts/migration/convert_annotations.sh annotations.xml --target-w 320 --target-h 240

  # Custom output:
  ./scripts/migration/convert_annotations.sh annotations.xml -o converted.xml --job-id 7 --user admin --password admin123
EOF
}

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo -e "${RED}ERROR: python3 not found${NC}" >&2
    exit 1
fi

# Check script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo -e "${RED}ERROR: $PYTHON_SCRIPT not found${NC}" >&2
    exit 1
fi

# Parse arguments
INPUT=""
OUTPUT=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -o|--output)
            OUTPUT="$2"
            shift 2
            ;;
        *)
            if [ -z "$INPUT" ] && [ -f "$1" ]; then
                INPUT="$1"
            else
                EXTRA_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [ -z "$INPUT" ]; then
    echo -e "${RED}ERROR: Input file is required${NC}" >&2
    echo ""
    usage
    exit 1
fi

if [ ! -f "$INPUT" ]; then
    echo -e "${RED}ERROR: Input file not found: $INPUT${NC}" >&2
    exit 1
fi

# Generate default output path
if [ -z "$OUTPUT" ]; then
    BASENAME="${INPUT%.*}"
    EXT="${INPUT##*.}"
    OUTPUT="${BASENAME}_converted.${EXT}"
fi

echo -e "${GREEN}Converting annotations...${NC}"
echo "  Input:  $INPUT"
echo "  Output: $OUTPUT"
echo ""

$PYTHON "$PYTHON_SCRIPT" "$INPUT" "$OUTPUT" "${EXTRA_ARGS[@]}"

STATUS=$?
if [ $STATUS -eq 0 ]; then
    echo ""
    echo -e "${GREEN}Done!${NC}"
else
    echo ""
    echo -e "${RED}Conversion failed (exit code $STATUS)${NC}" >&2
    exit $STATUS
fi
