from pyspark.sql.types import (
    BooleanType,
    DateType,
    FloatType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# Bronze: raw ingestion — one row per article, never updated
BRONZE_SCHEMA = StructType([
    StructField("url", StringType(), nullable=False),          # MERGE key
    StructField("title", StringType(), nullable=True),
    StructField("content", StringType(), nullable=True),       # raw HTML or plaintext
    StructField("author", StringType(), nullable=True),
    StructField("source_name", StringType(), nullable=True),
    StructField("source_type", StringType(), nullable=True),   # rss | arxiv | hn | github
    StructField("category", StringType(), nullable=True),      # databricks | ai | research | ...
    StructField("priority", StringType(), nullable=True),      # high | medium | low
    StructField("published_at", TimestampType(), nullable=True),
    StructField("collected_at", TimestampType(), nullable=True),
    StructField("ingestion_date", DateType(), nullable=False),  # partition key
    StructField("raw_metadata", StringType(), nullable=True),  # JSON string
])

# Silver: cleansed — HTML stripped, deduped, word count added
SILVER_SCHEMA = StructType([
    StructField("url", StringType(), nullable=False),
    StructField("title", StringType(), nullable=True),
    StructField("clean_content", StringType(), nullable=True),
    StructField("word_count", IntegerType(), nullable=True),
    StructField("author", StringType(), nullable=True),
    StructField("source_name", StringType(), nullable=True),
    StructField("source_type", StringType(), nullable=True),
    StructField("category", StringType(), nullable=True),
    StructField("priority", StringType(), nullable=True),
    StructField("published_at", TimestampType(), nullable=True),
    StructField("collected_at", TimestampType(), nullable=True),
    StructField("ingestion_date", DateType(), nullable=False),  # partition key
    StructField("is_databricks_related", BooleanType(), nullable=True),
    StructField("raw_metadata", StringType(), nullable=True),
])

# Gold: AI-enriched — Silver + scoring + summary
GOLD_SCHEMA = StructType([
    StructField("url", StringType(), nullable=False),
    StructField("title", StringType(), nullable=True),
    StructField("clean_content", StringType(), nullable=True),
    StructField("word_count", IntegerType(), nullable=True),
    StructField("author", StringType(), nullable=True),
    StructField("source_name", StringType(), nullable=True),
    StructField("source_type", StringType(), nullable=True),
    StructField("category", StringType(), nullable=True),
    StructField("priority", StringType(), nullable=True),
    StructField("published_at", TimestampType(), nullable=True),
    StructField("collected_at", TimestampType(), nullable=True),
    StructField("ingestion_date", DateType(), nullable=False),  # partition key
    StructField("is_databricks_related", BooleanType(), nullable=True),
    # AI-generated columns
    StructField("overall_score", FloatType(), nullable=True),
    StructField("relevance_score", FloatType(), nullable=True),
    StructField("novelty_score", FloatType(), nullable=True),
    StructField("one_line_summary", StringType(), nullable=True),
    StructField("full_summary", StringType(), nullable=True),
    StructField("digest_included", BooleanType(), nullable=True),
    StructField("raw_metadata", StringType(), nullable=True),
])

# Schema for AI scoring results to join back into Silver
GOLD_ADDITIONS_SCHEMA = StructType([
    StructField("url", StringType(), nullable=False),
    StructField("overall_score", FloatType(), nullable=True),
    StructField("relevance_score", FloatType(), nullable=True),
    StructField("novelty_score", FloatType(), nullable=True),
    StructField("one_line_summary", StringType(), nullable=True),
    StructField("full_summary", StringType(), nullable=True),
])
