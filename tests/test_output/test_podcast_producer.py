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
