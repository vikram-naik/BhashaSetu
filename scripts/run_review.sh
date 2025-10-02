#!/bin/bash
# run_review.sh - Start the sentence review app using JSON config

# Example usage:
# ./run_review.sh config.json

CONFIG_FILE=${1:-"config.json"}

# Path to indic_nlp_resources (adjust if cloned elsewhere)
INDIC_RESOURCES_PATH="$HOME/indic_nlp_resources"

# Export so review_app.py (if ever extended to use indic tools) can find it
export INDIC_RESOURCES_PATH

echo "Using INDIC_RESOURCES_PATH=$INDIC_RESOURCES_PATH"
echo "Starting review app with config: $CONFIG_FILE"

python3 ingestion/webcrawl/text_review_app.py --config "$CONFIG_FILE"
