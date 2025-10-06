import logging
import time
from urllib.parse import urlparse
from .page import Page

# ---------------------------------------------------------
# CrawlContext — shared runtime state + current page
# ---------------------------------------------------------
class CrawlContext:
    def __init__(self, config):
        self.config = config
        self.page = None
        self.visited = set()
        self.start_time = time.time()
        self.stats = {
            "pages": 0,
            "links": 0,
            "errors": 0,
            "sentences": 0
        }

    def log(self, msg):
        prefix = f"[Depth={getattr(self.page, 'depth', 0)} URL={getattr(self.page, 'url', 'N/A')}]"
        logging.info(f"{prefix} {msg}")


# ---------------------------------------------------------
# Crawler — emits lifecycle events only
# ---------------------------------------------------------
class Crawler:
    """Traverses URLs and emits lifecycle events."""

    def __init__(self, config, visitors):
        self.config = config
        self.visitors = visitors

    def run(self, start_url):
        context = CrawlContext(self.config)
        context.config["base_url"] = start_url
        self._notify("on_crawl_start", context)
        # Mark the root explicitly
        self._crawl(context, start_url, 0, is_root=True)
        self._notify("on_crawl_end", context)

    def _notify(self, event, context, *args):
        """Broadcast an event to all visitors."""
        for v in self.visitors:
            method = getattr(v, event, None)
            if callable(method):
                try:
                    method(context, *args)
                except Exception as e:
                    logging.exception(f"[Visitor Error] {v.__class__.__name__}.{event}: {e}")

    def _crawl(self, context, url, depth, is_root=False):
        """Recursive traversal — visitors handle all logic."""
        max_depth = context.config.get("depth", 1)
        max_pages = context.config.get("max_pages", 50)
        min_sentences = context.config.get("min_sentences", 1)

        # Initialize stop flag if not present
        if not hasattr(context, "stop_triggered"):
            context.stop_triggered = False

        # Global stop condition (checked in every recursion)
        if not context.stop_triggered:
            if (context.stats["pages"] >= max_pages and
                context.stats["sentences"] >= min_sentences):
                context.stop_triggered = True
                logging.info("[Crawler] Stop condition met — max pages and sentences reached.")
                return
        else:
            # Stop has already been triggered — silently return
            return

        # Depth limit guard
        if depth > max_depth:
            return

        # Create and assign current page
        context.page = Page(url=url, depth=depth, is_root=is_root)
        context.stats["pages"] += 1

        # Notify visitors
        self._notify("on_page_start", context)
        self._notify("on_page_process", context)
        self._notify("on_page_end", context)

        # Traverse child links
        links = getattr(context.page, "links", [])
        for link in links:
            if context.stop_triggered:
                return  # Stop mid-loop if limit reached

            context.stats["links"] += 1
            self._notify("on_link_discovered", context, link)

            # Stay within domain
            if urlparse(link).netloc == urlparse(url).netloc:
                self._crawl(context, link, depth + 1, is_root=False)

