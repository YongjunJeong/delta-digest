"""Bronze pipeline smoke test: collect → write → verify."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.ingestion.run_all import run_all_collectors
from src.pipeline.bronze import write_bronze, read_bronze
from src.pipeline.spark_session import get_spark, stop_spark
from delta.tables import DeltaTable

setup_logging()
logger = get_logger("test_bronze")


async def main() -> None:
    # 1. Collect
    logger.info("step1_collect")
    articles = await run_all_collectors()
    logger.info("collected", count=len(articles))

    # 2. Write to Bronze
    logger.info("step2_bronze_write")
    spark = get_spark()
    count = write_bronze(spark, articles, settings.bronze_path)
    logger.info("bronze_written", count=count)

    # 3. Verify
    logger.info("step3_verify")
    df = read_bronze(spark, settings.bronze_path)
    df.select("source_type", "title", "url", "ingestion_date").show(10, truncate=60)
    logger.info("bronze_total_rows", count=df.count())

    # 4. Source breakdown
    df.groupBy("source_type").count().orderBy("count", ascending=False).show()

    # 5. Time Travel
    dt = DeltaTable.forPath(spark, settings.bronze_path)
    dt.history().select("version", "timestamp", "operation", "operationMetrics").show(5, truncate=80)

    # 6. Re-run idempotency test (same articles → no new rows)
    count2 = write_bronze(spark, articles, settings.bronze_path)
    df2 = read_bronze(spark, settings.bronze_path)
    assert df2.count() == df.count(), "Idempotency FAILED: duplicate rows inserted!"
    logger.info("idempotency_ok", count=df2.count())

    stop_spark()
    logger.info("all_checks_passed")


if __name__ == "__main__":
    asyncio.run(main())
