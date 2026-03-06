"""Daily pipeline orchestrator: collect → bronze → silver → gold → digest."""
import asyncio
import sys
from datetime import date

import structlog

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.ingestion.run_all import run_all_collectors
from src.output.markdown_writer import write_digest
from src.pipeline.bronze import write_bronze
from src.pipeline.gold import read_gold, silver_to_gold
from src.pipeline.silver import bronze_to_silver
from src.pipeline.spark_session import get_spark, stop_spark

setup_logging()
logger = get_logger("run_daily")


async def run_pipeline(
    ingestion_date: date | None = None,
    use_mock_scores: bool = False,
    skip_podcast: bool = False,
) -> None:
    if ingestion_date is None:
        ingestion_date = date.today()

    logger.info("pipeline_start", date=str(ingestion_date))

    # ── Step 1: Collect ──────────────────────────────────────────────────────
    logger.info("step1_collect")
    articles = await run_all_collectors()
    total_collected = len(articles)
    logger.info("collect_done", count=total_collected)

    # ── Step 2: Bronze ───────────────────────────────────────────────────────
    logger.info("step2_bronze")
    spark = get_spark()
    write_bronze(spark, articles, settings.bronze_path, ingestion_date)

    # ── Step 3: Silver ───────────────────────────────────────────────────────
    logger.info("step3_silver")
    silver_count = bronze_to_silver(
        spark, settings.bronze_path, settings.silver_path, ingestion_date
    )

    # ── Step 4: AI Scoring + Summarization ──────────────────────────────────
    # Memory management: stop Spark before loading Ollama (24GB ARM)
    logger.info("step4_ai_scoring", silver_articles=silver_count)
    stop_spark()

    from src.pipeline.silver import read_silver
    spark2 = get_spark()
    silver_df = read_silver(spark2, settings.silver_path, ingestion_date)
    silver_articles = [row.asDict() for row in silver_df.collect()]
    stop_spark()

    if use_mock_scores:
        scored, summaries = _mock_scores(silver_articles)
    else:
        scored, summaries = await _run_ai_pipeline(silver_articles)

    # ── Step 5: Gold ─────────────────────────────────────────────────────────
    logger.info("step5_gold")
    spark3 = get_spark()
    silver_to_gold(
        spark3,
        settings.silver_path,
        settings.gold_path,
        ingestion_date,
        scored,
        summaries,
        top_n=20,
    )

    # ── Step 6: Digest ───────────────────────────────────────────────────────
    logger.info("step6_digest")
    from src.pipeline.gold import read_gold
    gold_df = read_gold(spark3, settings.gold_path, ingestion_date, digest_only=True)
    digest_articles = [row.asDict() for row in gold_df.collect()]
    stop_spark()

    output_path = write_digest(digest_articles, total_collected, ingestion_date)

    # ── Step 7: Podcast ──────────────────────────────────────────────────────
    logger.info("step7_podcast")
    if use_mock_scores or skip_podcast:
        logger.info("podcast_skipped", reason="mock_mode_or_skip_flag")
    else:
        from src.agents.scriptwriter import ScriptWriter
        from src.output.podcast_producer import PodcastProducer
        from src.agents.router import LLMRouter

        router_for_podcast = LLMRouter()
        gemini = router_for_podcast.get_client("scriptwriting")
        writer = ScriptWriter(gemini)
        script = await writer.generate(digest_articles, ingestion_date)

        if script.turns:
            producer = PodcastProducer()
            podcast_path = await producer.produce(script, ingestion_date)
            print(f"\n🎙️  Podcast saved: {podcast_path}  ({script.estimated_minutes} min)")
        else:
            logger.warning("podcast_empty_script")

    logger.info(
        "pipeline_complete",
        date=str(ingestion_date),
        collected=total_collected,
        silver=silver_count,
        digest_articles=len(digest_articles),
        output=str(output_path),
    )
    print(f"\n✅ Digest saved: {output_path}")


async def _run_ai_pipeline(
    silver_articles: list[dict],
) -> tuple[list[dict], dict]:
    from src.agents.router import LLMRouter
    from src.agents.scorer import score_batch
    from src.agents.summarizer import summarize_batch

    router = LLMRouter()
    health = await router.check_all()

    # Scoring: Ollama preferred, mock fallback
    if health.get("ollama"):
        ollama = router.get_client("scoring")
        scored = await score_batch(ollama, silver_articles, top_n=20)
    else:
        logger.warning("ollama_unavailable_using_mock_scores")
        scored, _ = _mock_scores(silver_articles)

    # Summarization: Gemini (independent of Ollama)
    summaries: dict = {}
    if health.get("gemini"):
        top_urls = {s["url"] for s in sorted(scored, key=lambda x: -x["overall_score"])[:20]}
        top_articles = [a for a in silver_articles if a["url"] in top_urls]
        gemini = router.get_client("summarization")
        summaries = await summarize_batch(gemini, top_articles)
    else:
        logger.warning("gemini_unavailable_skipping_summaries")

    return scored, summaries


def _mock_scores(articles: list[dict]) -> tuple[list[dict], dict]:
    """Fallback mock scores when Ollama is unavailable."""
    import random
    random.seed(42)
    scored = []
    summaries = {}
    for a in articles:
        # Give all articles realistic scores — quota selection handles Databricks priority
        scored.append({
            "url": a["url"],
            "overall_score": round(random.uniform(4.0, 8.5), 1),
            "relevance_score": round(
                random.uniform(6.0, 9.5) if a.get("is_databricks_related") else random.uniform(1.0, 5.0),
                1,
            ),
            "novelty_score": round(random.uniform(4.0, 9.0), 1),
            "one_line_summary": a["title"][:80],
            "reasoning": "",
        })
        summaries[a["url"]] = {
            "full_summary": f"{a['title']} — 실제 운영 시 Gemini가 한국어 요약을 생성합니다.",
            "key_points": [],
            "tech_keywords": [],
        }
    return scored, summaries


if __name__ == "__main__":
    mock = "--mock" in sys.argv
    no_podcast = "--no-podcast" in sys.argv
    asyncio.run(run_pipeline(use_mock_scores=mock, skip_podcast=no_podcast))
