# Phase 4: 대화형 팟캐스트 파이프라인 설계

**날짜**: 2026-03-06
**상태**: 승인됨
**목표**: delta-digest 다이제스트를 두 진행자가 대화하는 30분 팟캐스트 MP3로 자동 생성

---

## 배경

NotebookLM 스타일의 대화형 팟캐스트. 단순 TTS가 아니라 두 캐릭터가 기사에 대해
실제로 대화하는 형식으로, 스크립트 품질이 핵심.

---

## 캐릭터 설정

| 캐릭터 | 역할 | 목소리 | 성격 |
|--------|------|--------|------|
| 소희 (So-hee) | 메인 앵커 / 설명 담당 | ko-KR-SunHiNeural (여성) | 데이터 엔지니어링 5년차, 논리적이고 명확한 설명 |
| 도현 (Do-hyun) | 반응 / 질문 담당 | ko-KR-InJoonNeural (남성) | ML 연구 배경, 트렌드에 민감, 직관적 반응 |

---

## 팟캐스트 구조 (30분)

```
[섹션 0] 인트로                    2분
  - 날짜, 오늘의 핵심 이슈 예고
  - 두 진행자 가벼운 바랜터

[섹션 1] AI 핫뉴스 TOP 10         15분
  - 기사당 ~1.5분 대화
  - 기술 설명 + 의미 논의 + 반응

[섹션 2] Databricks / Delta Lake   8분
  - TOP 5 기사, 더 심화된 논의
  - 실제 활용 맥락 포함

[섹션 3] 기타 뉴스 + 아웃트로      5분
  - TOP 5 빠른 언급 (기사당 ~30초)
  - 오늘의 한 줄 정리 + 마무리 인사
```

---

## 아키텍처

```
Gold Layer 데이터 (20 기사 + 요약)
           │
           ▼
   ScriptWriter (src/agents/scriptwriter.py)
   ├── generate_intro()       → Gemini 호출 1
   ├── generate_main_section() → Gemini 호출 2 (AI 핫뉴스 10건)
   ├── generate_db_section()   → Gemini 호출 3 (Databricks 5건)
   └── generate_outro()        → Gemini 호출 4 (기타 5건 + 아웃트로)
           │
           ▼ List[DialogueTurn]
           │  [{speaker: str, text: str, pause_after_ms: int}]
           │
   PodcastProducer (src/output/podcast_producer.py)
   ├── _generate_audio_clip()  → edge-tts 비동기
   ├── _merge_clips()          → pydub AudioSegment
   └── produce()               → outputs/podcasts/YYYY-MM-DD-podcast.mp3
                                  outputs/podcasts/YYYY-MM-DD-script.json
```

---

## 데이터 모델

```python
@dataclass
class DialogueTurn:
    speaker: str          # "소희" | "도현"
    text: str             # 대사
    pause_after_ms: int   # 다음 대사 전 침묵 (ms)

@dataclass
class PodcastScript:
    date: str
    turns: list[DialogueTurn]
    total_chars: int
    estimated_minutes: float
```

---

## 스크립트 생성 전략 (접근 B: 섹션별 분리)

섹션별로 Gemini를 호출하여 토큰 한계를 우회하고 섹션 성격에 맞는 프롬프트 조율.

### 프롬프트 설계 원칙

1. **캐릭터 일관성**: 매 호출에 캐릭터 설명 포함
2. **자연스러운 대화**: 상대방 말을 받아서 이어지도록 유도
3. **출력 형식**: JSON array of `{speaker, text, pause_after_ms}`
4. **적절한 깊이**:
   - AI 핫뉴스: 기사당 4-6 대화 턴
   - Databricks: 기사당 6-8 대화 턴 (더 심화)
   - 기타: 기사당 2-3 대화 턴 (빠르게)

---

## TTS & 오디오 합성

- **엔진**: `edge-tts` (무료, 별도 API 키 불필요)
- **소희**: `ko-KR-SunHiNeural`
- **도현**: `ko-KR-InJoonNeural`
- **처리**: 각 대화 턴을 임시 MP3로 변환 후 `pydub`으로 합산
- **포즈**: `pause_after_ms`만큼 무음 삽입

```python
# 예상 처리 시간 (ARM64 Oracle Cloud)
TTS 생성:  ~5-10분 (100-150개 클립 × 약 3-5초)
오디오 합산: ~1분
총계:       ~10-15분
```

---

## 출력 파일

```
outputs/
└── podcasts/
    ├── 2026-03-06-podcast.mp3    ← 최종 오디오 (~30분)
    └── 2026-03-06-script.json   ← 전체 대화 스크립트 (검토/편집용)
```

---

## 비용

| 항목 | 비용 |
|------|------|
| Gemini 스크립트 생성 (4회) | $0 (Free tier: 1500 req/day) |
| edge-tts | $0 (무료 서비스) |
| pydub/ffmpeg 로컬 처리 | $0 |
| **합계** | **$0** |

---

## run_daily.py 통합

```python
# Step 7: Podcast (Phase 4)
logger.info("step7_podcast")
from src.agents.scriptwriter import ScriptWriter
from src.output.podcast_producer import PodcastProducer

writer = ScriptWriter(gemini_client)
script = await writer.generate(digest_articles, ingestion_date)

producer = PodcastProducer()
audio_path = await producer.produce(script, ingestion_date)
print(f"🎙️ Podcast saved: {audio_path}")
```

---

## 의존성 추가

```toml
edge-tts = "*"
pydub = "*"
```

시스템: `ffmpeg` 설치 필요 (ARM64: `sudo apt install ffmpeg`)

---

## 향후 확장

- BGM/효과음 레이어 추가
- 섹션 간 징글 삽입
- 속도 조절 파라미터
