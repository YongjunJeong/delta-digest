"""Article summarization agent — uses Gemini for Korean quality summaries."""
import asyncio

import structlog

from src.agents.llm_client import LLMClient

logger = structlog.get_logger(__name__)

SUMMARIZATION_SYSTEM = """당신은 AI/데이터 엔지니어링 전문가를 위한 기술 뉴스 요약 전문가입니다.
주어진 기사를 한국어로 요약하되, 기술 용어(Delta Lake, Spark, LLM 등)는 영어 원문 그대로 유지하세요.
문체는 "~다" 체를 사용하세요.
반드시 유효한 JSON만 반환하세요.

JSON schema:
{
  "full_summary": "<3-5문장 요약, 핵심 기술 내용 포함>",
  "key_points": ["<핵심 포인트 1>", "<핵심 포인트 2>", "<핵심 포인트 3>"],
  "tech_keywords": ["<기술 키워드1>", "<기술 키워드2>"]
}"""


async def summarize_article(client: LLMClient, title: str, content: str) -> dict:
    """Generate Korean summary for a single article."""
    prompt = f"제목: {title}\n\n내용:\n{content[:3000]}"
    result = await client.generate_json(prompt=prompt, system=SUMMARIZATION_SYSTEM)

    if not result:
        return {
            "full_summary": f"{title}에 관한 기사이다.",
            "key_points": [],
            "tech_keywords": [],
        }

    return {
        "full_summary": str(result.get("full_summary", "")),
        "key_points": result.get("key_points", []),
        "tech_keywords": result.get("tech_keywords", []),
    }


async def summarize_batch(
    client: LLMClient,
    articles: list[dict],
    delay_seconds: float = 1.0,
) -> dict[str, dict]:
    """Summarize a list of articles. Returns dict keyed by URL.

    Uses delay between calls to respect Gemini free tier rate limits.
    """
    results: dict[str, dict] = {}
    total = len(articles)

    for i, article in enumerate(articles):
        logger.info(
            "summarizing_article",
            progress=f"{i + 1}/{total}",
            title=article["title"][:60],
        )
        try:
            summary = await summarize_article(client, article["title"], article["clean_content"])
        except Exception as e:
            logger.error("summarize_failed", title=article["title"][:60], error=str(e))
            summary = {
                "full_summary": f"{article['title']}에 관한 기사이다.",
                "key_points": [],
                "tech_keywords": [],
            }

        results[article["url"]] = summary

        # Respect Gemini free tier — small delay between calls
        if i < total - 1:
            await asyncio.sleep(delay_seconds)

    logger.info("summarization_complete", total=total)
    return results
