import time
from abc import ABC, abstractmethod
from datetime import datetime

import structlog

from src.common.models import RawArticle

logger = structlog.get_logger(__name__)


class BaseCollector(ABC):
    def __init__(self, source_config: dict):
        self.config = source_config
        self.name = source_config["name"]
        self.category = source_config.get("category", "tech")
        self.priority = source_config.get("priority", "medium")

    @abstractmethod
    async def collect(self) -> list[RawArticle]:
        """Collect articles from source. Must handle its own errors."""
        ...

    async def health_check(self) -> bool:
        """Check if source is reachable. Default: always healthy."""
        return True

    def _apply_keyword_filter(
        self, articles: list[RawArticle], keywords: list[str]
    ) -> list[RawArticle]:
        if not keywords:
            return articles
        kw_lower = [k.lower() for k in keywords]
        return [
            a for a in articles
            if any(kw in a.title.lower() or kw in a.content.lower() for kw in kw_lower)
        ]

    @staticmethod
    def _parse_date(time_struct) -> datetime | None:
        if time_struct is None:
            return None
        try:
            return datetime.fromtimestamp(time.mktime(time_struct))
        except (TypeError, ValueError, OverflowError):
            return None
