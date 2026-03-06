# Phase 4: 대화형 팟캐스트 파이프라인 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gold Layer의 20개 기사 데이터를 소희+도현 두 진행자가 대화하는 ~30분 한국어 팟캐스트 MP3로 자동 생성한다.

**Architecture:** ScriptWriter(Gemini)로 4개 섹션 대화 스크립트를 순차 생성 → PodcastProducer(edge-tts)로 각 대사를 MP3 클립으로 변환 → pydub으로 전체 합산.

**Tech Stack:** `edge-tts`, `pydub`, `ffmpeg` (시스템), Google Gemini 2.5 Flash (기존 GeminiClient 재사용)

---

## Task 1: 의존성 추가 + config 확장

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/common/config.py`

**Step 1: 의존성 설치**

```bash
uv add edge-tts pydub
```

Expected: `pyproject.toml`의 `[project.dependencies]`에 `edge-tts`, `pydub` 추가됨.

**Step 2: `podcasts_path` property를 Settings에 추가**

`src/common/config.py` 의 `digests_path` 아래에 추가:

```python
@property
def podcasts_path(self) -> Path:
    return self.output_dir / "podcasts"
```

**Step 3: 설치 확인**

```bash
uv run python -c "import edge_tts; import pydub; print('OK')"
```

Expected: `OK`

**Step 4: ffmpeg 확인 (로컬 Mac)**

```bash
which ffmpeg || brew install ffmpeg
```

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/common/config.py
git commit -m "feat: add edge-tts, pydub deps + podcasts_path config"
```

---

## Task 2: DialogueTurn + PodcastScript 데이터 모델 + ScriptWriter 골격

**Files:**
- Create: `src/agents/scriptwriter.py`
- Create: `tests/test_agents/test_scriptwriter.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_agents/test_scriptwriter.py`:

```python
"""Tests for ScriptWriter dialogue generation."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.scriptwriter import (
    DialogueTurn,
    PodcastScript,
    ScriptWriter,
    HOST_A,
    HOST_B,
)


def test_dialogue_turn_defaults():
    turn = DialogueTurn(speaker="소희", text="안녕하세요")
    assert turn.speaker == "소희"
    assert turn.text == "안녕하세요"
    assert turn.pause_after_ms == 400


def test_podcast_script_estimated_minutes():
    # 250 chars/min → 500 chars = 2.0 min
    turns = [DialogueTurn(speaker="소희", text="가" * 500)]
    script = PodcastScript(date="2026-03-06", turns=turns)
    assert script.total_chars == 500
    assert script.estimated_minutes == 2.0


def test_podcast_script_to_json():
    turns = [
        DialogueTurn(speaker="소희", text="안녕하세요", pause_after_ms=300),
        DialogueTurn(speaker="도현", text="반갑습니다", pause_after_ms=500),
    ]
    script = PodcastScript(date="2026-03-06", turns=turns)
    result = script.to_json()
    assert len(result) == 2
    assert result[0] == {"speaker": "소희", "text": "안녕하세요", "pause_after_ms": 300}
    assert result[1]["speaker"] == "도현"


@pytest.mark.asyncio
async def test_scriptwriter_returns_dialogue_turns():
    """ScriptWriter.generate() should return a PodcastScript with turns."""
    # Mock Gemini response: JSON array of dialogue turns
    mock_response = MagicMock()
    mock_response.content = '''[
        {"speaker": "소희", "text": "안녕하세요, 델타 다이제스트입니다.", "pause_after_ms": 400},
        {"speaker": "도현", "text": "오늘도 재미있는 뉴스가 많네요!", "pause_after_ms": 300}
    ]'''

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    articles = [
        {
            "url": "https://example.com/1",
            "title": "FlashAttention-4 출시",
            "full_summary": "새로운 어텐션 메커니즘이다.",
            "one_line_summary": "빠른 어텐션",
            "source_name": "ArXiv",
            "is_databricks_related": False,
            "overall_score": 8.5,
        }
    ]

    writer = ScriptWriter(mock_client)
    script = await writer.generate(articles)

    assert isinstance(script, PodcastScript)
    assert len(script.turns) > 0
    assert all(isinstance(t, DialogueTurn) for t in script.turns)
    assert all(t.speaker in [HOST_A, HOST_B] for t in script.turns)


@pytest.mark.asyncio
async def test_scriptwriter_handles_empty_response():
    """ScriptWriter should return empty turns (not crash) on bad Gemini response."""
    mock_response = MagicMock()
    mock_response.content = "죄송합니다, 오류가 발생했습니다."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    writer = ScriptWriter(mock_client)
    script = await writer.generate([])

    assert isinstance(script, PodcastScript)
    # May have 0 turns, but should not raise
    assert isinstance(script.turns, list)
```

**Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_agents/test_scriptwriter.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.agents.scriptwriter'`

**Step 3: `src/agents/scriptwriter.py` 구현**

```python
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
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_agents/test_scriptwriter.py -v
```

Expected: 5개 모두 PASS

**Step 5: Commit**

```bash
git add src/agents/scriptwriter.py tests/test_agents/test_scriptwriter.py
git commit -m "feat: add ScriptWriter for dialogue podcast script generation"
```

---

## Task 3: PodcastProducer (edge-tts + pydub 오디오 합성)

**Files:**
- Create: `src/output/podcast_producer.py`
- Create: `tests/test_output/test_podcast_producer.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_output/test_podcast_producer.py`:

```python
"""Tests for PodcastProducer audio synthesis."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.scriptwriter import DialogueTurn, PodcastScript
from src.output.podcast_producer import PodcastProducer, VOICE_MAP


def test_voice_map_has_both_hosts():
    assert "소희" in VOICE_MAP
    assert "도현" in VOICE_MAP
    assert VOICE_MAP["소희"] == "ko-KR-SunHiNeural"
    assert VOICE_MAP["도현"] == "ko-KR-InJoonNeural"


def test_podcast_producer_saves_script_json(tmp_path):
    """PodcastProducer should save script JSON before audio generation."""
    from datetime import date

    script = PodcastScript(
        date="2026-03-06",
        turns=[
            DialogueTurn(speaker="소희", text="안녕하세요", pause_after_ms=400),
            DialogueTurn(speaker="도현", text="반갑습니다", pause_after_ms=300),
        ],
    )

    producer = PodcastProducer(output_dir=tmp_path)

    with patch.object(producer, "_generate_audio", new=AsyncMock()):
        import asyncio
        asyncio.run(producer.produce(script, date(2026, 3, 6)))

    script_file = tmp_path / "2026-03-06-script.json"
    assert script_file.exists()
    data = json.loads(script_file.read_text())
    assert len(data) == 2
    assert data[0]["speaker"] == "소희"


@pytest.mark.asyncio
async def test_tts_to_file_uses_correct_voice(tmp_path):
    """_tts_to_file should call edge_tts.Communicate with correct voice."""
    producer = PodcastProducer(output_dir=tmp_path)
    output = tmp_path / "test.mp3"

    mock_communicate = MagicMock()
    mock_communicate.save = AsyncMock()

    with patch("src.output.podcast_producer.edge_tts") as mock_edge_tts:
        mock_edge_tts.Communicate.return_value = mock_communicate
        await producer._tts_to_file("소희", "테스트 대사입니다.", output)

    mock_edge_tts.Communicate.assert_called_once_with("테스트 대사입니다.", "ko-KR-SunHiNeural")
    mock_communicate.save.assert_called_once_with(str(output))
```

**Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_output/test_podcast_producer.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.output.podcast_producer'`

**Step 3: `src/output/podcast_producer.py` 구현**

```python
"""Convert PodcastScript to MP3 using edge-tts and pydub."""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import structlog

from src.agents.scriptwriter import VOICE_A, VOICE_B, HOST_A, DialogueTurn, PodcastScript
from src.common.config import settings

logger = structlog.get_logger(__name__)

VOICE_MAP: dict[str, str] = {
    "소희": VOICE_A,  # ko-KR-SunHiNeural
    "도현": VOICE_B,  # ko-KR-InJoonNeural
}


class PodcastProducer:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or settings.podcasts_path

    async def produce(
        self,
        script: PodcastScript,
        ingestion_date: date | None = None,
    ) -> Path:
        if ingestion_date is None:
            ingestion_date = date.today()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        date_str = ingestion_date.strftime("%Y-%m-%d")

        # Always save script JSON first (useful even if audio fails)
        script_path = self.output_dir / f"{date_str}-script.json"
        script_path.write_text(
            json.dumps(script.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("script_saved", path=str(script_path), turns=len(script.turns))

        # Generate MP3
        audio_path = self.output_dir / f"{date_str}-podcast.mp3"
        await self._generate_audio(script.turns, audio_path)
        return audio_path

    async def _generate_audio(self, turns: list[DialogueTurn], output_path: Path) -> None:
        import edge_tts  # noqa: F401 — imported for mocking in tests
        from pydub import AudioSegment

        total = len(turns)
        clips: list[AudioSegment] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            for i, turn in enumerate(turns):
                logger.info(
                    "tts_progress",
                    index=i + 1,
                    total=total,
                    speaker=turn.speaker,
                    chars=len(turn.text),
                )
                clip_path = tmpdir_path / f"clip_{i:04d}.mp3"
                await self._tts_to_file(turn.speaker, turn.text, clip_path)

                clips.append(AudioSegment.from_mp3(clip_path))

                if turn.pause_after_ms > 0:
                    clips.append(AudioSegment.silent(duration=turn.pause_after_ms))

            logger.info("merging_clips", count=len(clips))
            combined: AudioSegment = sum(clips[1:], clips[0]) if clips else AudioSegment.empty()
            combined.export(str(output_path), format="mp3", bitrate="128k")
            duration_min = round(len(combined) / 60000, 1)

        logger.info("podcast_produced", path=str(output_path), duration_min=duration_min)

    async def _tts_to_file(self, speaker: str, text: str, output_path: Path) -> None:
        import edge_tts
        voice = VOICE_MAP.get(speaker, VOICE_A)
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_output/test_podcast_producer.py -v
```

Expected: 3개 모두 PASS

**Step 5: Commit**

```bash
git add src/output/podcast_producer.py tests/test_output/test_podcast_producer.py
git commit -m "feat: add PodcastProducer for edge-tts audio synthesis"
```

---

## Task 4: run_daily.py에 Step 7 통합

**Files:**
- Modify: `src/run_daily.py`

**Step 1: Step 7 블록을 `run_pipeline()` 함수의 Step 6 다이제스트 저장 뒤에 추가**

`src/run_daily.py` 의 `output_path = write_digest(...)` 줄 아래, `logger.info("pipeline_complete", ...)` 위에 삽입:

```python
    # ── Step 7: Podcast ──────────────────────────────────────────────────────
    logger.info("step7_podcast")
    if not use_mock_scores and health.get("gemini"):
        from src.agents.scriptwriter import ScriptWriter
        from src.output.podcast_producer import PodcastProducer

        gemini_for_script = router.get_client("scriptwriting")
        writer = ScriptWriter(gemini_for_script)
        script = await writer.generate(digest_articles, ingestion_date)

        producer = PodcastProducer()
        podcast_path = await producer.produce(script, ingestion_date)
        print(f"\n🎙️  Podcast saved: {podcast_path}  ({script.estimated_minutes} min)")
    else:
        logger.info("podcast_skipped", reason="mock_mode_or_gemini_unavailable")
```

> **주의**: `health` 변수는 `_run_ai_pipeline` 내부에 있으므로 스코프 밖임.
> `health` dict를 `_run_ai_pipeline` 반환값에 추가하거나, Step 7에서 `router.check_all()`을 재호출하지 말고 아래처럼 처리:

실제로 `run_pipeline()` 함수를 보면 `health`가 `_run_ai_pipeline` 내부에 있음. Step 7을 `use_mock_scores` 조건으로만 가드하고, Gemini 미설정 시 자연스럽게 `generate()`가 빈 turns를 반환하도록 처리:

```python
    # ── Step 7: Podcast ──────────────────────────────────────────────────────
    logger.info("step7_podcast")
    if use_mock_scores:
        logger.info("podcast_skipped", reason="mock_mode")
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
```

**Step 2: `--no-podcast` 플래그 지원 (선택적, 빠른 테스트용)**

`run_daily.py` 하단의 `if __name__ == "__main__":` 블록:

```python
if __name__ == "__main__":
    mock = "--mock" in sys.argv
    no_podcast = "--no-podcast" in sys.argv
    asyncio.run(run_pipeline(use_mock_scores=mock, skip_podcast=no_podcast))
```

`run_pipeline` 시그니처에 `skip_podcast: bool = False` 파라미터 추가, Step 7 조건에 `or skip_podcast` 추가.

**Step 3: import 누락 확인**

```bash
uv run python -c "from src.run_daily import run_pipeline; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add src/run_daily.py
git commit -m "feat: integrate podcast generation as Step 7 in run_daily pipeline"
```

---

## Task 5: 빠른 통합 테스트 (mock 스크립트로 오디오 생성 확인)

**Files:**
- Create: `scripts/test_podcast.py`

**Step 1: 테스트 스크립트 작성**

`scripts/test_podcast.py`:

```python
"""Quick integration test: generate podcast with a tiny mock script."""
import asyncio
from datetime import date
from pathlib import Path

from src.agents.scriptwriter import DialogueTurn, PodcastScript
from src.output.podcast_producer import PodcastProducer


async def main():
    script = PodcastScript(
        date="2026-03-06",
        turns=[
            DialogueTurn(speaker="소희", text="안녕하세요, 델타 다이제스트 팟캐스트입니다.", pause_after_ms=500),
            DialogueTurn(speaker="도현", text="오늘도 AI 업계 핫뉴스 같이 살펴볼게요!", pause_after_ms=400),
            DialogueTurn(speaker="소희", text="오늘의 첫 번째 뉴스는 FlashAttention-4 출시입니다.", pause_after_ms=300),
            DialogueTurn(speaker="도현", text="이번엔 B200 GPU에서 성능이 크게 향상됐다고 하죠?", pause_after_ms=400),
            DialogueTurn(speaker="소희", text="맞아요, cuDNN 대비 1.3배, Triton 대비 2.7배라고 합니다.", pause_after_ms=800),
            DialogueTurn(speaker="도현", text="오늘도 들어주셔서 감사합니다!", pause_after_ms=500),
        ],
    )

    output_dir = Path("outputs/podcasts")
    producer = PodcastProducer(output_dir=output_dir)
    path = await producer.produce(script, date(2026, 3, 6))
    print(f"✅ 테스트 팟캐스트 저장: {path}")
    print(f"   예상 길이: {script.estimated_minutes}분")
    print(f"   실제 파일 크기: {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: 실행**

```bash
uv run python scripts/test_podcast.py
```

Expected 출력:
```
✅ 테스트 팟캐스트 저장: outputs/podcasts/2026-03-06-podcast.mp3
   예상 길이: 0.5분
   실제 파일 크기: 약 200-500 KB
```

MP3 파일을 재생해서 소희/도현 목소리가 교대로 들리는지 확인.

**Step 3: Commit**

```bash
git add scripts/test_podcast.py
git commit -m "test: add podcast integration smoke test script"
```

---

## Task 6: Gemini 실제 스크립트 생성 테스트 (실제 API 호출)

**Step 1: 오늘의 다이제스트 데이터로 실제 스크립트 생성**

```bash
uv run python -c "
import asyncio, json
from src.agents.llm_client import GeminiClient
from src.agents.scriptwriter import ScriptWriter
from src.common.config import settings

# 오늘 digest 샘플 (gold 데이터 없으면 mock 사용)
articles = [
    {
        'url': 'https://arxiv.org/abs/2501.12345',
        'title': 'FlashAttention-4: 하드웨어 인식 알고리즘으로 어텐션 가속화',
        'full_summary': 'FlashAttention-4는 Blackwell GPU에서 어텐션 연산을 최적화한다.',
        'one_line_summary': 'FlashAttention 최신 버전',
        'source_name': 'ArXiv',
        'is_databricks_related': False,
        'overall_score': 8.5,
        'relevance_score': 3.0,
    },
    {
        'url': 'https://databricks.com/blog/delta-4',
        'title': 'Delta Lake 4.0 정식 출시',
        'full_summary': 'Delta Lake 4.0이 액체 클러스터링과 개선된 CDC를 제공한다.',
        'one_line_summary': 'Delta Lake 4.0 출시',
        'source_name': 'Databricks Blog',
        'is_databricks_related': True,
        'overall_score': 9.0,
        'relevance_score': 9.5,
    },
]

async def test():
    client = GeminiClient(api_key=settings.gemini_api_key)
    writer = ScriptWriter(client)
    script = await writer.generate(articles)
    print(f'턴 수: {len(script.turns)}')
    print(f'예상 길이: {script.estimated_minutes}분')
    for t in script.turns[:4]:
        print(f'[{t.speaker}] {t.text[:80]}')

asyncio.run(test())
"
```

Expected: 실제 Gemini가 생성한 대화 출력

**Step 2: 전체 파이프라인 실행 (--no-podcast 없이)**

```bash
uv run python src/run_daily.py --mock
# mock 모드는 podcast 스킵됨 (정상)

# 실제 Gemini 스크립트 생성 포함:
uv run python src/run_daily.py
```

**Step 3: 최종 커밋 + Push**

```bash
git add -A
git commit -m "feat: Phase 4 complete - conversational podcast pipeline"
git push origin main
```

---

## 요약

| Task | 파일 | 핵심 |
|------|------|------|
| 1 | `pyproject.toml`, `config.py` | edge-tts, pydub 의존성 + podcasts_path |
| 2 | `src/agents/scriptwriter.py` | Gemini로 소희+도현 대화 스크립트 생성 |
| 3 | `src/output/podcast_producer.py` | edge-tts TTS + pydub 오디오 합산 |
| 4 | `src/run_daily.py` | Step 7으로 파이프라인 통합 |
| 5 | `scripts/test_podcast.py` | Mock 스크립트로 TTS 동작 검증 |
| 6 | — | 실제 API로 end-to-end 검증 |

**완료 기준**: `outputs/podcasts/YYYY-MM-DD-podcast.mp3`가 생성되고, 재생 시 소희+도현이 교대로 AI/Databricks 뉴스를 논의하는 한국어 음성이 들림.
