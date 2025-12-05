#!/usr/bin/env bash
set -euo pipefail

# Example runner. Adjust OPENAI_* to enable K2.

SOURCE_URL=${1:-"http://10.42.39.161/results/"}
ARCHIVE_ROOT=${2:-"./archive"}
DAYS=${3:-7}

python -m ia.cli crawl --source-url "$SOURCE_URL" --archive-root "$ARCHIVE_ROOT" --days "$DAYS"

