from dataclasses import dataclass, field
from typing import Any

@dataclass
class Page:
    """
    Represents a single web page being crawled.
    Each visitor can attach flags, metadata, sentences, or links.
    """

    url: str
    depth: int = 0
    is_root: bool = False

    # Core content fields
    text: str | None = None
    text_clean: str | None = None
    sentences: list[str] = field(default_factory=list)
    sentence_statuses: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    # Dynamic runtime flags set by visitors
    flags: dict[str, Any] = field(default_factory=dict)

    # Extra metadata (e.g., DB id, timestamps, processor stats)
    metadata: dict[str, Any] = field(default_factory=dict)

    def reset(self):
        """Reset transient fields before reuse (not usually needed)."""
        self.text = None
        self.text_clean = None
        self.sentences.clear()
        self.sentence_statuses.clear()
        self.links.clear()
        self.flags.clear()
        self.metadata.clear()

    def __repr__(self):
        flags = ",".join(k for k,v in self.flags.items() if v)
        return f"<Page url={self.url} depth={self.depth} flags=[{flags}] sentences={len(self.sentences)}>"


    def should_skip(self) -> bool:
        return any(self.flags.get(k) for k in ("skip_processing", "excluded", "duplicate", "failed"))
