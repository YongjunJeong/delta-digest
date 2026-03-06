from pyspark.sql import SparkSession

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

_spark: SparkSession | None = None


def get_spark() -> SparkSession:
    global _spark
    if _spark is None or _spark._jsc.sc().isStopped():
        logger.info("creating_spark_session", driver_memory=settings.spark_driver_memory)
        _spark = (
            SparkSession.builder.appName("delta-digest")
            .master("local[*]")
            .config("spark.driver.memory", settings.spark_driver_memory)
            .config("spark.sql.shuffle.partitions", settings.spark_shuffle_partitions)
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
            .config("spark.jars.packages", "io.delta:delta-spark_2.12:3.2.1")
            .getOrCreate()
        )
        _spark.sparkContext.setLogLevel("WARN")
        logger.info("spark_session_ready")
    return _spark


def stop_spark() -> None:
    global _spark
    if _spark is not None and not _spark._jsc.sc().isStopped():
        logger.info("stopping_spark_session")
        _spark.stop()
        _spark = None
