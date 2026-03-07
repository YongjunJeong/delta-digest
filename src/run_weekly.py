"""Weekly digest: aggregate 7 days of Gold data into a single PDF."""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.pipeline.gold import read_gold
from src.pipeline.spark_session import get_spark, stop_spark
from src.output.pdf_writer import write_pdfs

setup_logging()
logger = get_logger("run_weekly")


async def run_weekly(reference_date: date | None = None) -> None:
    if reference_date is None:
        reference_date = date.today()

    week_start = reference_date - timedelta(days=6)
    logger.info("weekly_start", from_date=str(week_start), to_date=str(reference_date))

    spark = get_spark()

    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for i in range(7):
        d = week_start + timedelta(days=i)
        try:
            df = read_gold(spark, settings.gold_path, d, digest_only=True)
            rows = [r.asDict() for r in df.collect()]
            for row in rows:
                if row["url"] not in seen_urls:
                    seen_urls.add(row["url"])
                    all_articles.append(row)
        except Exception:
            logger.warning("weekly_date_missing", date=str(d))

    stop_spark()
    logger.info("weekly_articles_loaded", total=len(all_articles))

    if not all_articles:
        logger.warning("weekly_no_articles")
        return

    week_label = f"{reference_date.year}-W{reference_date.isocalendar()[1]:02d}"
    output_dir = settings.digests_path / "weekly"
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = write_pdfs(
        all_articles,
        total_collected=len(all_articles),
        ingestion_date=reference_date,
        output_dir=output_dir,
    )

    renamed: list[Path] = []
    for p in pdf_paths:
        suffix = "ai" if "digest-ai" in str(p) else "db"
        new_name = output_dir / f"{week_label}-weekly-{suffix}.pdf"
        Path(p).rename(new_name)
        renamed.append(new_name)
        print(f"Weekly PDF: {new_name}")

    if settings.slack_bot_token and settings.slack_channel_id:
        from src.output.slack_notifier import SlackNotifier
        notifier = SlackNotifier(settings.slack_bot_token, settings.slack_channel_id)
        db_count = sum(1 for a in all_articles if a.get("is_databricks_related"))
        notifier.notify_success(
            ingestion_date=f"{week_label} 주간",
            stats={
                "collected": len(all_articles),
                "digest": len(all_articles),
                "db": db_count,
                "ai": len(all_articles) - db_count,
                "other": 0,
            },
            pdf_paths=renamed,
            new_since_yesterday=0,
        )


if __name__ == "__main__":
    asyncio.run(run_weekly())
