# delta-digest

> AI/Databricks 기술 동향을 매일 자동 수집·정리하는 개인 지식 시스템

Databricks SE 포지션 포트폴리오 프로젝트입니다.  
RSS, ArXiv, Hacker News, GitHub에서 매일 AI/데이터 엔지니어링 관련 뉴스를 자동 수집하고, Delta Lake Medallion Architecture로 처리한 뒤, LLM이 한국어로 요약한 다이제스트를 생성합니다.

**월 운영 비용: $0** — 로컬 LLM(Ollama) + Gemini Free API + Oracle Cloud Free Tier

---

## 왜 이 프로젝트를 만들었나

Databricks SE 인터뷰를 준비하면서 두 가지 문제가 있었습니다.

1. AI/Databricks 관련 뉴스가 너무 많아서 매일 따라가기 힘들다
2. Delta Lake와 Spark를 직접 써본 프로젝트가 없다

이 프로젝트는 두 문제를 동시에 해결합니다. 실제로 매일 사용하면서, Databricks 핵심 기술 스택(Spark, Delta Lake, Medallion Architecture)을 직접 구현한 포트폴리오입니다.

---

## 아키텍처

```
수집 소스
┌──────────────────────────────────────┐
│  RSS Feed   ArXiv API   HN Firebase  │
│  (Databricks, Google AI, MIT 등)     │  GitHub Search API
└──────────────────┬───────────────────┘
                   │ async HTTP (httpx)
                   ▼
        ┌─────────────────────┐
        │    Bronze Layer     │  ← Delta Lake
        │  RAW 데이터 저장     │
        │  MERGE upsert (URL) │  ← 중복 방지
        │  날짜 파티션         │
        └──────────┬──────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │    Silver Layer     │  ← Delta Lake
        │  HTML 태그 제거      │
        │  중복 URL 제거       │
        │  단어 수 필터링      │
        │  Databricks 관련 분류│
        └──────────┬──────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
   Ollama (로컬)      Gemini Flash (API)
   Qwen 2.5 7B       무료 티어
   중요도 스코어링    한국어 요약 생성
          │                 │
          └────────┬────────┘
                   ▼
        ┌─────────────────────┐
        │    Gold Layer       │  ← Delta Lake
        │  AI 스코어 + 요약   │
        │  쿼터 기반 Top 20   │
        │  digest_included 플래그│
        └──────────┬──────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
  outputs/digests/    outputs/glossary/
  YYYY-MM-DD-digest-ai.pdf   glossary.json
  YYYY-MM-DD-digest-db.pdf   (누적 아카이브)
  YYYY-MM-DD-glossary.pdf
```

---

## Delta Lake Medallion Architecture 상세

이 프로젝트의 핵심은 Databricks가 권장하는 **Bronze → Silver → Gold** 레이어 설계를 직접 구현한 것입니다.

### Bronze Layer (원본 보존)

```python
# URL 기준 MERGE upsert — 중복 삽입 방지, 원본 데이터 불변 유지
delta_table.alias("target")
    .merge(df.alias("source"), "target.url = source.url")
    .whenNotMatchedInsertAll()
    .execute()
```

- 수집된 모든 기사를 원본 그대로 저장
- URL이 동일하면 재수집해도 중복 삽입 없음 (MERGE upsert)
- `ingestion_date`로 파티셔닝 → 날짜별 빠른 조회
- Delta Lake **Time Travel**로 과거 데이터 복원 가능

### Silver Layer (정제)

```python
# HTML 제거 → 단어 수 필터링 → Databricks 관련 분류
bronze_df
    .dropDuplicates(["url"])
    .withColumn("clean_content", strip_html_udf(col("content")))
    .withColumn("word_count", word_count_udf(col("clean_content")))
    .withColumn("is_databricks_related", databricks_check_udf(...))
    .filter(col("word_count") >= 10)
```

- HTML 태그 제거, 공백 정규화
- URL 기준 중복 제거
- Databricks/Delta Lake/Spark 키워드 감지 → `is_databricks_related` 플래그
- `replaceWhere`로 날짜 단위 멱등 재처리 (안전한 재실행)

### Gold Layer (AI 강화)

```python
# Silver + AI 스코어 JOIN + 쿼터 기반 Top 20 선별
silver_df.join(scores_df, on="url", how="left")
window = Window.orderBy(col("overall_score").desc())
gold_df.withColumn("digest_included", col("url").isin(quota_urls))
```

- Silver 데이터 + Ollama 스코어 + Gemini 요약 JOIN
- 쿼터 기반 선별: Databricks 10건 + AI 핫뉴스 20건 + 기타 10건 (총 40건)
- `digest_included` 플래그로 다이제스트 포함 여부 표시

---

## LLM 하이브리드 전략

태스크 복잡도에 따라 로컬 LLM과 클라우드 API를 분리 배치했습니다.

```
LLMClient (추상 클래스)
├── OllamaClient  →  localhost:11434  →  Qwen 2.5 7B  →  스코어링
└── GeminiClient  →  Google API      →  Gemini 2.5 Flash  →  요약, 스크립트
```

| 태스크 | 모델 | 이유 |
|--------|------|------|
| 중요도 스코어링 (~180건/일) | Ollama Qwen 2.5 7B (로컬) | 단순 JSON 출력, 대량 처리, 무제한 |
| 한국어 요약 (상위 20건/일) | Gemini 2.5 Flash (무료 API) | 한국어 품질, 긴 컨텍스트 처리 |

**추상화 레이어** 덕분에 향후 Databricks Foundation Model API나 Anthropic Claude로 교체할 때 클라이언트 한 줄만 바꾸면 됩니다.

```python
# 태스크별 라우팅
router.get_client("scoring")        # → OllamaClient
router.get_client("summarization")  # → GeminiClient
```

### Ollama 장애 대응

Ollama 미실행 상태에서도 파이프라인이 중단되지 않습니다:
- Ollama 헬스체크 실패 → mock 스코어로 자동 폴백
- Gemini는 Ollama와 독립적으로 동작 (요약은 항상 실행)

---

## 다이제스트 출력 형식

매일 3개의 PDF가 `outputs/digests/`에 생성됩니다.

| 파일 | 내용 |
|------|------|
| `YYYY-MM-DD-digest-ai.pdf` | AI 핫뉴스 TOP 20 (풀 카드: 제목 + 한국어 요약 + 핵심 포인트 3개) |
| `YYYY-MM-DD-digest-db.pdf` | Databricks TOP 10 (풀 카드) + 기타 TOP 10 (컴팩트 카드) |
| `YYYY-MM-DD-glossary.pdf` | 오늘의 신규 기술 용어 + 전체 누적 용어집 |

용어집은 `outputs/glossary/glossary.json`에 누적 아카이빙됩니다. 이미 저장된 용어는 중복 저장하지 않으며, Gemini가 신규 용어에 대한 한국어 한 줄 정의를 배치로 생성합니다.

---

## 수집 소스

| 소스 | 타입 | 카테고리 |
|------|------|----------|
| Databricks Blog | RSS | Databricks (우선순위 높음) |
| OpenAI Blog | RSS | AI (우선순위 높음) |
| Google AI Blog | RSS | AI 연구 |
| NVIDIA Blog | RSS | AI/GPU (키워드 필터링) |
| The Sequence | RSS | AI/ML |
| Hacker News | Firebase API | 기술 트렌드 |
| ArXiv (cs.AI, cs.LG, cs.CL) | Atom API | 논문 |
| GitHub Trending (LLM 관련) | Search API | 오픈소스 |

`src/ingestion/sources.yaml`에서 소스 추가/제거/필터 키워드 관리.

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 데이터 처리 | PySpark 3.5 (local mode) |
| 스토리지 | Delta Lake 3.2 (delta-spark) |
| 언어 | Python 3.11 |
| 패키지 관리 | uv |
| HTTP 클라이언트 | httpx (async) |
| HTML 파싱 | BeautifulSoup4 |
| RSS 파싱 | feedparser |
| 설정 관리 | Pydantic Settings |
| 로깅 | structlog (구조화 로그) |
| 템플릿 | Jinja2 |
| PDF 생성 | weasyprint |
| LLM (로컬) | Ollama + Qwen 2.5 7B |
| LLM (클라우드) | Google Gemini 2.0 Flash |
| 인프라 | Oracle Cloud Free Tier (ARM) |

---

## 인프라 및 운영

### 서버 스펙 (Oracle Cloud Free Tier)
- VM.Standard.A1.Flex (ARM64, Ubuntu 22.04)
- 4 OCPU, 24GB RAM
- 월 비용: $0

### 메모리 관리 (24GB)

Spark와 Ollama를 동시에 실행하면 OOM이 발생할 수 있어 **순차 처리**합니다.

```
Step 1-3 (수집 + Bronze + Silver): Spark 실행 (4GB)
Step 4   (스코어링):               Spark 종료 → Ollama 실행 (5-6GB)
Step 5   (Gold 저장):              Ollama 완료 → Spark 재시작
Step 6   (PDF 생성):               weasyprint (경량, 3개 PDF)
```

### 일일 처리 시간

```
수집 (9개 소스):        ~2-3분
Bronze MERGE:           ~1분
Silver 변환:            ~1분
Ollama 스코어링 (180건): ~30-50분  ← 병목 (ARM 7B 모델)
Gemini 요약 (40건):     ~5-8분
Gold 저장:              ~1분
PDF 생성 (3개):         ~30초
─────────────────────────────
합계:                   ~40-65분
```

→ 새벽 5시 cron 실행 시 6시 전 완료

---

## 설치 및 실행

### 사전 요구사항
- Python 3.11+
- Java 11+ (PySpark 필수)
- [uv](https://docs.astral.sh/uv/) 패키지 매니저

### 로컬 개발 환경

```bash
# 1. 클론 및 의존성 설치
git clone https://github.com/YongjunJeong/delta-digest.git
cd delta-digest
uv sync

# 2. 환경변수 설정
cp .env.example .env
# .env 파일에 Gemini API 키 입력
# DIGEST_GEMINI_API_KEY=AIza...

# 3. 실행 (Java PATH 필요)
export JAVA_HOME=/opt/homebrew/opt/openjdk@11
uv run python src/run_daily.py

# LLM 없이 mock 모드로 빠른 테스트
uv run python src/run_daily.py --mock
```

### Oracle Cloud 서버 (프로덕션)

```bash
# Java 설치
sudo apt install openjdk-11-jdk

# uv 설치
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ollama 설치 및 모델 다운로드
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:7b

# 의존성 설치
uv sync

# 환경변수 설정
cp .env.example .env
vi .env  # Gemini API 키 입력

# cron 등록 (매일 새벽 5시)
crontab -e
0 5 * * * /home/ubuntu/delta-digest/scripts/run_daily.sh >> /home/ubuntu/delta-digest/outputs/logs/cron.log 2>&1
```

---

## 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DIGEST_GEMINI_API_KEY` | Google AI Studio API 키 | (필수) |
| `DIGEST_OLLAMA_BASE_URL` | Ollama 서버 주소 | `http://localhost:11434` |
| `DIGEST_OLLAMA_MODEL` | Ollama 모델명 | `qwen2.5:7b` |
| `DIGEST_DATA_DIR` | Delta Lake 데이터 경로 | `./data` |
| `DIGEST_OUTPUT_DIR` | 다이제스트 출력 경로 | `./outputs` |
| `DIGEST_SPARK_DRIVER_MEMORY` | Spark 드라이버 메모리 | `4g` |
| `DIGEST_LOG_LEVEL` | 로그 레벨 | `INFO` |

Gemini API 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 발급 가능합니다. (무료 한도: 1,500 req/day)

---

## 프로젝트 구조

```
delta-digest/
├── src/
│   ├── ingestion/           # 비동기 수집기
│   │   ├── base.py          # BaseCollector ABC + RawArticle 모델
│   │   ├── rss_collector.py # RSS/Atom 피드 수집
│   │   ├── hn_collector.py  # Hacker News Firebase API
│   │   ├── arxiv_collector.py # ArXiv Atom API
│   │   ├── github_collector.py # GitHub Search API
│   │   ├── run_all.py       # 전체 수집 오케스트레이터
│   │   └── sources.yaml     # 수집 소스 설정
│   ├── pipeline/            # Spark + Delta Lake
│   │   ├── spark_session.py # SparkSession 팩토리
│   │   ├── schemas.py       # Bronze/Silver/Gold 스키마 정의
│   │   ├── bronze.py        # MERGE upsert
│   │   ├── silver.py        # HTML 정제, 중복 제거, UDF
│   │   └── gold.py          # AI 결과 JOIN, 쿼터 선별
│   ├── agents/              # LLM 에이전트
│   │   ├── llm_client.py    # LLMClient ABC + Ollama/Gemini 구현
│   │   ├── router.py        # 태스크별 LLM 라우팅
│   │   ├── scorer.py        # 중요도 스코어링 (Ollama)
│   │   ├── summarizer.py    # 한국어 요약 (Gemini)
│   │   └── glossary_agent.py # 기술 용어 추출 및 누적 아카이빙
│   ├── output/
│   │   ├── pdf_writer.py    # PDF 생성 (weasyprint)
│   │   └── templates/
│   │       ├── digest.html.j2   # 뉴스레터 PDF 템플릿
│   │       └── glossary.html.j2 # 용어집 PDF 템플릿
│   ├── common/
│   │   ├── config.py        # Pydantic Settings
│   │   ├── logging.py       # structlog 설정
│   │   └── models.py        # RawArticle 데이터 모델
│   └── run_daily.py         # 엔드-투-엔드 파이프라인
├── scripts/
│   ├── run_daily.sh         # cron용 실행 스크립트
│   ├── test_spark.py        # Spark + Delta Lake 연결 테스트
│   ├── test_bronze.py       # Bronze 파이프라인 테스트
│   ├── test_silver.py       # Silver 파이프라인 테스트
│   └── test_gold.py         # Gold 파이프라인 테스트
├── data/                    # Delta Lake 데이터 (gitignore)
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── outputs/                 # 생성된 출력물 (gitignore)
│   ├── digests/             # 일일 PDF 3개
│   └── glossary/            # glossary.json (누적)
├── .env.example
├── pyproject.toml
└── uv.lock
```

---

## 왜 이 기술 스택인가

단순히 "작동하는" 파이프라인을 만드는 방법은 많다. 이 프로젝트에서 각 기술을 선택한 데는 구체적인 이유가 있다.

**Delta Lake — 파일 시스템 대신 트랜잭셔널 스토리지**

매일 동일한 URL의 기사가 재수집된다. 단순 파일 저장이라면 중복이 쌓이거나 매번 전체를 덮어써야 한다. Delta Lake의 MERGE upsert는 "URL이 같으면 무시, 새 것만 삽입"을 원자적으로 처리한다. Partitioning으로 날짜별 조회를 빠르게 하고, Time Travel로 파이프라인 버그 발생 시 이전 상태로 롤백할 수 있다.

**Medallion Architecture — 재처리 가능한 파이프라인**

Bronze(원본 불변) → Silver(정제) → Gold(AI 강화) 레이어 분리는 "Silver 로직을 고쳤을 때 Bronze를 다시 수집하지 않아도 된다"는 실용적 이점에서 나온 선택이다. Silver는 `replaceWhere`로 날짜 단위 멱등 재처리를 지원한다.

**LLM 추상화 레이어 — 벤더 락인 방지**

Ollama(로컬)와 Gemini(클라우드)를 동일한 `LLMClient` 인터페이스로 추상화했다. 스코어링처럼 대량 반복 작업은 비용 $0인 로컬 모델로, 한국어 품질이 중요한 요약은 클라우드 API로 라우팅한다. 향후 Databricks Foundation Model API나 다른 제공자로 교체해도 클라이언트 구현체 하나만 바꾸면 된다.

**Ollama 폴백 설계 — 부분 장애 허용**

새벽 cron 실행 중 Ollama가 다운되면 파이프라인 전체가 멈추면 안 된다. 헬스체크 실패 시 mock 스코어로 자동 폴백해 요약과 PDF 생성은 계속 진행된다.

---

## 로드맵

- [x] Phase 1: 수집 레이어 (RSS / HN / ArXiv / GitHub)
- [x] Phase 2: Delta Lake Medallion Pipeline (Bronze → Silver → Gold)
- [x] Phase 3: LLM 하이브리드 + 한국어 요약 생성
- [x] Phase 4a: PDF 뉴스레터 출력 (digest-ai.pdf + digest-db.pdf)
- [x] Phase 4b: 기술 용어 아카이빙 + 용어집 PDF
- [⏸] Phase 5: 대화형 TTS 팟캐스트 (구현 완료, 음성 품질 개선 후 운영 예정)
