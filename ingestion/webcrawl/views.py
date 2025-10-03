# ingestion/webcrawl/views.py
from flask import render_template

def render_links_page(links, page, page_size, total_links, total_sentences, status_counts):
    total_pages = max(1, (total_links + page_size - 1) // page_size)
    start = (page - 1) * page_size + 1 if total_links > 0 else 0
    end = min(total_links, page * page_size)
    return render_template(
        "links.html",
        links=links,
        page=page, page_size=page_size,
        total_links=total_links, total_pages=total_pages,
        start=start, end=end,
        total_sentences=total_sentences,
        status_counts=status_counts
    )


def render_link_sentences_page(link_id, link_url, sentences, page, page_size, total, status_filter=None):
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size + 1 if total > 0 else 0
    end = min(total, page * page_size)
    return render_template("sentences.html",
                           link_id=link_id, link_url=link_url,
                           sentences=sentences, page=page, page_size=page_size,
                           total=total, total_pages=total_pages,
                           start=start, end=end,
                           status_filter=status_filter)

