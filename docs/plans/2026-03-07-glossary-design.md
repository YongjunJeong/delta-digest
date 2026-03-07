# 기술 용어 아카이빙 설계

**날짜**: 2026-03-07
**상태**: 승인됨
**목표**: 매일 뉴스에서 주요 기술 용어를 추출해 한 줄 정의와 함께 누적 아카이빙하고, 별도 PDF로 출력

---

## 배경

매일 AI/Databricks 뉴스를 읽으면서 새로 등장하는 기술 용어를 체계적으로 공부하고 싶음.
한번 저장된 용어는 중복 저장하지 않고, 누적 아카이브를 매일 성장시키는 방식.

---

## 출력 파일

```
outputs/
├── digests/
│   ├── YYYY-MM-DD-digest-ai.pdf      ← AI 핫뉴스 20개 (기존)
│   ├── YYYY-MM-DD-digest-db.pdf      ← Databricks+기타 20개 (기존)
│   └── YYYY-MM-DD-glossary.pdf       ← 오늘의 신규 용어 + 전체 누적 (신규)
└── glossary/
    └── glossary.json                 ← 누적 아카이브 (영구 보존)
```

신규 용어가 0개인 날은 glossary.pdf 생성 스킵.

---

## 아키텍처

```
Gold Layer (상위 20개 기사, overall_score 기준)
    │  tech_keywords 수집
    ▼
GlossaryAgent (src/agents/glossary_agent.py)
├── load_archive()         → outputs/glossary/glossary.json 읽기
├── find_new_terms()       → 아카이브에 없는 신규 용어 필터링
├── generate_definitions() → Gemini 1회 배치 호출 (신규 용어만)
└── save_archive()         → glossary.json 업데이트
    │
    ├──→ outputs/glossary/glossary.json     (누적 아카이브)
    └──→ list[GlossaryTerm]
              │
              ▼
    pdf_writer.py (write_glossary_pdf())
    └──→ outputs/digests/YYYY-MM-DD-glossary.pdf
```

---

## 데이터 모델

### glossary.json 구조

```json
{
  "RAG": {
    "definition": "검색 증강 생성(Retrieval-Augmented Generation). LLM이 외부 지식베이스를 검색해 답변 품질을 높이는 기법.",
    "first_seen": "2026-03-07"
  },
  "Delta Lake": {
    "definition": "Apache Spark 기반 오픈소스 스토리지 레이어. ACID 트랜잭션과 스키마 강제를 지원한다.",
    "first_seen": "2026-03-01"
  }
}
```

### GlossaryTerm dataclass

```python
@dataclass
class GlossaryTerm:
    term: str
    definition: str
    first_seen: str   # "YYYY-MM-DD"
    is_new: bool      # 오늘 신규 여부
```

---

## GlossaryAgent 설계

### 소스: tech_keywords 수집 방법

Gold layer의 상위 20개 기사(overall_score 기준)에서 `tech_keywords` 필드를 수집.
`tech_keywords`는 summarizer.py에서 이미 Gemini가 추출하므로 추가 비용 없음.

### 신규 용어 필터링

```python
new_terms = [t for t in collected_terms if t not in archive]
```

대소문자 정규화 (예: "rag" == "RAG") 적용.

### Gemini 배치 호출 (신규 용어만)

프롬프트:
```
다음 AI/데이터 엔지니어링 기술 용어 각각에 대해 한국어로 한 줄 정의를 작성하세요.
기술 용어 원문은 유지하고, "~다" 체를 사용하세요.

용어 목록: RAG, LoRA, RLHF, ...

반드시 아래 JSON만 반환:
{"RAG": "정의...", "LoRA": "정의..."}
```

신규 용어가 없으면 Gemini 호출 없음.

---

## glossary.pdf 레이아웃

```
┌──────────────────────────────────────────┐
│  Delta Digest 용어집      2026-03-07     │  헤더
│  오늘 신규 12개 · 누적 87개              │
├──────────────────────────────────────────┤
│  📚 오늘의 신규 용어 (12개)              │  신규 섹션
│  ┌────────────────────────────────────┐  │
│  │ RAG                                │  │  용어 카드
│  │ 검색 증강 생성(Retrieval-Augmented  │  │
│  │ Generation). LLM이 외부 지식...     │  │
│  └────────────────────────────────────┘  │
│  ... × N                                 │
├──────────────────────────────────────────┤
│  📖 전체 용어 아카이브 (가나다/ABC순)    │  누적 섹션
│  [A] AgentRAG  Apache Iceberg  AutoML   │  알파벳 인덱스
│  [B] BERT  BPE                          │
│  [D] Delta Lake  DPO  DuckDB            │
│  ...                                    │
└──────────────────────────────────────────┘
```

- 신규 용어: 풀 카드 (용어명 + 정의)
- 전체 아카이브: 컴팩트 (알파벳/가나다 그룹별, 용어명 + 정의 한 줄)

---

## run_daily.py 통합 (Step 6.5)

```python
# Step 6.5: Glossary (PDF 생성 전)
logger.info("step6_5_glossary")
from src.agents.glossary_agent import GlossaryAgent
from src.output.pdf_writer import write_glossary_pdf

if health.get("gemini") and not use_mock_scores:
    agent = GlossaryAgent(gemini_client, settings.glossary_path)
    new_terms = await agent.update(digest_articles)
    if new_terms:
        glossary_path = write_glossary_pdf(new_terms, agent.all_terms, ingestion_date)
        print(f"📚 Glossary saved: {glossary_path} ({len(new_terms)} new terms)")
else:
    logger.info("glossary_skipped", reason="mock_mode_or_gemini_unavailable")
```

---

## 파일 목록

### 새로 생성

| 파일 | 역할 |
|------|------|
| `src/agents/glossary_agent.py` | GlossaryAgent: 용어 추출·정의·아카이브 관리 |
| `src/output/templates/glossary.html.j2` | 용어집 PDF HTML 템플릿 |

### 수정

| 파일 | 변경 내용 |
|------|-----------|
| `src/output/pdf_writer.py` | `write_glossary_pdf()` 함수 추가 |
| `src/run_daily.py` | Step 6.5 추가, `glossary_path` 설정 |
| `src/common/config.py` | `glossary_path` 프로퍼티 추가 |

---

## 비용

| 항목 | 비용 |
|------|------|
| tech_keywords 추출 (이미 요약 단계에서 수행) | $0 |
| 신규 용어 정의 생성 (Gemini, 1일 1회 배치) | $0 (Free tier) |
| 신규 용어 0개인 날 | Gemini 호출 없음 |
| weasyprint PDF 생성 | $0 |
| **합계** | **$0** |

---

## 테스트 전략

- `test_glossary_agent.py`: 중복 제거, 배치 정의 생성, 아카이브 저장 검증
- `test_pdf_writer.py`: `write_glossary_pdf()` 파일명·weasyprint 호출 검증
