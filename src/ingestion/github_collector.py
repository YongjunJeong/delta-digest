from datetime import datetime, timezone

import httpx
import structlog

from src.common.models import RawArticle
from src.ingestion.base import BaseCollector

logger = structlog.get_logger(__name__)

# GitHub Trending has no official API — scrape the explore page via GH search API
SEARCH_URL = "https://api.github.com/search/repositories"


class GitHubCollector(BaseCollector):
    """Collect trending AI/ML repositories via GitHub Search API."""

    async def collect(self) -> list[RawArticle]:
        # Build query: recently updated AI/ML repos with good stars
        # GitHub Search API: multiple topic filters use separate topic: qualifiers
        language = self.config.get("language", "")
        query = "topic:llm stars:>100 pushed:>2025-01-01"
        if language:
            query += f" language:{language}"

        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": 30,
        }

        headers = {"Accept": "application/vnd.github.v3+json"}
        # GitHub token optional — unauthenticated = 10 req/min (sufficient for daily)
        token = self.config.get("token")
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(SEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.error("github_fetch_failed", error=str(e))
            return []

        articles = []
        for repo in data.get("items", []):
            description = repo.get("description") or ""
            content = f"{description}\n\nTopics: {', '.join(repo.get('topics', []))}"
            articles.append(
                RawArticle(
                    source_name=self.name,
                    source_type="github",
                    title=repo["full_name"],
                    url=repo["html_url"],
                    content=content,
                    author=repo.get("owner", {}).get("login"),
                    published_at=datetime.fromisoformat(
                        repo["created_at"].replace("Z", "+00:00")
                    ).replace(tzinfo=None),
                    category=self.category,
                    priority=self.priority,
                    raw_metadata={
                        "stars": repo.get("stargazers_count", 0),
                        "forks": repo.get("forks_count", 0),
                        "language": repo.get("language", ""),
                        "topics": repo.get("topics", []),
                        "updated_at": repo.get("updated_at", ""),
                    },
                )
            )

        keywords = self.config.get("filter_keywords", [])
        filtered = self._apply_keyword_filter(articles, keywords)
        logger.info("github_collected", total=len(articles), filtered=len(filtered))
        return filtered

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    SEARCH_URL,
                    params={"q": "stars:>1000", "per_page": 1},
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
