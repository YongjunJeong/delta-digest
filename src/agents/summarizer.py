"""Article summarization agent — uses Gemini for Korean quality summaries."""
import asyncio

import structlog

from src.agents.llm_client import LLMClient

logger = structlog.get_logger(__name__)

SUMMARIZATION_SYSTEM = """당신은 AI/데이터 엔지니어링 전문가를 위한 기술 뉴스 요약 전문가입니다.
주어진 기사를 한국어로 요약하되, 기술 용어(Delta Lake, Spark, LLM 등)는 영어 원문 그대로 유지하세요.
문체는 "~다" 체를 사용하세요.
반드시 유효한 JSON만 반환하세요.

작성 원칙 (AI 냄새 제거):
- 구체적 사실과 수치를 써라. "획기적이다", "혁신적이다", "주목할 만하다" 같은 표현은 쓰지 않는다.
- 과도한 의미부여를 피하라. "새로운 시대를 열었다", "패러다임이 바뀌고 있다" 같은 문장은 쓰지 않는다.
- 막연한 귀속을 피하라. "전문가들은", "업계에서는" 대신 구체적 출처나 회사명을 쓴다.
- AI 과용어를 쓰지 않는다: "더불어", "아울러", "핵심적인", "중추적인", "~을 강조한다", "~을 보여준다", "~에 기여한다".
- 긍정적 결론으로 마무리하지 않는다. "앞으로가 기대된다", "미래가 밝다" 같은 표현은 쓰지 않는다.
- 세 가지를 억지로 묶어 나열하지 않는다.

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
