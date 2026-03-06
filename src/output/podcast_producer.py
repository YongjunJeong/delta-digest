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

try:
    import edge_tts  # noqa: F401
except ImportError:  # pragma: no cover
    edge_tts = None  # type: ignore[assignment]

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
        voice = VOICE_MAP.get(speaker, VOICE_A)
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
