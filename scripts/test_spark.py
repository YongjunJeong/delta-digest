"""Quick smoke test: SparkSession + Delta Lake write/read."""
import sys
sys.path.insert(0, ".")

from src.common.logging import setup_logging, get_logger
from src.pipeline.spark_session import get_spark, stop_spark

setup_logging()
logger = get_logger("test_spark")


def main() -> None:
    spark = get_spark()
    logger.info("spark_version", version=spark.version)

    # Write a small Delta table
    df = spark.createDataFrame(
        [("article_1", "Delta Lake test"), ("article_2", "Spark test")],
        ["url", "title"],
    )
    df.write.format("delta").mode("overwrite").save("data/test_delta")
    logger.info("delta_write_ok")

    # Read back
    df2 = spark.read.format("delta").load("data/test_delta")
    df2.show()
    logger.info("delta_read_ok", count=df2.count())

    # Time travel
    from delta.tables import DeltaTable
    dt = DeltaTable.forPath(spark, "data/test_delta")
    dt.history().select("version", "timestamp", "operation").show()
    logger.info("time_travel_ok")

    stop_spark()
    logger.info("all_checks_passed")


if __name__ == "__main__":
    main()
