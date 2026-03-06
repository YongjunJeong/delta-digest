# delta-digest 프로젝트 최종 계획서 (v2)

## 프로젝트 요약

| 항목 | 내용 |
|------|------|
| 프로젝트명 | `delta-digest` |
| 목표 | AI/Databricks 기술 동향 자동 수집·정리 시스템 |
| 스코프 | **Phase 1-3** (수집 → 처리 → 다이제스트) |
| 데이터 처리 | **PySpark 우선** (실패 시 DuckDB 전환) |
| LLM 전략 | **하이브리드**: Ollama(로컬) + Gemini Flash(무료 API) |
| 출력 언어 | **한영 혼합** (기술=영어, 설명=한국어) |
| 인프라 | Oracle Cloud ARM (4 OCPU, 24GB RAM) |
| 월 비용 | **$0** (Oracle Free Tier + 로컬 LLM + Gemini Free) |
| 예상 개발기간 | 5-8일 (Claude Code 세션 6회) |

---

## 핵심 설계 결정

### 1. LLM 하이브리드 (비용 $0)

```
┌────────────────────────┬──────────────┬─────────────────┐
│ 태스크                  │ LLM          │ 이유            │
├────────────────────────┼──────────────┼─────────────────┤
│ 스코어링 (~100건/일)    │ Ollama       │ 단순 JSON, 대량 │
│                        │ Qwen 2.5 7B  │ 로컬=무제한     │
├────────────────────────┼──────────────┼─────────────────┤
│ 요약 (~20건/일)         │ Gemini Flash │ 한국어 품질     │
│                        │ (Free API)   │ 긴 컨텍스트     │
├────────────────────────┼──────────────┼─────────────────┤
│ 스크립트 (1건/일)       │ Gemini Flash │ 창작 품질       │
└────────────────────────┴──────────────┴─────────────────┘
```

**왜 하이브리드인가:**
- 스코어링은 JSON 출력만 하면 되는 단순 작업 → 7B 모델로 충분
- 요약/스크립트는 한국어 품질이 중요 → Gemini Flash가 7B보다 월등
- LLMClient 추상화로 향후 Claude/Databricks Foundation Model API로 교체 1줄

**Databricks 면접 어필:**
> "태스크 복잡도에 따라 로컬 LLM과 클라우드 API를 분리 배치하는
> 비용 최적화 설계를 직접 구현했습니다. 추상화 레이어 덕분에
> Databricks Foundation Model API로도 즉시 전환 가능합니다."

### 2. PySpark 먼저 (Databricks 어필)

Databricks 핵심 엔진이 Spark이므로, PySpark local mode 경험이 직접적 어필.
ARM 설치 실패 시에만 DuckDB 전환.

### 3. Phase 1-3 먼저 (최소 완성품)

Phase 1-3만으로도 GitHub에 올릴 수 있는 완성된 프로젝트.
README + 실행 결과 스크린샷 + 아키텍처 다이어그램으로 면접 데모 가능.

---

## 아키텍처

```
                     Phase 1                    Phase 2                Phase 3
              ┌─────────────────┐      ┌──────────────────┐    ┌──────────────┐
              │   Ingestion     │      │   Processing     │    │   Output     │
              │                 │      │                  │    │              │
  RSS ────────┤                 │      │  Silver Layer    │    │  Markdown    │
  ArXiv ──────┤  Async HTTP     │─────→│  ・HTML 정제     │───→│  Digest      │
  HN ─────────┤  Collectors     │      │  ・중복 제거     │    │  (일일)      │
  GitHub ─────┤                 │      │                  │    └──────────────┘
              └───────┬─────────┘      │  Gold Layer      │
                      │                │  ・Ollama 스코어링│
                      ▼                │  ・Gemini 요약   │
              ┌─────────────────┐      │  ・Top 20 선별   │
              │  Bronze Layer   │      └──────────────────┘
              │  (Delta Lake)   │
              │  ・MERGE upsert │      ┌──────────────────┐
              │  ・날짜 파티션    │      │  LLMClient ABC   │
              └─────────────────┘      │  ├─ Ollama       │
                                       │  ├─ Gemini       │
                                       │  └─ (확장 가능)  │
                                       └──────────────────┘
```

---

## 리소스 계획

### 메모리 (24GB RAM)

```
컴포넌트         사용량    실행 시점
───────────────────────────────────
OS + Docker      2GB     상시
PySpark driver   4GB     Step 1-3, 5
Ollama Qwen 7B   5-6GB   Step 4 (스코어링)
Python 프로세스   2GB     상시
───────────────────────────────────
최대 동시:       ~14GB   (여유 10GB)
```

**메모리 관리 전략:**
1. 수집 + Bronze + Silver: Spark 사용 (Ollama idle → 자동 언로드)
2. Gold 스코어링: Spark stop() → Ollama 스코어링 (~30-50분)
3. Gold 요약: Gemini API (메모리 무관)
4. Gold 저장: Spark 재시작 → 결과 저장
5. 다이제스트: Jinja2 (경량)

### 처리 시간 (일일 파이프라인)

```
단계                         예상 시간
─────────────────────────────────────
수집 (4개 소스)               ~2-3분
Bronze 저장                   ~1분
Silver 변환                   ~1분
Ollama 스코어링 (100건)       ~30-50분  ← 병목
Gemini 요약 (20건)            ~3-5분
Gold 저장                     ~1분
다이제스트 생성               ~10초
─────────────────────────────────────
합계:                         ~40-60분
```

→ 새벽 5시 cron 실행하면 6시 전에 완료

### 비용

```
항목              월 비용
──────────────────────
Oracle Cloud      $0 (Free Tier)
Ollama            $0 (로컬)
Gemini Flash      $0 (Free Tier: 1500 req/day)
스토리지          $0 (서버 로컬)
──────────────────────
합계:             $0
```

---

## Phase별 상세 계획

### Phase 1: 수집 + Bronze (2-3일)

**세션 1**: 프로젝트 초기화
- uv init, 의존성 설치
- SparkSession + Delta Lake 확장 로딩 테스트
- Ollama 설치 + qwen2.5:7b 다운로드
- Gemini API 키 테스트
- config.py, logging.py

**세션 2**: 수집 레이어
- BaseCollector + RawArticle
- RSS → HN → ArXiv → GitHub 순서
- sources.yaml
- 테스트 (mock HTTP)

**세션 3**: Bronze 파이프라인
- BRONZE_SCHEMA 정의
- MERGE upsert by URL
- Delta Lake 검증: history(), time travel, describe()

### Phase 2: Silver/Gold + AI (2-3일)

**세션 4**: Silver + LLM 클라이언트
- Silver 변환 (HTML 정제, 중복 제거)
- **llm_client.py** (OllamaClient + GeminiClient) ← 가장 중요
- router.py (태스크별 라우팅)
- LLM 클라이언트 테스트

**세션 5**: Gold + AI 에이전트
- scorer.py (Ollama 스코어링, JSON 파싱 + 폴백)
- summarizer.py (Gemini 요약, 한국어)
- gold.py (통합, 메모리 관리)

### Phase 3: 다이제스트 (1-2일)

**세션 6**: 출력 + 통합
- Jinja2 템플릿 (digest.md.j2)
- markdown_writer.py
- run_daily.sh (end-to-end)
- README.md (영어)
- cron 등록

---

## LLM 클라이언트 상세 설계

### OllamaClient (스코어링용)

```python
# 핵심 포인트:
# 1. httpx로 localhost:11434/api/generate 직접 호출
# 2. format="json" → Ollama 내장 JSON mode
# 3. timeout=120 (ARM 7B 느림)
# 4. JSON 파싱 실패 대응:
#    시도 1: json.loads(response)
#    시도 2: regex로 JSON 블록 추출
#    시도 3: 기본 스코어 5.0 반환

# 프롬프트 전략 (Qwen 2.5 최적화):
# - 영어 프롬프트 (Qwen은 영어 지시 따르기가 더 안정적)
# - JSON 스키마를 프롬프트에 명시
# - "Respond ONLY with JSON. No text outside JSON."
# - 출력은 한국어 (one_line_summary, reasoning)
```

### GeminiClient (요약/스크립트용)

```python
# 핵심 포인트:
# 1. google-generativeai SDK 사용
# 2. generation_config에 response_mime_type="application/json"
# 3. system_instruction 지원
# 4. 429 에러: exponential backoff (1→2→4초, 3회)
# 5. 안전 필터링: BLOCK_NONE (기술 기사 차단 방지)

# 프롬프트 전략:
# - 한국어 프롬프트 (Gemini 한국어 이해 우수)
# - 기술 용어 영어 유지 지시
# - 요약: 3-5문장, "~다" 체
# - 스크립트: 구어체, 3000-4000자
```

---

## Databricks 면접 어필 정리

### Delta Lake 전문성
- ACID 트랜잭션 (MERGE upsert)
- Medallion Architecture 직접 설계
- Time Travel, Schema Evolution
- Partitioning 전략 (날짜/카테고리)

### Spark 활용
- Local mode → "Databricks 클러스터로 즉시 확장 가능한 구조"
- DataFrame API, Window Functions, UDF
- Structured Streaming 확장 가능성

### AI Engineering
- **LLM 추상화 레이어**: 로컬/클라우드 교체 가능 설계
- **비용 최적화**: 태스크 복잡도별 모델 라우팅
- **에러 핸들링**: JSON 파싱 재시도, 폴백 전략
- Databricks Foundation Model API 연동 가능성 (추상화 덕분)

### 인프라 + 운영
- ARM 환경 Spark + LLM 세팅
- cron 자동화
- 구조화 로깅, 모니터링

---

## 리스크 및 대안

| 리스크 | 대안 |
|--------|------|
| ARM PySpark 설치 실패 | DuckDB + deltalake (delta-rs) |
| Ollama OOM | Spark stop() 후 실행, 또는 Qwen 3B로 다운그레이드 |
| Qwen 7B JSON 불안정 | 3회 재시도 + regex + 기본값 폴백 |
| Gemini 무료 tier 정책 변경 | Groq Free (Llama 3) 또는 Claude Haiku |
| ARM 추론 너무 느림 | Qwen 2.5 3B로 교체 (2-3GB, 2배 빠름, 품질 다소 하락) |
| 수집 소스 차단/변경 | health_check + 자동 비활성화 |

---

## Phase 4-5 (향후)

| Phase | 내용 | 추가 의존성 |
|-------|------|-----------|
| Phase 4 | TTS 팟캐스트 | edge-tts (무료), ffmpeg |
| Phase 5 | RAG Q&A | chromadb, fastapi, uvicorn |
