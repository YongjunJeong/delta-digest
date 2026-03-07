"""Gold layer: Silver + AI scoring + summarization → digest-ready table."""
import json
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, lit, row_number
from pyspark.sql.window import Window

from src.common.logging import get_logger
from src.pipeline.silver import read_silver

logger = get_logger(__name__)


def silver_to_gold(
    spark: SparkSession,
    silver_path: str,
    gold_path: str,
    ingestion_date: date,
    scored_articles: list[dict],
    summaries: dict[str, dict],
    top_n: int = 20,
) -> int:
    """Merge Silver data with AI results into Gold layer.

    scored_articles: output of scorer.score_batch()  — list of dicts with url + scores
    summaries:       output of summarizer.summarize_batch() — dict[url, summary]

    Returns:
        Row count written to Gold.
    """
    date_str = str(ingestion_date)

    silver_df = read_silver(spark, silver_path, ingestion_date)
    silver_count = silver_df.count()
    logger.info("gold_transform_start", date=date_str, silver_rows=silver_count)

    # Build scores DataFrame
    scores_rows = []
    for s in scored_articles:
        url = s["url"]
        summary_data = summaries.get(url, {})
        scores_rows.append({
            "url": url,
            "overall_score": float(s.get("overall_score", 5.0)),
            "relevance_score": float(s.get("relevance_score", 0.0)),
            "novelty_score": float(s.get("novelty_score", 5.0)),
            "one_line_summary": str(s.get("one_line_summary", "")),
            "full_summary": str(summary_data.get("full_summary", "")),
            "key_points": json.dumps(summary_data.get("key_points", []), ensure_ascii=False),
            "tech_keywords": json.dumps(summary_data.get("tech_keywords", []), ensure_ascii=False),
        })

    scores_df = spark.createDataFrame(scores_rows)

    # Join Silver + AI scores
    gold_df = silver_df.join(scores_df, on="url", how="left")

    # Fill missing scores (articles not scored — shouldn't happen but safe)
    gold_df = (
        gold_df
        .withColumn("overall_score", col("overall_score").cast("float"))
        .fillna({"overall_score": 5.0, "relevance_score": 0.0, "novelty_score": 5.0})
    )

    # Quota-based selection:
    #   - Top 10 Databricks (by relevance_score, is_databricks_related=True)
    #   - Top 20 general AI hot news (by overall_score, excluding already selected)
    #   - Top 10 other (remainder by overall_score)
    quota = _select_digest_urls(gold_df, top_databricks=10, top_ai=20, top_other=10)
    from pyspark.sql.functions import when
    gold_df = gold_df.withColumn(
        "digest_included",
        col("url").isin(quota),
    )

    (
        gold_df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"ingestion_date = '{date_str}'")
        .partitionBy("ingestion_date")
        .save(gold_path)
    )

    gold_count = gold_df.count()
    digest_count = gold_df.filter(col("digest_included")).count()
    logger.info(
        "gold_transform_done",
        date=date_str,
        gold_rows=gold_count,
        digest_included=digest_count,
    )
    return gold_count


def _select_digest_urls(
    gold_df,
    top_databricks: int = 10,
    top_ai: int = 20,
    top_other: int = 10,
) -> list[str]:
    """Return URLs selected by quota: Databricks / hot AI / other."""
    selected: list[str] = []

    # 1. Top Databricks articles
    db_rows = (
        gold_df
        .filter(col("is_databricks_related") == True)  # noqa: E712
        .orderBy(col("relevance_score").desc(), col("overall_score").desc())
        .select("url")
        .limit(top_databricks)
        .collect()
    )
    selected += [r.url for r in db_rows]

    # 2. Top AI hot news (exclude already selected)
    ai_rows = (
        gold_df
        .filter(~col("url").isin(selected))
        .orderBy(col("overall_score").desc())
        .select("url")
        .limit(top_ai)
        .collect()
    )
    selected += [r.url for r in ai_rows]

    # 3. Top other (remainder)
    other_rows = (
        gold_df
        .filter(~col("url").isin(selected))
        .orderBy(col("overall_score").desc())
        .select("url")
        .limit(top_other)
        .collect()
    )
    selected += [r.url for r in other_rows]

    logger.info(
        "digest_quota_selected",
        databricks=len(db_rows),
        ai=len(ai_rows),
        other=len(other_rows),
        total=len(selected),
    )
    return selected


def read_gold(
    spark: SparkSession,
    gold_path: str,
    ingestion_date: date | None = None,
    digest_only: bool = False,
):
    """Read Gold layer, optionally filtered by date and/or digest_included."""
    df = spark.read.format("delta").load(gold_path)
    if ingestion_date is not None:
        df = df.filter(col("ingestion_date") == ingestion_date)
    if digest_only:
        df = df.filter(col("digest_included") == True)  # noqa: E712
    return df


def count_new_since_yesterday(
    spark: SparkSession,
    gold_path: str,
    ingestion_date: date,
) -> int:
    """Return count of digest articles that did not exist in the previous Gold version.

    Uses Delta time travel (VERSION AS OF) to compare today's digest URLs
    against the previous write. Returns full digest count if no prior version exists.
    """
    from delta.tables import DeltaTable

    today_df = read_gold(spark, gold_path, ingestion_date, digest_only=True)
    today_urls = {r.url for r in today_df.select("url").collect()}

    try:
        dt = DeltaTable.forPath(spark, gold_path)
        history = dt.history(2).collect()
        if len(history) < 2:
            return len(today_urls)

        yesterday_version = history[1].version
        yesterday_df = (
            spark.read.format("delta")
            .option("versionAsOf", yesterday_version)
            .load(gold_path)
            .filter(col("digest_included") == True)  # noqa: E712
        )
        yesterday_urls = {r.url for r in yesterday_df.select("url").collect()}
        return len(today_urls - yesterday_urls)
    except Exception as e:
        logger.warning("time_travel_failed", error=str(e))
        return len(today_urls)
