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
