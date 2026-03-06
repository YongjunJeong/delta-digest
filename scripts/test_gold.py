"""Gold pipeline smoke test — uses mock scores (no Ollama needed)."""
import json
import sys
from datetime import date
sys.path.insert(0, ".")

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.pipeline.gold import silver_to_gold, read_gold
from src.pipeline.silver import read_silver
from src.pipeline.spark_session import get_spark, stop_spark

setup_logging()
logger = get_logger("test_gold")


def build_mock_scores(articles: list[dict], top_n: int = 20) -> tuple[list[dict], dict]:
    """Generate mock scores for testing without Ollama."""
    import random
    random.seed(42)

    scored = []
    summaries = {}

    for i, a in enumerate(articles):
        # Databricks-related articles get higher scores
        base = 8.0 if a.get("is_databricks_related") else random.uniform(3.0, 7.0)
        scored.append({
            "url": a["url"],
            "overall_score": round(base + random.uniform(-0.5, 0.5), 1),
            "relevance_score": round(8.0 if a.get("is_databricks_related") else random.uniform(1.0, 5.0), 1),
            "novelty_score": round(random.uniform(4.0, 9.0), 1),
            "one_line_summary": f"[mock] {a['title'][:70]}",
            "reasoning": "테스트용 mock 스코어입니다.",
        })
        summaries[a["url"]] = {
            "full_summary": f"[mock 요약] {a['title']}에 관한 기사이다. 주요 내용을 확인하시오.",
            "key_points": ["핵심 포인트 1", "핵심 포인트 2"],
            "tech_keywords": ["AI", "LLM"],
        }

    return scored, summaries


def main() -> None:
    today = date.today()
    spark = get_spark()

    # 1. Read Silver
    logger.info("step1_read_silver")
    silver_df = read_silver(spark, settings.silver_path, today)
    articles = [row.asDict() for row in silver_df.collect()]
    logger.info("silver_articles", count=len(articles))

    # 2. Mock scores + summaries
    logger.info("step2_mock_scoring")
    scored, summaries = build_mock_scores(articles, top_n=20)
    logger.info("scoring_done", total=len(scored))

    # 3. Write Gold
    logger.info("step3_write_gold")
    count = silver_to_gold(
        spark,
        settings.silver_path,
        settings.gold_path,
        today,
        scored,
        summaries,
        top_n=20,
    )
    logger.info("gold_written", count=count)

    # 4. Verify
    logger.info("step4_verify")
    gold_df = read_gold(spark, settings.gold_path, today)
    gold_df.select(
        "source_type", "title", "overall_score", "relevance_score", "digest_included"
    ).orderBy("overall_score", ascending=False).show(15, truncate=55)

    digest_df = read_gold(spark, settings.gold_path, today, digest_only=True)
    digest_count = digest_df.count()
    logger.info("digest_articles", count=digest_count)

    # Top 5 for digest
    print("\n=== Top 5 Digest Articles ===")
    for row in digest_df.orderBy("overall_score", ascending=False).take(5):
        print(f"  [{row.overall_score:.1f}] {row.title[:70]}")
        print(f"         {row.one_line_summary[:80]}")

    # Source breakdown
    print("\n=== Gold Source Breakdown ===")
    gold_df.groupBy("source_type").count().orderBy("count", ascending=False).show()

    stop_spark()
    logger.info("all_checks_passed")


if __name__ == "__main__":
    main()
