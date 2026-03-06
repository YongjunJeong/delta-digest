import sys; sys.path.insert(0, ".")
from src.pipeline.spark_session import get_spark, stop_spark
from src.common.config import settings
from pyspark.sql.functions import col, length

spark = get_spark()
df = spark.read.format("delta").load(settings.bronze_path)

print("=== Databricks Blog content samples ===")
for row in df.filter(col("source_name") == "Databricks Blog").select("title", "content").take(3):
    print(f"TITLE: {row.title}")
    print(f"CONTENT ({len((row.content or '').split())} words): {(row.content or '')[:300]}")
    print()

stop_spark()
