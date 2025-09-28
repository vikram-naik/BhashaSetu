#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(pwd)"
SCRIPT_PATH="${1:-}"
QUERY="${2:-"映画 lang:ja"}"
LIMIT="${3:-10}"

if [[ -z "$SCRIPT_PATH" ]]; then
  echo "❌ No ingestion script provided."
  echo "Usage: $0 ingestion/<source>/<script>.py \"<query>\" [limit]"
  exit 1
fi

echo "🐳 Running ingestion inside Python 3.11 container..."
echo "    Script: $SCRIPT_PATH"
echo "    Query:  $QUERY"
echo "    Limit:  $LIMIT"
echo "    Project mounted: $PROJECT_DIR -> /workspace"
echo "    Virtualenv: /workspace/venv311"

docker run -it --rm \
  -v "$PROJECT_DIR":/workspace \
  -w /workspace \
  --network host \
  python:3.11-slim bash -c "
    # Install SSL root certificates + build tools for psycopg2
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates gcc libpq-dev && \
      rm -rf /var/lib/apt/lists/*

    if [ ! -d venv311 ]; then
      echo '📦 Creating virtualenv venv311...'
      python -m venv venv311
    fi

    . venv311/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt

    python $SCRIPT_PATH \"$QUERY\" $LIMIT
  "
