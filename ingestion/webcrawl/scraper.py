import argparse
import json
import logging
from .crawler import Crawler
from .visitors import Visitor

def build_visitors(config):
    """Instantiate visitors in JSON order."""
    visitor_names = config.get("visitors", [])
    available = {cls.__name__: cls for cls in Visitor.__subclasses__()}
    visitors = []
    for name in visitor_names:
        if name not in available:
            logging.warning(f"[Scraper] Unknown visitor: {name}")
            continue
        v = available[name]()
        if hasattr(v, "initialize"):
            v.initialize(config)
        visitors.append(v)
        logging.info(f"[Scraper] Added visitor: {name}")
    return visitors

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="News Scraper")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    parser.add_argument("--dry-run", action="store_true", help="Exploratory dry-run: only print/save URLs, no DB")
    args = parser.parse_args()

    dry_run = args.dry_run

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    visitors = build_visitors(config)
    crawler = Crawler(config, visitors)
    crawler.run(config["base_url"])

if __name__ == "__main__":
    main()
