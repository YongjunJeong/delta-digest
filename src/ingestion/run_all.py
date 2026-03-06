"""Orchestrate all collectors and return aggregated RawArticle list."""
import asyncio
from pathlib import Path

import structlog
import yaml

from src.common.models import RawArticle
from src.ingestion.arxiv_collector import ArXivCollector
from src.ingestion.base import BaseCollector
from src.ingestion.github_collector import GitHubCollector
from src.ingestion.hn_collector import HNCollector
from src.ingestion.rss_collector import RSSCollector

logger = structlog.get_logger(__name__)

SOURCES_FILE = Path(__file__).parent / "sources.yaml"


def build_collectors(config: dict) -> list[BaseCollector]:
    collectors: list[BaseCollector] = []

    for source in config.get("rss", []):
        collectors.append(RSSCollector(source))

    for source in config.get("hn", []):
        collectors.append(HNCollector(source))

    for source in config.get("arxiv", []):
        collectors.append(ArXivCollector(source))

    for source in config.get("github", []):
        collectors.append(GitHubCollector(source))

    return collectors


async def run_all_collectors(sources_path: Path = SOURCES_FILE) -> list[RawArticle]:
    config = yaml.safe_load(sources_path.read_text())
    collectors = build_collectors(config)

    all_articles: list[RawArticle] = []

    for collector in collectors:
        try:
            if not await collector.health_check():
                logger.warning("source_unhealthy", source=collector.name)
                continue
            articles = await collector.collect()
            all_articles.extend(articles)
        except Exception as e:
            logger.error("collector_failed", source=collector.name, error=str(e))
            continue

    logger.info(
        "ingestion_complete",
        total_articles=len(all_articles),
        sources=len(collectors),
    )
    return all_articles


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    from src.common.logging import setup_logging
    setup_logging()

    articles = asyncio.run(run_all_collectors())
    print(f"\n총 수집: {len(articles)}건")
    for a in articles[:5]:
        print(f"  [{a.source_type}] {a.title[:60]}")
