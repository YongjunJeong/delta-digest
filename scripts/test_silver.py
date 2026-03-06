"""Silver pipeline + LLM health check smoke test."""
import asyncio
import sys
from datetime import date
sys.path.insert(0, ".")

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.pipeline.silver import bronze_to_silver, read_silver
from src.pipeline.spark_session import get_spark, stop_spark
from src.agents.router import LLMRouter

setup_logging()
logger = get_logger("test_silver")


async def main() -> None:
    today = date.today()

    # 1. Bronze → Silver
    logger.info("step1_silver_transform")
    spark = get_spark()
    count = bronze_to_silver(spark, settings.bronze_path, settings.silver_path, today)
    logger.info("silver_written", count=count)

    # 2. Verify Silver
    df = read_silver(spark, settings.silver_path, today)
    df.select("source_type", "title", "word_count", "is_databricks_related").show(10, truncate=60)

    # Stats
    print("\n=== Silver Stats ===")
    df.groupBy("source_type").count().orderBy("count", ascending=False).show()
    df.groupBy("is_databricks_related").count().show()

    total = df.count()
    db_related = df.filter(df.is_databricks_related).count()
    logger.info("silver_stats", total=total, databricks_related=db_related)

    stop_spark()

    # 3. LLM Health Check
    logger.info("step2_llm_health_check")
    router = LLMRouter()
    health = await router.check_all()
    logger.info("llm_health_results", **health)

    logger.info("all_checks_passed")


if __name__ == "__main__":
    asyncio.run(main())
