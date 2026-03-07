import feedparser
import httpx
import structlog

from src.common.models import RawArticle
from src.ingestion.base import BaseCollector

logger = structlog.get_logger(__name__)


class RSSCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        url = self.config["url"]
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("rss_fetch_failed", source=self.name, error=str(e))
            return []

        feed = feedparser.parse(response.text)
        articles = []

        max_items = self.config.get("max_items")
        entries = feed.entries[:max_items] if max_items else feed.entries

        for entry in entries:
            article = RawArticle(
                source_name=self.name,
                source_type="rss",
                title=entry.get("title", "").strip(),
                url=entry.get("link", ""),
                content=entry.get("summary", "") or entry.get("description", ""),
                author=entry.get("author"),
                published_at=self._parse_date(entry.get("published_parsed")),
                category=self.category,
                priority=self.priority,
                raw_metadata={
                    "tags": [t.get("term", "") for t in entry.get("tags", [])],
                    "feed_title": feed.feed.get("title", ""),
                },
            )
            if article.url and article.title:
                articles.append(article)

        keywords = self.config.get("filter_keywords", [])
        filtered = self._apply_keyword_filter(articles, keywords)
        logger.info("rss_collected", source=self.name, total=len(articles), filtered=len(filtered))
        return filtered

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.head(self.config["url"])
                return resp.status_code < 500
        except httpx.HTTPError:
            return False
