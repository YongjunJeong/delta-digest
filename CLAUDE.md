# CLAUDE.md — delta-digest 프로젝트 개발 가이드

## 프로젝트 개요

**delta-digest**: AI/Databricks 기술 동향을 매일 자동 수집·정리하는 개인 지식 시스템
- Databricks SE 포지션 포트폴리오 프로젝트
- Delta Lake Medallion Architecture (Bronze/Silver/Gold) 직접 구현이 핵심
- **비용 $0 운영**: 로컬 LLM(Ollama) + Gemini Free API 하이브리드

## 현재 스코프: Phase 1-3 (수집 → 처리 → 다이제스트 출력)

Phase 4 (TTS), Phase 5 (RAG Q&A)는 1-3 완료 후 진행.

---

## 인프라 환경

- **서버**: Oracle Cloud ARM (VM.Standard.A1.Flex, aarch64, Ubuntu 22.04)
- **리소스**: 4 OCPU, 24GB RAM, Docker 설치 완료
- **Python**: 3.11+ (uv 패키지 매니저)
- **Java**: OpenJDK 11+ (PySpark 필수)
- **데이터 처리**: PySpark 3.5 (local mode) + delta-spark 3.2
  - ⚠️ ARM에서 PySpark 설치 실패 시 → DuckDB + deltalake(delta-rs) 대안 전환
- **네트워크**: 외부 API 호출 가능 (RSS, ArXiv, HN, GitHub, Gemini API)

### 메모리 분배 (24GB)

```
OS + Docker:      ~2GB
PySpark driver:    4GB
Ollama (Qwen 7B):  5-6GB
Python 프로세스:   ~2GB
여유:             ~10GB
합계:             ~24GB ✓
```

⚠️ **중요**: PySpark와 Ollama가 동시에 메모리를 많이 쓰므로,
파이프라인 실행 시 순차 처리 (Spark 작업 → Ollama 스코어링 → Gemini 요약).
필요 시 Spark를 stop() 후 Ollama 실행.

---

## LLM 전략: 하이브리드 (비용 $0)

### 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                  LLMClient (ABC)                     │
│                                                      │
│  ┌─────────────────┐    ┌─────────────────────────┐ │
│  │  OllamaClient   │    │    GeminiClient          │ │
│  │  (localhost)     │    │    (Free API)            │ │
│  │                  │    │                          │ │
│  │  모델: Qwen 2.5  │    │  모델: Gemini 2.0 Flash  │ │
│  │  용도: 스코어링   │    │  용도: 요약, 스크립트     │ │
│  │  ~100건/일       │    │  ~25건/일               │ │
│  │  비용: $0        │    │  비용: $0               │ │
│  └─────────────────┘    └─────────────────────────┘ │
│                                                      │
│  향후 교체 가능: AnthropicClient, DatabricksClient   │
└─────────────────────────────────────────────────────┘
```

### 태스크별 라우팅

| 태스크 | LLM | 이유 |
|--------|-----|------|
| 중요도 스코어링 (100건/일) | Ollama (Qwen 2.5 7B Q4) | 단순 JSON 출력, 로컬 처리 |
| 기사 요약 (20건/일) | Gemini 2.0 Flash | 한국어 품질, 긴 컨텍스트 |
| 스크립트 작성 (1건/일) | Gemini 2.0 Flash | 창작 품질 필요 |

### Ollama 설정

```bash
# ARM64 네이티브 지원
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:7b

# 동작 확인
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"test"}'
```

### Gemini API 설정

```bash
# Google AI Studio에서 무료 API 키 발급: https://aistudio.google.com/apikey
# .env에: DIGEST_GEMINI_API_KEY=AIza...
# 무료 한도: 1500 req/day → 우리 ~25 req/day로 충분
```

### LLM 클라이언트 추상화

```python
# src/agents/llm_client.py

@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float

class LLMClient(ABC):
    async def generate(self, prompt, system="", temperature=0.3, max_tokens=1000) -> LLMResponse: ...
    async def generate_json(self, prompt, system="", temperature=0.1) -> dict: ...

class OllamaClient(LLMClient):
    # httpx → localhost:11434/api/generate
    # format="json" 으로 JSON 모드 강제
    # timeout 120초 (ARM 느림 대응)
    # 재시도 3회 + 폴백

class GeminiClient(LLMClient):
    # google-generativeai SDK
    # responseMimeType="application/json"
    # 재시도 3회 (429 대응)
```

```python
# src/agents/router.py
class LLMRouter:
    def get_client(self, task: str) -> LLMClient:
        return {"scoring": self.ollama, "summarization": self.gemini, "scriptwriting": self.gemini}[task]
```

---

## 코딩 컨벤션

### 언어
- 코드/주석/변수명/함수명: **영어**
- 다이제스트 출력/프롬프트: **한국어**
- README: **영어** (글로벌 포트폴리오)

### Python 스타일
- Type hints 필수
- async/await: 수집 레이어, LLM 호출
- Pydantic BaseModel: 데이터 모델, 설정
- structlog: 구조화 로깅
- pytest + pytest-asyncio
- ruff formatter, max line 100

### 패키지
```bash
uv add pyspark==3.5.4 delta-spark==3.2.1
uv add httpx beautifulsoup4 feedparser
uv add pydantic-settings structlog jinja2 pyyaml
uv add google-generativeai
uv add --dev pytest pytest-asyncio ruff
```

---

## 디렉토리 구조

```
delta-digest/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── ingestion/          # 수집
│   │   ├── base.py         # BaseCollector ABC + RawArticle
│   │   ├── rss_collector.py
│   │   ├── arxiv_collector.py
│   │   ├── hn_collector.py
│   │   ├── github_collector.py
│   │   ├── run_all.py
│   │   └── sources.yaml
│   ├── pipeline/           # Spark + Delta Lake
│   │   ├── spark_session.py
│   │   ├── schemas.py
│   │   ├── bronze.py
│   │   ├── silver.py
│   │   └── gold.py
│   ├── agents/             # LLM 에이전트
│   │   ├── llm_client.py   # LLMClient ABC + Ollama/Gemini
│   │   ├── router.py       # 태스크별 라우팅
│   │   ├── scorer.py       # → Ollama
│   │   ├── summarizer.py   # → Gemini
│   │   └── scriptwriter.py # → Gemini
│   ├── output/
│   │   ├── markdown_writer.py
│   │   └── templates/digest.md.j2
│   └── common/
│       ├── config.py
│       ├── logging.py
│       └── models.py
├── data/{bronze,silver,gold}/
├── outputs/{digests,logs}/
├── tests/
│   ├── test_ingestion/
│   ├── test_pipeline/
│   ├── test_agents/
│   └── fixtures/
└── scripts/
    ├── run_daily.sh
    ├── init_delta.py
    └── setup_ollama.sh
```

---

## 세션별 개발 계획

### 세션 1: 초기화 + 인프라 (30분)
- uv init, 의존성, 디렉토리 구조
- config.py (Settings), logging.py
- SparkSession + Delta Lake 테스트
- Ollama 설치 + qwen2.5:7b 다운로드
- Gemini API 키 테스트

### 세션 2: 수집 레이어 (1-2시간)
- base.py (RawArticle + BaseCollector)
- rss_collector.py → hn_collector.py → arxiv_collector.py → github_collector.py
- run_all.py (전체 수집 오케스트레이션)
- 테스트

### 세션 3: Bronze 파이프라인 (1시간)
- schemas.py (BRONZE_SCHEMA)
- bronze.py (MERGE upsert)
- Delta Lake 기능 검증 (history, time travel)

### 세션 4: Silver + LLM 클라이언트 (1-2시간)
- silver.py (HTML 정제, 중복 제거)
- llm_client.py (OllamaClient + GeminiClient) ← 핵심
- router.py
- 각 클라이언트 테스트

### 세션 5: Gold + AI 에이전트 (1-2시간)
- scorer.py (Ollama 스코어링)
- summarizer.py (Gemini 요약)
- gold.py (통합)

### 세션 6: 다이제스트 + 통합 (1-2시간)
- digest.md.j2 템플릿
- markdown_writer.py
- run_daily.sh
- README.md
- 통합 테스트

---

## 환경변수 (.env)

```bash
DIGEST_GEMINI_API_KEY=AIza...
DIGEST_OLLAMA_BASE_URL=http://localhost:11434
DIGEST_OLLAMA_MODEL=qwen2.5:7b
DIGEST_DATA_DIR=./data
DIGEST_OUTPUT_DIR=./outputs
DIGEST_SPARK_DRIVER_MEMORY=4g
DIGEST_SPARK_SHUFFLE_PARTITIONS=4
DIGEST_LOG_LEVEL=INFO
```

---

## 주의사항

1. **PySpark ARM**: 설치 실패 시 → `uv add duckdb deltalake` 전환
2. **Ollama 메모리**: Spark와 동시 실행 OOM 주의. 순차 실행 권장.
3. **Ollama JSON**: Qwen 7B 가끔 잘못된 JSON. 3회 재시도 + regex 폴백 + 기본값.
4. **Gemini 429**: exponential backoff (1→2→4초)
5. **ARM 추론 속도**: 건당 20-30초, 100건 스코어링 ~30-50분. 새벽 cron이면 OK.
6. **Delta Lake 경로**: 상대 경로 `data/bronze` 등 사용.
