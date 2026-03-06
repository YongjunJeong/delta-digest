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
    assert isinstance(script.turns, list)
