"""Silver layer: cleanse Bronze data — strip HTML, deduplicate, enrich."""
import re
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, udf
from pyspark.sql.types import BooleanType, IntegerType, StringType

from src.common.logging import get_logger
from src.pipeline.schemas import SILVER_SCHEMA

logger = get_logger(__name__)

DATABRICKS_KEYWORDS = [
    "databricks", "delta lake", "delta table", "unity catalog",
    "mlflow", "spark", "apache spark", "lakehouse", "dlt",
]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


def _is_databricks_related(
    title: str | None, content: str | None, source_name: str | None = None
) -> bool:
    if source_name and "databricks" in source_name.lower():
        return True
    combined = f"{title or ''} {content or ''}".lower()
    return any(kw in combined for kw in DATABRICKS_KEYWORDS)


# Register as Spark UDFs
strip_html_udf = udf(_strip_html, StringType())
word_count_udf = udf(_word_count, IntegerType())
databricks_check_udf = udf(
    lambda title, content, source_name: _is_databricks_related(title, content, source_name),
    BooleanType(),
)


def bronze_to_silver(
    spark: SparkSession,
    bronze_path: str,
    silver_path: str,
    ingestion_date: date,
    min_word_count: int = 10,
) -> int:
    """Transform Bronze → Silver for a given date.

    Steps:
    1. Read Bronze for the date
    2. Strip HTML from content
    3. Deduplicate by URL
    4. Filter short articles
    5. Add computed columns (word_count, is_databricks_related)
    6. Write with replaceWhere (idempotent)

    Returns:
        Row count written to Silver.
    """
    date_str = str(ingestion_date)

    bronze_df = (
        spark.read.format("delta")
        .load(bronze_path)
        .filter(col("ingestion_date") == ingestion_date)
    )

    raw_count = bronze_df.count()
    logger.info("silver_transform_start", date=date_str, bronze_rows=raw_count)

    silver_df = (
        bronze_df
        .dropDuplicates(["url"])
        .withColumn("clean_content", strip_html_udf(col("content")))
        .withColumn("word_count", word_count_udf(col("clean_content")))
        .withColumn(
            "is_databricks_related",
            databricks_check_udf(col("title"), col("clean_content"), col("source_name")),
        )
        .filter(col("word_count") >= min_word_count)
        .select(
            "url", "title", "clean_content", "word_count",
            "author", "source_name", "source_type",
            "category", "priority",
            "published_at", "collected_at", "ingestion_date",
            "is_databricks_related", "raw_metadata",
        )
    )

    silver_count = silver_df.count()

    (
        silver_df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"ingestion_date = '{date_str}'")
        .partitionBy("ingestion_date")
        .save(silver_path)
    )

    logger.info(
        "silver_transform_done",
        date=date_str,
        bronze_rows=raw_count,
        silver_rows=silver_count,
        dropped=raw_count - silver_count,
    )
    return silver_count


def read_silver(spark: SparkSession, silver_path: str, ingestion_date: date | None = None):
    df = spark.read.format("delta").load(silver_path)
    if ingestion_date is not None:
        df = df.filter(col("ingestion_date") == ingestion_date)
    return df
