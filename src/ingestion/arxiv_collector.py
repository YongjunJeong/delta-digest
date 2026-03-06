import feedparser
import httpx
import structlog

from src.common.models import RawArticle
from src.ingestion.base import BaseCollector

logger = structlog.get_logger(__name__)

BASE_URL = "http://export.arxiv.org/api/query"


class ArXivCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        params = {
            "search_query": self.config["query"],
            "start": 0,
            "max_results": self.config.get("max_results", 30),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(BASE_URL, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("arxiv_fetch_failed", error=str(e))
            return []

        feed = feedparser.parse(resp.text)
        articles = []

        for entry in feed.entries:
            articles.append(
                RawArticle(
                    source_name=self.name,
                    source_type="arxiv",
                    title=entry.get("title", "").replace("\n", " ").strip(),
                    url=entry.get("link", ""),
                    content=entry.get("summary", "").replace("\n", " "),
                    author=", ".join(
                        a.get("name", "") for a in entry.get("authors", [])
                    ),
                    published_at=self._parse_date(entry.get("published_parsed")),
                    category=self.category,
                    priority=self.priority,
                    raw_metadata={
                        "arxiv_id": entry.get("id", ""),
                        "categories": [t["term"] for t in entry.get("tags", [])],
                        "pdf_url": next(
                            (
                                lnk["href"]
                                for lnk in entry.get("links", [])
                                if lnk.get("type") == "application/pdf"
                            ),
                            None,
                        ),
                    },
                )
            )

        keywords = self.config.get("filter_keywords", [])
        filtered = self._apply_keyword_filter(articles, keywords)
        logger.info("arxiv_collected", total=len(articles), filtered=len(filtered))
        return filtered
