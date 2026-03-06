"""Bronze layer: raw ingestion with MERGE upsert into Delta Lake."""
import json
from datetime import date, datetime

from delta.tables import DeltaTable
from pyspark.sql import SparkSession

from src.common.logging import get_logger
from src.common.models import RawArticle
from src.pipeline.schemas import BRONZE_SCHEMA

logger = get_logger(__name__)


def articles_to_rows(articles: list[RawArticle], ingestion_date: date) -> list[dict]:
    """Convert RawArticle dataclasses to Bronze row dicts."""
    rows = []
    for a in articles:
        rows.append({
            "url": a.url,
            "title": a.title,
            "content": a.content,
            "author": a.author,
            "source_name": a.source_name,
            "source_type": a.source_type,
            "category": a.category,
            "priority": a.priority,
            "published_at": a.published_at,
            "collected_at": a.collected_at,
            "ingestion_date": ingestion_date,
            "raw_metadata": json.dumps(a.raw_metadata, ensure_ascii=False),
        })
    return rows


def write_bronze(
    spark: SparkSession,
    articles: list[RawArticle],
    bronze_path: str,
    ingestion_date: date | None = None,
) -> int:
    """Write raw articles to Bronze layer with MERGE upsert.

    - New URLs are inserted, existing URLs are skipped (raw data is immutable).
    - Partitioned by ingestion_date.

    Returns:
        Number of rows in the incoming DataFrame.
    """
    if not articles:
        logger.warning("bronze_write_skipped", reason="no articles")
        return 0

    if ingestion_date is None:
        ingestion_date = datetime.utcnow().date()

    rows = articles_to_rows(articles, ingestion_date)
    df = spark.createDataFrame(rows, schema=BRONZE_SCHEMA)

    if DeltaTable.isDeltaTable(spark, bronze_path):
        logger.info("bronze_merge_start", path=bronze_path, incoming=df.count())
        delta_table = DeltaTable.forPath(spark, bronze_path)
        (
            delta_table.alias("target")
            .merge(df.alias("source"), "target.url = source.url")
            .whenNotMatchedInsertAll()
            .execute()
        )
        logger.info("bronze_merge_done")
    else:
        logger.info("bronze_initial_write", path=bronze_path, count=df.count())
        (
            df.write.format("delta")
            .partitionBy("ingestion_date")
            .save(bronze_path)
        )

    count = df.count()
    logger.info("bronze_write_complete", ingestion_date=str(ingestion_date), count=count)
    return count


def read_bronze(
    spark: SparkSession,
    bronze_path: str,
    ingestion_date: date | None = None,
):
    """Read Bronze layer, optionally filtered by date."""
    df = spark.read.format("delta").load(bronze_path)
    if ingestion_date is not None:
        df = df.filter(df.ingestion_date == ingestion_date)
    return df
