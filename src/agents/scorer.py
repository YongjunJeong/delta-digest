"""Article scoring agent — uses Ollama (local) for high-volume JSON scoring."""
import asyncio

import structlog

from src.agents.llm_client import LLMClient

logger = structlog.get_logger(__name__)

SCORING_SYSTEM = """You are a tech news relevance scorer for a Databricks/AI professional.
Rate the article and respond ONLY with valid JSON, no extra text.

JSON schema:
{
  "overall_score": <float 1.0-10.0>,
  "relevance_score": <float 0.0-10.0>,
  "novelty_score": <float 0.0-10.0>,
  "one_line_summary": "<Korean, max 80 chars>",
  "reasoning": "<Korean, 1-2 sentences>"
}

Scoring criteria:
- overall_score: general interest and quality (1=spam, 10=must-read)
- relevance_score: relevance to Databricks/Delta Lake/Spark/LLM/AI engineering (0=unrelated, 10=core topic)
- novelty_score: how new or surprising the information is (0=old news, 10=breakthrough)"""

DEFAULT_SCORES = {
    "overall_score": 5.0,
    "relevance_score": 0.0,
    "novelty_score": 5.0,
    "one_line_summary": "",
    "reasoning": "",
}


async def score_article(client: LLMClient, title: str, content: str) -> dict:
    """Score a single article. Returns dict with defaults on failure."""
    prompt = f"Title: {title}\n\nContent (first 1500 chars):\n{content[:1500]}"
    result = await client.generate_json(prompt=prompt, system=SCORING_SYSTEM)

    if not result:
        return DEFAULT_SCORES | {"one_line_summary": title[:80]}

    return {
        "overall_score": max(1.0, min(10.0, float(result.get("overall_score", 5.0)))),
        "relevance_score": max(0.0, min(10.0, float(result.get("relevance_score", 0.0)))),
        "novelty_score": max(0.0, min(10.0, float(result.get("novelty_score", 5.0)))),
        "one_line_summary": str(result.get("one_line_summary", title[:80])),
        "reasoning": str(result.get("reasoning", "")),
    }


async def score_batch(
    client: LLMClient,
    articles: list[dict],
    top_n: int = 20,
) -> list[dict]:
    """Score all articles and return top_n by overall_score.

    Processes sequentially — Ollama is a single model instance.
    """
    results = []
    total = len(articles)

    for i, article in enumerate(articles):
        logger.info(
            "scoring_article",
            progress=f"{i + 1}/{total}",
            title=article["title"][:60],
        )
        try:
            scored = await score_article(client, article["title"], article["clean_content"])
        except Exception as e:
            logger.error("score_article_failed", title=article["title"][:60], error=str(e))
            scored = DEFAULT_SCORES | {"one_line_summary": article["title"][:80]}

        scored["url"] = article["url"]
        results.append(scored)

    # Sort by overall_score desc and mark top_n
    results.sort(key=lambda x: x["overall_score"], reverse=True)
    for i, r in enumerate(results):
        r["digest_included"] = i < top_n

    logger.info("scoring_complete", total=total, top_n=top_n)
    return results
