#!/bin/bash
# run_crawler.sh - Kick off the Gujarati news crawler using JSON config

# Example usage:
#   ./run_crawler.sh config.json
#   ./run_crawler.sh config.json --dry-run

CONFIG_FILE=$1
shift  # shift args so $@ passes any remaining (like --dry-run)

# Path to indic_nlp_resources (adjust if cloned elsewhere)
INDIC_RESOURCES_PATH="$HOME/indic_nlp_resources"

# Export so scraper.py can find it
export INDIC_RESOURCES_PATH

echo "Using INDIC_RESOURCES_PATH=$INDIC_RESOURCES_PATH"
echo "Starting crawler with config: $CONFIG_FILE"

# Forward all remaining args ($@) to Python
python3 -m ingestion.webcrawl.scraper --config "$CONFIG_FILE" "$@"
