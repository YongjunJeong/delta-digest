"""Dialogue podcast script generator — uses Gemini to create two-host conversation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import structlog

from src.agents.llm_client import LLMClient

logger = structlog.get_logger(__name__)

HOST_A = "소희"
HOST_B = "도현"
VOICE_A = "ko-KR-SunHiNeural"
VOICE_B = "ko-KR-InJoonNeural"

_CHARACTER_BRIEF = f"""진행자 설명:
- {HOST_A}: 데이터 엔지니어링 5년차. 논리적이고 명확하게 기술 내용을 설명한다. 문체는 "~요" 체.
- {HOST_B}: ML 연구 배경. 트렌드에 민감하고 직관적으로 반응한다. \
"오 이거 진짜요?", "그게 왜 중요해요?" 같은 반응. 둘은 오래된 동료로 편안하게 대화한다."""

_JSON_FORMAT = """반드시 아래 형식의 JSON 배열만 반환하세요. 다른 텍스트 없이:
[
  {"speaker": "소희", "text": "대사 내용", "pause_after_ms": 400},
  {"speaker": "도현", "text": "대사 내용", "pause_after_ms": 300}
]
pause_after_ms: 다음 대사 전 침묵 ms. 보통 300-500, 섹션 끝은 800-1000."""


@dataclass
class DialogueTurn:
    speaker: str
    text: str
    pause_after_ms: int = 400


@dataclass
class PodcastScript:
    date: str
    turns: list[DialogueTurn] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(len(t.text) for t in self.turns)

    @property
    def estimated_minutes(self) -> float:
        return round(self.total_chars / 250, 1)

    def to_json(self) -> list[dict]:
        return [
            {"speaker": t.speaker, "text": t.text, "pause_after_ms": t.pause_after_ms}
            for t in self.turns
        ]


class ScriptWriter:
    def __init__(self, client: LLMClient):
        self._client = client

    async def generate(
        self,
        articles: list[dict],
        ingestion_date: date | None = None,
    ) -> PodcastScript:
        if ingestion_date is None:
            ingestion_date = date.today()

        date_str = ingestion_date.strftime("%Y년 %m월 %d일")
        script = PodcastScript(date=str(ingestion_date))

        # Split into sections
        db_articles = sorted(
            [a for a in articles if a.get("is_databricks_related")],
            key=lambda x: -x.get("relevance_score", 0),
        )[:5]
        db_urls = {a["url"] for a in db_articles}
        ai_articles = sorted(
            [a for a in articles if a["url"] not in db_urls],
            key=lambda x: -x.get("overall_score", 0),
        )[:10]
        ai_urls = {a["url"] for a in ai_articles}
        other_articles = [
            a for a in articles if a["url"] not in db_urls and a["url"] not in ai_urls
        ][:5]

        # Section 0: Intro (~2분)
        script.turns.extend(
            await self._generate_intro(date_str, articles[:5])
        )

        # Section 1: AI 핫뉴스 (~15분)
        script.turns.extend(
            await self._generate_section(
                section_name="AI 핫뉴스 TOP 10",
                articles=ai_articles,
                depth="각 기사당 4-6턴. 기술 내용과 업계 의미를 충분히 논의하세요.",
            )
        )

        # Section 2: Databricks (~8분)
        script.turns.extend(
            await self._generate_section(
                section_name="Databricks / Delta Lake 특화 뉴스",
                articles=db_articles,
                depth="각 기사당 6-8턴. 실제 데이터 엔지니어링 활용 맥락을 포함해 심화 논의하세요.",
            )
        )

        # Section 3: 기타 + 아웃트로 (~5분)
        script.turns.extend(
            await self._generate_outro(other_articles, date_str)
        )

        logger.info(
            "script_generated",
            turns=len(script.turns),
            chars=script.total_chars,
            estimated_minutes=script.estimated_minutes,
        )
        return script

    async def _generate_intro(
        self, date_str: str, top_articles: list[dict]
    ) -> list[DialogueTurn]:
        top_titles = "\n".join(f"- {a['title']}" for a in top_articles)
        prompt = f"""오늘은 {date_str}입니다. 오늘의 주요 기사:
{top_titles}

델타 다이제스트 팟캐스트의 인트로를 작성하세요.
- 두 진행자가 인사하고 오늘 다룰 주요 내용을 자연스럽게 예고한다
- 약 2분 분량, 10-14 대화 턴

{_CHARACTER_BRIEF}

{_JSON_FORMAT}"""
        return await self._call_and_parse(prompt, context="intro")

    async def _generate_section(
        self,
        section_name: str,
        articles: list[dict],
        depth: str,
    ) -> list[DialogueTurn]:
        articles_text = self._format_articles(articles)
        prompt = f"""## {section_name} 섹션

다음 기사들에 대해 두 진행자가 대화하는 팟캐스트 스크립트를 작성하세요.
{depth}

기사 목록:
{articles_text}

{_CHARACTER_BRIEF}

{_JSON_FORMAT}"""
        return await self._call_and_parse(prompt, context=section_name)

    async def _generate_outro(
        self, other_articles: list[dict], date_str: str
    ) -> list[DialogueTurn]:
        articles_text = self._format_articles(other_articles)
        prompt = f"""## 기타 뉴스 + 아웃트로

1. 아래 기사들을 빠르게 언급하세요 (기사당 2-3턴):
{articles_text}

2. 오늘 방송 마무리:
- 오늘의 한 줄 정리 (각자 한 마디씩)
- 청취자 감사 인사, 다음 방송 예고

{_CHARACTER_BRIEF}

{_JSON_FORMAT}"""
        return await self._call_and_parse(prompt, context="outro")

    def _format_articles(self, articles: list[dict]) -> str:
        lines = []
        for i, a in enumerate(articles, 1):
            summary = a.get("full_summary") or a.get("one_line_summary", "")
            lines.append(
                f"{i}. 제목: {a['title']}\n"
                f"   출처: {a.get('source_name', '')}\n"
                f"   요약: {str(summary)[:300]}"
            )
        return "\n\n".join(lines)

    async def _call_and_parse(self, prompt: str, context: str) -> list[DialogueTurn]:
        system = "당신은 한국어 팟캐스트 스크립트 작가입니다. 반드시 유효한 JSON 배열만 반환하세요."
        try:
            resp = await self._client.generate(
                prompt=prompt,
                system=system,
                temperature=0.7,
                max_tokens=8000,
            )
            text = resp.content.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                logger.error("script_no_json_array", context=context, preview=text[:200])
                return []

            turns_data = json.loads(text[start:end])
            return [
                DialogueTurn(
                    speaker=t.get("speaker", HOST_A),
                    text=t.get("text", ""),
                    pause_after_ms=int(t.get("pause_after_ms", 400)),
                )
                for t in turns_data
                if isinstance(t, dict) and t.get("text")
            ]
        except Exception as e:
            logger.error("script_generation_failed", context=context, error=str(e))
            return []
