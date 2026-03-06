import asyncio
from datetime import datetime

import httpx
import structlog

from src.common.models import RawArticle
from src.ingestion.base import BaseCollector

logger = structlog.get_logger(__name__)

BASE_URL = "https://hacker-news.firebaseio.com/v0"


class HNCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{BASE_URL}/topstories.json")
                resp.raise_for_status()
                story_ids = resp.json()[:50]

                semaphore = asyncio.Semaphore(10)

                async def fetch_story(sid: int) -> dict | None:
                    async with semaphore:
                        try:
                            r = await client.get(f"{BASE_URL}/item/{sid}.json")
                            return r.json()
                        except httpx.HTTPError:
                            return None

                stories = await asyncio.gather(
                    *[fetch_story(sid) for sid in story_ids],
                    return_exceptions=True,
                )

        except httpx.HTTPError as e:
            logger.error("hn_fetch_failed", error=str(e))
            return []

        articles = []
        for story in stories:
            if isinstance(story, Exception) or not story:
                continue
            if story.get("type") != "story" or not story.get("url"):
                continue
            articles.append(
                RawArticle(
                    source_name=self.name,
                    source_type="hn",
                    title=story.get("title", ""),
                    url=story["url"],
                    content=story.get("text", ""),
                    author=story.get("by"),
                    published_at=datetime.fromtimestamp(story.get("time", 0)),
                    category=self.category,
                    priority=self.priority,
                    raw_metadata={
                        "hn_id": story["id"],
                        "score": story.get("score", 0),
                        "comments": story.get("descendants", 0),
                    },
                )
            )

        keywords = self.config.get("filter_keywords", [])
        filtered = self._apply_keyword_filter(articles, keywords)
        logger.info("hn_collected", total=len(articles), filtered=len(filtered))
        return filtered

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{BASE_URL}/topstories.json")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
