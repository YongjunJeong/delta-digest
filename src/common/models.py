from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawArticle:
    source_name: str            # e.g. "Databricks Blog"
    source_type: str            # rss | arxiv | hn | github
    title: str
    url: str                    # unique key for MERGE
    content: str                # raw HTML or plaintext (Silver cleans this)
    author: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = field(default_factory=datetime.utcnow)
    category: str = ""          # databricks | ai | ai_tools | research | tech | open_source
    priority: str = "medium"    # high | medium | low
    raw_metadata: dict = field(default_factory=dict)
