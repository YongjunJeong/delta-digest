# Phase 4b: PDF 뉴스레터 출력 설계

**날짜**: 2026-03-06
**상태**: 승인됨
**목표**: Gold layer 40개 기사를 매일 두 개의 뉴스레터 PDF로 자동 생성

---

## 배경

출퇴근·육아 중 눈으로 읽을 수 있는 PDF 출력물이 필요.
NotebookLM으로 수동 팟캐스트 생성 시 업로드 소스로도 활용.
기존 Markdown 출력은 PDF로 대체.

---

## 출력 파일

```
outputs/digests/
├── 2026-03-06-digest-ai.pdf   ← PDF 1: AI 핫뉴스 20개
└── 2026-03-06-digest-db.pdf   ← PDF 2: Databricks 10개 + 기타 10개
```

---

## 콘텐츠 구조

### PDF 1 — AI 핫뉴스 (`-ai.pdf`)

| 섹션 | 기사 수 | 카드 스타일 |
|------|---------|------------|
| AI 핫뉴스 TOP 20 | 20 | 풀 카드 (제목·요약·key points) |

### PDF 2 — Databricks & 기타 (`-db.pdf`)

| 섹션 | 기사 수 | 카드 스타일 |
|------|---------|------------|
| Databricks / Delta Lake TOP 10 | 10 | 풀 카드 (심화 요약 포함) |
| 기타 뉴스 TOP 10 | 10 | 컴팩트 카드 (제목 + one-line summary) |

---

## Gold Layer 쿼터 확대

현재 → 변경:

| 구분 | 현재 | 변경 |
|------|------|------|
| `top_databricks` | 5 | 10 |
| `top_ai` | 10 | 20 |
| `top_other` | 5 | 10 |
| `top_n` (silver_to_gold) | 20 | 40 |
| 요약 대상 (summarize_batch) | top 20 | top 40 |

---

## 아키텍처

```
Gold Layer (40개 기사)
       │
       ▼
pdf_writer.py
├── build_digest_html(articles, section)  →  Jinja2 → HTML 문자열
└── write_pdfs(articles, total, date)     →  weasyprint
    ├── YYYY-MM-DD-digest-ai.pdf   (AI 20개)
    └── YYYY-MM-DD-digest-db.pdf   (Databricks 10개 + 기타 10개)
```

---

## 파일 변경 목록

### 새로 생성

| 파일 | 역할 |
|------|------|
| `src/output/pdf_writer.py` | `write_pdfs()` 진입점, HTML 빌드 + weasyprint 호출 |
| `src/output/templates/digest.html.j2` | 뉴스레터 HTML/CSS 템플릿 |

### 수정

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline/gold.py` | `_select_digest_urls(top_databricks=10, top_ai=20, top_other=10)` |
| `src/run_daily.py` | `top_n=40`, 요약 대상 40개, Step 6을 `write_pdfs()` 호출로 교체 |

### 삭제

| 파일 | 이유 |
|------|------|
| `src/output/markdown_writer.py` | PDF로 완전 대체 |
| `src/output/templates/digest.md.j2` | PDF로 완전 대체 |

---

## HTML 템플릿 레이아웃

```
┌──────────────────────────────────────────┐
│  DELTA DIGEST         2026-03-06         │  헤더: 제목 + 날짜
│  수집 120건 · 선별 40건 · AI 핫뉴스 TOP 20 │  부제: 섹션 설명
├──────────────────────────────────────────┤
│ ┌──────────────────────────────────────┐ │
│ │ [1] 기사 제목                  [링크] │ │  풀 카드
│ │ 출처: TechCrunch  ·  점수: 8.4      │ │
│ │ • 핵심 포인트 1                      │ │
│ │ • 핵심 포인트 2                      │ │
│ │ 요약 텍스트 (full_summary)...        │ │
│ └──────────────────────────────────────┘ │
│  ... × 20                                │
├──────────────────────────────────────────┤
│  Generated 2026-03-06 09:00 KST          │  푸터
└──────────────────────────────────────────┘
```

기타 뉴스 컴팩트 카드 (PDF 2 하단):
```
│ [1] 기사 제목                       출처 │
│     one_line_summary 한 줄            │
```

---

## CSS 스타일

- **배경**: 흰색 (`#ffffff`)
- **폰트**: `Noto Sans KR` (시스템 폰트, `apt install fonts-noto-cjk`)
- **액센트 색상**: 제목 `#1a1a2e`, 링크 `#2563eb`, Databricks 섹션 `#e53e3e`
- **페이지**: A4, 여백 15mm
- **카드**: 미세한 보더 + 그림자, 기사 번호 배지

---

## 폰트 설치 (Oracle Cloud)

```bash
sudo apt install -y fonts-noto-cjk
# weasyprint가 시스템 폰트를 자동 탐색
```

---

## 의존성

```toml
weasyprint = "*"
```

---

## run_daily.py 통합

```python
# Step 6: PDF 출력 (마크다운 대체)
logger.info("step6_pdf")
from src.output.pdf_writer import write_pdfs
pdf_paths = write_pdfs(digest_articles, total_collected, ingestion_date)
for p in pdf_paths:
    print(f"📄 PDF saved: {p}")
```

---

## 테스트 전략

- `test_pdf_writer.py`: mock 기사 데이터로 HTML 빌드 검증 (weasyprint 호출 없이)
- `test_gold_quota.py`: 40개 쿼터 선택 로직 검증
- smoke test: 소수 기사로 실제 PDF 파일 생성 확인

---

## 비용

| 항목 | 비용 |
|------|------|
| weasyprint (로컬 HTML→PDF) | $0 |
| Gemini 요약 추가 (20건 더) | $0 (Free tier 여유 충분) |
| **합계** | **$0** |
