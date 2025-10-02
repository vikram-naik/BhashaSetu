#!/bin/bash
# run_crawler.sh - Kick off the Gujarati news crawler using JSON config

# Example usage:
# ./run_crawler.sh config.json

CONFIG_FILE=${1:-"config.json"}

# Path to indic_nlp_resources (adjust if cloned elsewhere)
INDIC_RESOURCES_PATH="$HOME/indic_nlp_resources"

# Export so scraper.py can find it
export INDIC_RESOURCES_PATH

echo "Using INDIC_RESOURCES_PATH=$INDIC_RESOURCES_PATH"
echo "Starting crawler with config: $CONFIG_FILE"

python3 ingestion/webcrawl/scraper.py --config "$CONFIG_FILE"
