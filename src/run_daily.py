"""Daily pipeline orchestrator: collect → bronze → silver → gold → digest."""
import asyncio
import sys
from datetime import date
from pathlib import Path

import structlog

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.ingestion.run_all import run_all_collectors
from src.output.pdf_writer import write_pdfs
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

    from src.output.slack_notifier import SlackNotifier
    notifier: SlackNotifier | None = None
    if settings.slack_bot_token and settings.slack_channel_id:
        notifier = SlackNotifier(settings.slack_bot_token, settings.slack_channel_id)
    current_step = "init"
    new_since_yesterday = 0

    try:
        logger.info("pipeline_start", date=str(ingestion_date))

        # ── Step 1: Collect ──────────────────────────────────────────────────────
        logger.info("step1_collect")
        current_step = "step1_collect"
        articles = await run_all_collectors()
        total_collected = len(articles)
        logger.info("collect_done", count=total_collected)

        # ── Step 2: Bronze ───────────────────────────────────────────────────────
        logger.info("step2_bronze")
        current_step = "step2_bronze"
        spark = get_spark()
        write_bronze(spark, articles, settings.bronze_path, ingestion_date)

        # ── Step 3: Silver ───────────────────────────────────────────────────────
        logger.info("step3_silver")
        current_step = "step3_silver"
        silver_count = bronze_to_silver(
            spark, settings.bronze_path, settings.silver_path, ingestion_date
        )

        # ── Step 4: AI Scoring + Summarization ──────────────────────────────────
        # Memory management: stop Spark before loading Ollama (24GB ARM)
        logger.info("step4_ai_scoring", silver_articles=silver_count)
        current_step = "step4_ai_scoring"
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
        current_step = "step5_gold"
        spark3 = get_spark()
        silver_to_gold(
            spark3,
            settings.silver_path,
            settings.gold_path,
            ingestion_date,
            scored,
            summaries,
            top_n=40,
        )

        # ── Step 6: Digest ───────────────────────────────────────────────────────
        logger.info("step6_digest")
        current_step = "step6_digest"
        gold_df = read_gold(spark3, settings.gold_path, ingestion_date, digest_only=True)
        digest_articles = [row.asDict() for row in gold_df.collect()]

        from src.pipeline.gold import count_new_since_yesterday
        new_since_yesterday = count_new_since_yesterday(spark3, settings.gold_path, ingestion_date)
        logger.info("new_since_yesterday", count=new_since_yesterday)
        stop_spark()

        pdf_paths = write_pdfs(digest_articles, total_collected, ingestion_date)

        if notifier:
            db_count = sum(1 for a in digest_articles if a.get("is_databricks_related"))
            ai_count = len(digest_articles) - db_count
            notifier.notify_success(
                ingestion_date=str(ingestion_date),
                stats={
                    "collected": total_collected,
                    "digest": len(digest_articles),
                    "db": db_count,
                    "ai": ai_count,
                    "other": 0,
                },
                pdf_paths=[Path(p) for p in pdf_paths],
                new_since_yesterday=new_since_yesterday,
            )

        # ── Step 6.5: Glossary ───────────────────────────────────────────────────────
        logger.info("step6_5_glossary")
        current_step = "step6_5_glossary"
        if not use_mock_scores:
            from src.agents.glossary_agent import GlossaryAgent
            from src.agents.router import LLMRouter
            from src.output.pdf_writer import write_glossary_pdf

            glossary_router = LLMRouter()
            glossary_health = await glossary_router.check_all()
            if glossary_health.get("gemini"):
                gemini_client = glossary_router.get_client("summarization")
                top_articles = sorted(
                    digest_articles, key=lambda x: -x.get("overall_score", 0)
                )[:20]
                glossary_agent = GlossaryAgent(gemini_client, settings.glossary_path)
                new_terms = await glossary_agent.update(top_articles, ingestion_date)

                if new_terms:
                    glossary_path = write_glossary_pdf(
                        new_terms, glossary_agent.all_terms, ingestion_date
                    )
                    print(f"\n📚 Glossary saved: {glossary_path} ({len(new_terms)} new terms)")
                else:
                    logger.info("glossary_pdf_skipped", reason="no_new_terms")
            else:
                logger.info("glossary_skipped", reason="gemini_unavailable")
        else:
            logger.info("glossary_skipped", reason="mock_mode")

        # ── Step 7: Podcast ──────────────────────────────────────────────────────
        logger.info("step7_podcast")
        current_step = "step7_podcast"
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
        )
        for p in pdf_paths:
            print(f"\n📄 PDF saved: {p}")

    except Exception as e:
        logger.error("pipeline_failed", step=current_step, error=str(e))
        if notifier:
            notifier.notify_failure(str(ingestion_date), current_step, str(e))
        raise


async def _run_ai_pipeline(
    silver_articles: list[dict],
) -> tuple[list[dict], dict]:
    from src.agents.router import LLMRouter
    from src.agents.scorer import score_batch
    from src.agents.summarizer import summarize_batch

    router = LLMRouter()
    health = await router.check_all()

    # Scoring: Ollama preferred, mock fallback
    # Pre-filter to top candidates by source priority before scoring (ARM CPU is slow)
    SCORE_LIMIT = 200
    priority_order = {"high": 0, "medium": 1, "low": 2}
    candidates = sorted(
        silver_articles,
        key=lambda x: priority_order.get(x.get("priority", "medium"), 1),
    )[:SCORE_LIMIT]
    logger.info("scoring_candidates", total_silver=len(silver_articles), candidates=len(candidates))

    if health.get("ollama"):
        ollama = router.get_client("scoring")
        scored = await score_batch(ollama, candidates, top_n=40)
    else:
        logger.warning("ollama_unavailable_using_mock_scores")
        scored, _ = _mock_scores(silver_articles)

    # Summarization: Gemini (independent of Ollama)
    # Use same quota logic as Gold: top 10 Databricks + top 20 AI + top 10 other
    summaries: dict = {}
    if health.get("gemini"):
        silver_by_url = {a["url"]: a for a in silver_articles}
        db_scored = sorted(
            [s for s in scored if silver_by_url.get(s["url"], {}).get("is_databricks_related")],
            key=lambda x: -x["relevance_score"],
        )[:10]
        db_urls = {s["url"] for s in db_scored}
        ai_scored = sorted(
            [s for s in scored if s["url"] not in db_urls],
            key=lambda x: -x["overall_score"],
        )[:20]
        ai_urls = {s["url"] for s in ai_scored}
        other_scored = sorted(
            [s for s in scored if s["url"] not in db_urls and s["url"] not in ai_urls],
            key=lambda x: -x["overall_score"],
        )[:10]
        top_urls = db_urls | ai_urls | {s["url"] for s in other_scored}
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
