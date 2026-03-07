# PDF Newsletter Output Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gold layer 40개 기사를 매일 두 개의 PDF 뉴스레터로 자동 생성 (AI 20개 / Databricks+기타 20개)

**Architecture:** Gold layer 쿼터를 5/10/5 → 10/20/10으로 확대하고, weasyprint + Jinja2 HTML 템플릿으로 두 PDF를 생성한다. 기존 markdown_writer.py는 삭제하고 pdf_writer.py로 완전 대체한다.

**Tech Stack:** weasyprint, Jinja2, pydantic-settings, pytest

---

### Task 1: Gold 쿼터 10/20/10으로 확대

**Files:**
- Modify: `src/pipeline/gold.py:70`
- Test: `tests/test_pipeline/test_gold_quota.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_pipeline/test_gold_quota.py` 신규 파일:

```python
"""Tests for Gold layer quota selection logic."""
from unittest.mock import MagicMock

import pytest

from src.pipeline.gold import _select_digest_urls


def _make_mock_df(rows: list[dict]):
    """Build a MagicMock that mimics the Spark DataFrame calls used by _select_digest_urls."""
    def fake_filter(cond):
        # Return a new mock; we control collect() results below
        return MagicMock(
            orderBy=lambda *a, **kw: MagicMock(
                select=lambda *a: MagicMock(
                    limit=lambda n: MagicMock(
                        collect=lambda: [MagicMock(url=r["url"]) for r in rows[:n]]
                    )
                )
            )
        )

    mock_df = MagicMock()
    mock_df.filter.side_effect = fake_filter
    return mock_df


def test_select_digest_urls_quota():
    """_select_digest_urls with new defaults returns up to 40 URLs."""
    # Build 50 fake rows
    rows = [{"url": f"http://example.com/{i}", "is_databricks_related": i < 15} for i in range(50)]
    mock_df = _make_mock_df(rows)

    result = _select_digest_urls(mock_df, top_databricks=10, top_ai=20, top_other=10)
    assert len(result) <= 40


def test_select_digest_urls_default_quota():
    """_select_digest_urls default args are now 10/20/10."""
    import inspect
    sig = inspect.signature(_select_digest_urls)
    assert sig.parameters["top_databricks"].default == 10
    assert sig.parameters["top_ai"].default == 20
    assert sig.parameters["top_other"].default == 10
```

**Step 2: 테스트 실패 확인**

```bash
cd /Users/yongjun/Desktop/Portfolio/delta-digest
uv run pytest tests/test_pipeline/test_gold_quota.py -v
```

Expected: `FAILED test_select_digest_urls_default_quota` — 현재 기본값이 5/10/5이므로 실패

**Step 3: gold.py 수정**

`src/pipeline/gold.py` 두 곳 변경:

① 70번째 줄 — `silver_to_gold()` 안의 함수 호출:
```python
# 변경 전
quota = _select_digest_urls(gold_df, top_databricks=5, top_ai=10, top_other=5)
# 변경 후
quota = _select_digest_urls(gold_df, top_databricks=10, top_ai=20, top_other=10)
```

② `_select_digest_urls()` 기본값:
```python
# 변경 전
def _select_digest_urls(
    gold_df,
    top_databricks: int = 5,
    top_ai: int = 10,
    top_other: int = 5,
) -> list[str]:
# 변경 후
def _select_digest_urls(
    gold_df,
    top_databricks: int = 10,
    top_ai: int = 20,
    top_other: int = 10,
) -> list[str]:
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_pipeline/test_gold_quota.py -v
```

Expected: `PASSED` 2건

**Step 5: 커밋**

```bash
git add src/pipeline/gold.py tests/test_pipeline/test_gold_quota.py
git commit -m "feat: expand Gold quota to 10/20/10 (40 articles total)"
```

---

### Task 2: HTML 뉴스레터 템플릿 생성

**Files:**
- Create: `src/output/templates/digest.html.j2`

템플릿은 순수 HTML/CSS이므로 별도 단위 테스트 없이 Task 3에서 pdf_writer 테스트와 함께 검증한다.

**Step 1: 템플릿 파일 생성**

`src/output/templates/digest.html.j2`:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>Delta Digest {{ date }} — {{ title_suffix }}</title>
  <style>
    @page { size: A4; margin: 15mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
      background: #ffffff;
      color: #1a1a2e;
      font-size: 9.5pt;
      line-height: 1.5;
    }
    .header {
      border-bottom: 3px solid #2563eb;
      padding-bottom: 10px;
      margin-bottom: 18px;
    }
    .header-top { display: flex; justify-content: space-between; align-items: baseline; }
    .header h1 { font-size: 20pt; color: #1a1a2e; letter-spacing: -0.5px; }
    .badge {
      font-size: 9pt; font-weight: bold; color: #2563eb;
      background: #eff6ff; padding: 3px 8px; border-radius: 12px;
    }
    .meta { font-size: 8.5pt; color: #6b7280; margin-top: 4px; }
    .section-title {
      font-size: 12pt; font-weight: bold;
      padding: 5px 10px;
      margin: 20px 0 10px;
      border-left: 4px solid #2563eb;
      background: #eff6ff;
      color: #1e40af;
    }
    .section-title.db { border-left-color: #dc2626; background: #fff1f2; color: #991b1b; }
    .section-title.other { border-left-color: #6b7280; background: #f9fafb; color: #374151; }
    .article-card {
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 10px 12px;
      margin-bottom: 10px;
      break-inside: avoid;
    }
    .article-header { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 4px; }
    .article-num {
      flex-shrink: 0;
      display: inline-flex; align-items: center; justify-content: center;
      width: 20px; height: 20px;
      background: #2563eb; color: white;
      border-radius: 50%; font-size: 7.5pt; font-weight: bold;
      margin-top: 1px;
    }
    .article-num.db { background: #dc2626; }
    .article-num.other { background: #6b7280; }
    .article-title { font-size: 10.5pt; font-weight: bold; line-height: 1.35; }
    .article-title a { color: #1d4ed8; text-decoration: none; }
    .article-meta { font-size: 8pt; color: #6b7280; margin: 3px 0 6px 28px; }
    .key-points { margin: 4px 0 4px 28px; }
    .key-points li { font-size: 8.5pt; margin-bottom: 2px; color: #374151; }
    .summary { font-size: 8.5pt; color: #4b5563; margin: 4px 0 0 28px; line-height: 1.55; }
    .article-card.compact { padding: 7px 12px; }
    .article-card.compact .article-title { font-size: 9.5pt; }
    .one-line { font-size: 8.5pt; color: #6b7280; margin-left: 28px; }
    .footer {
      margin-top: 24px; padding-top: 8px;
      border-top: 1px solid #e5e7eb;
      font-size: 7.5pt; color: #9ca3af; text-align: center;
    }
  </style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <h1>Delta Digest</h1>
    <span class="badge">{{ title_suffix }}</span>
  </div>
  <div class="meta">{{ date }} · 수집 {{ total_collected }}건 선별</div>
</div>

{% if ai_news %}
<div class="section-title">🔥 AI 핫뉴스 TOP {{ ai_news | length }}</div>
{% for article in ai_news %}
<div class="article-card">
  <div class="article-header">
    <span class="article-num">{{ loop.index }}</span>
    <div class="article-title">
      <a href="{{ article.url }}">{{ article.title }}</a>
    </div>
  </div>
  <div class="article-meta">
    {{ article.source_name }} · 점수 {{ "%.1f" | format(article.overall_score | float) }}
  </div>
  {% if article.key_points %}
  <ul class="key-points">
    {% for point in article.key_points %}<li>{{ point }}</li>{% endfor %}
  </ul>
  {% endif %}
  {% if article.full_summary %}
  <div class="summary">{{ article.full_summary }}</div>
  {% elif article.one_line_summary %}
  <div class="summary">{{ article.one_line_summary }}</div>
  {% endif %}
</div>
{% endfor %}
{% endif %}

{% if databricks_news %}
<div class="section-title db">🔷 Databricks / Delta Lake TOP {{ databricks_news | length }}</div>
{% for article in databricks_news %}
<div class="article-card">
  <div class="article-header">
    <span class="article-num db">{{ loop.index }}</span>
    <div class="article-title">
      <a href="{{ article.url }}">{{ article.title }}</a>
    </div>
  </div>
  <div class="article-meta">
    {{ article.source_name }} · 관련도 {{ "%.1f" | format(article.relevance_score | float) }}
  </div>
  {% if article.key_points %}
  <ul class="key-points">
    {% for point in article.key_points %}<li>{{ point }}</li>{% endfor %}
  </ul>
  {% endif %}
  {% if article.full_summary %}
  <div class="summary">{{ article.full_summary }}</div>
  {% elif article.one_line_summary %}
  <div class="summary">{{ article.one_line_summary }}</div>
  {% endif %}
</div>
{% endfor %}
{% endif %}

{% if other_news %}
<div class="section-title other">📌 기타 뉴스 TOP {{ other_news | length }}</div>
{% for article in other_news %}
<div class="article-card compact">
  <div class="article-header">
    <span class="article-num other">{{ loop.index }}</span>
    <div class="article-title">
      <a href="{{ article.url }}">{{ article.title }}</a>
    </div>
  </div>
  <div class="one-line">{{ article.one_line_summary }}</div>
</div>
{% endfor %}
{% endif %}

<div class="footer">
  Generated by delta-digest at {{ generated_at }}
</div>

</body>
</html>
```

**Step 2: 커밋**

```bash
git add src/output/templates/digest.html.j2
git commit -m "feat: add HTML newsletter template for PDF output"
```

---

### Task 3: pdf_writer.py 구현 (TDD)

**Files:**
- Create: `src/output/pdf_writer.py`
- Test: `tests/test_output/test_pdf_writer.py`

**Step 1: 실패하는 테스트 작성**

`tests/test_output/test_pdf_writer.py`:

```python
"""Tests for PDF newsletter writer."""
import json
from datetime import date
from pathlib import Path

import pytest


# ── 공통 픽스처 ──────────────────────────────────────────────────────────────

def _make_article(
    url: str,
    title: str,
    is_db: bool = False,
    overall_score: float = 7.0,
    relevance_score: float = 0.0,
) -> dict:
    return {
        "url": url,
        "title": title,
        "source_name": "TechNews",
        "source_type": "rss",
        "is_databricks_related": is_db,
        "overall_score": overall_score,
        "relevance_score": relevance_score if is_db else 0.0,
        "one_line_summary": f"{title} 한 줄 요약",
        "full_summary": f"{title} 상세 요약",
        "key_points": json.dumps(["포인트 1", "포인트 2"]),
    }


@pytest.fixture
def sample_articles():
    articles = []
    # 12 Databricks
    for i in range(12):
        articles.append(_make_article(f"http://db.com/{i}", f"DB 기사 {i}", is_db=True, relevance_score=9.0 - i * 0.1))
    # 25 AI
    for i in range(25):
        articles.append(_make_article(f"http://ai.com/{i}", f"AI 기사 {i}", overall_score=8.5 - i * 0.1))
    return articles


# ── 섹션 분리 테스트 ─────────────────────────────────────────────────────────

def test_split_sections_quota(sample_articles):
    """_split_sections returns at most 10 DB, 20 AI, 10 other."""
    from src.output.pdf_writer import _split_sections
    db, ai, other = _split_sections(sample_articles)
    assert len(db) <= 10
    assert len(ai) <= 20
    assert len(other) <= 10


def test_split_sections_no_overlap(sample_articles):
    """No URL appears in more than one section."""
    from src.output.pdf_writer import _split_sections
    db, ai, other = _split_sections(sample_articles)
    db_urls = {a["url"] for a in db}
    ai_urls = {a["url"] for a in ai}
    other_urls = {a["url"] for a in other}
    assert db_urls.isdisjoint(ai_urls)
    assert db_urls.isdisjoint(other_urls)
    assert ai_urls.isdisjoint(other_urls)


# ── HTML 빌드 테스트 ─────────────────────────────────────────────────────────

def test_build_ai_html_contains_ai_articles(sample_articles):
    """build_ai_html returns HTML containing AI article titles."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 6), total_collected=120)
    assert "AI 기사 0" in html
    assert "Delta Digest" in html
    assert "AI 핫뉴스" in html


def test_build_ai_html_excludes_db_section(sample_articles):
    """build_ai_html does NOT include Databricks section."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 6), total_collected=120)
    assert "Databricks" not in html


def test_build_db_html_contains_db_articles(sample_articles):
    """build_db_html returns HTML containing Databricks article titles."""
    from src.output.pdf_writer import build_db_html
    html = build_db_html(sample_articles, date(2026, 3, 6), total_collected=120)
    assert "DB 기사 0" in html
    assert "Databricks" in html


def test_build_db_html_excludes_ai_section(sample_articles):
    """build_db_html does NOT include AI 핫뉴스 section."""
    from src.output.pdf_writer import build_db_html
    html = build_db_html(sample_articles, date(2026, 3, 6), total_collected=120)
    assert "AI 핫뉴스" not in html


def test_key_points_parsed_from_json_string(sample_articles):
    """key_points stored as JSON string are parsed into list items in HTML."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 6), total_collected=120)
    assert "포인트 1" in html


# ── write_pdfs 출력 경로 테스트 ──────────────────────────────────────────────

def test_write_pdfs_returns_two_paths(tmp_path, sample_articles, monkeypatch):
    """write_pdfs returns exactly two Path objects."""
    # Mock weasyprint to avoid actual PDF generation in unit test
    from unittest.mock import MagicMock, patch
    mock_html_cls = MagicMock()
    mock_html_cls.return_value.write_pdf = MagicMock()

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        from src.output.pdf_writer import write_pdfs
        paths = write_pdfs(sample_articles, 120, date(2026, 3, 6), output_dir=tmp_path)

    assert len(paths) == 2
    assert paths[0].name == "2026-03-06-digest-ai.pdf"
    assert paths[1].name == "2026-03-06-digest-db.pdf"


def test_write_pdfs_calls_weasyprint_twice(tmp_path, sample_articles):
    """write_pdfs calls weasyprint HTML().write_pdf() exactly twice."""
    from unittest.mock import MagicMock, patch
    mock_html_cls = MagicMock()
    mock_instance = MagicMock()
    mock_html_cls.return_value = mock_instance

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        from src.output.pdf_writer import write_pdfs
        write_pdfs(sample_articles, 120, date(2026, 3, 6), output_dir=tmp_path)

    assert mock_html_cls.call_count == 2
    assert mock_instance.write_pdf.call_count == 2
```

**Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_output/test_pdf_writer.py -v
```

Expected: `ERROR` — `src.output.pdf_writer` 모듈 없음

**Step 3: pdf_writer.py 구현**

`src/output/pdf_writer.py`:

```python
"""Generate daily PDF newsletters from Gold layer data using weasyprint."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _parse_key_points(article: dict) -> list[str]:
    kp = article.get("key_points", [])
    if isinstance(kp, str):
        try:
            kp = json.loads(kp)
        except (json.JSONDecodeError, TypeError):
            kp = []
    return kp if isinstance(kp, list) else []


def _split_sections(articles: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split articles into (databricks, ai_news, other_news) by quota 10/20/10."""
    db_articles = sorted(
        [a for a in articles if a.get("is_databricks_related")],
        key=lambda x: (-x.get("relevance_score", 0), -x.get("overall_score", 0)),
    )[:10]
    db_urls = {a["url"] for a in db_articles}

    remaining = sorted(
        [a for a in articles if a["url"] not in db_urls],
        key=lambda x: -x.get("overall_score", 0),
    )
    ai_news = remaining[:20]
    other_news = remaining[20:][:10]

    return db_articles, ai_news, other_news


def _render_html(
    ai_news: list[dict],
    databricks_news: list[dict],
    other_news: list[dict],
    title_suffix: str,
    date_str: str,
    total_collected: int,
) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("digest.html.j2")
    return template.render(
        date=date_str,
        title_suffix=title_suffix,
        ai_news=ai_news,
        databricks_news=databricks_news,
        other_news=other_news,
        total_collected=total_collected,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M KST"),
    )


def build_ai_html(
    articles: list[dict],
    ingestion_date: date,
    total_collected: int,
) -> str:
    """Build HTML string for AI hot news PDF (top 20 AI articles)."""
    for a in articles:
        a["key_points"] = _parse_key_points(a)
    _, ai_news, _ = _split_sections(articles)
    return _render_html(
        ai_news=ai_news,
        databricks_news=[],
        other_news=[],
        title_suffix="AI 핫뉴스 TOP 20",
        date_str=ingestion_date.strftime("%Y-%m-%d"),
        total_collected=total_collected,
    )


def build_db_html(
    articles: list[dict],
    ingestion_date: date,
    total_collected: int,
) -> str:
    """Build HTML string for Databricks + Other PDF (top 10 each)."""
    for a in articles:
        a["key_points"] = _parse_key_points(a)
    db_articles, _, other_news = _split_sections(articles)
    return _render_html(
        ai_news=[],
        databricks_news=db_articles,
        other_news=other_news,
        title_suffix="Databricks & 기타 뉴스",
        date_str=ingestion_date.strftime("%Y-%m-%d"),
        total_collected=total_collected,
    )


def write_pdfs(
    articles: list[dict],
    total_collected: int,
    ingestion_date: date | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Render and write two PDF files. Returns list of output paths."""
    from weasyprint import HTML

    if ingestion_date is None:
        ingestion_date = date.today()
    if output_dir is None:
        output_dir = settings.digests_path

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = ingestion_date.strftime("%Y-%m-%d")
    paths: list[Path] = []

    # PDF 1: AI hot news (20개)
    ai_html = build_ai_html(articles, ingestion_date, total_collected)
    ai_path = output_dir / f"{date_str}-digest-ai.pdf"
    HTML(string=ai_html).write_pdf(str(ai_path))
    logger.info("pdf_written", path=str(ai_path), type="ai")
    paths.append(ai_path)

    # PDF 2: Databricks (10개) + Other (10개)
    db_html = build_db_html(articles, ingestion_date, total_collected)
    db_path = output_dir / f"{date_str}-digest-db.pdf"
    HTML(string=db_html).write_pdf(str(db_path))
    logger.info("pdf_written", path=str(db_path), type="db")
    paths.append(db_path)

    return paths
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_output/test_pdf_writer.py -v
```

Expected: `PASSED` 8건

**Step 5: 커밋**

```bash
git add src/output/pdf_writer.py tests/test_output/test_pdf_writer.py
git commit -m "feat: implement pdf_writer with two-PDF newsletter output"
```

---

### Task 4: run_daily.py 업데이트 (top_n=40, write_pdfs 호출)

**Files:**
- Modify: `src/run_daily.py`

변경 사항:
1. `top_n=20` → `top_n=40` (silver_to_gold 호출)
2. `top_urls` 요약 대상 20 → 40개
3. Step 6: `write_digest` → `write_pdfs` 호출
4. import 정리 (`markdown_writer` 삭제, `pdf_writer` 추가)

**Step 1: run_daily.py 수정**

`src/run_daily.py` 전체 내용으로 교체:

```python
"""Daily pipeline orchestrator: collect → bronze → silver → gold → PDF digest."""
import asyncio
import sys
from datetime import date

import structlog

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.ingestion.run_all import run_all_collectors
from src.output.pdf_writer import write_pdfs
from src.pipeline.bronze import write_bronze
from src.pipeline.gold import read_gold, silver_to_gold
from src.pipeline.silver import bronze_to_silver
from src.pipeline.spark_session import get_spark, stop_spark

setup_logging()
logger = get_logger("run_daily")


async def run_pipeline(
    ingestion_date: date | None = None,
    use_mock_scores: bool = False,
    skip_podcast: bool = False,
) -> None:
    if ingestion_date is None:
        ingestion_date = date.today()

    logger.info("pipeline_start", date=str(ingestion_date))

    # ── Step 1: Collect ──────────────────────────────────────────────────────
    logger.info("step1_collect")
    articles = await run_all_collectors()
    total_collected = len(articles)
    logger.info("collect_done", count=total_collected)

    # ── Step 2: Bronze ───────────────────────────────────────────────────────
    logger.info("step2_bronze")
    spark = get_spark()
    write_bronze(spark, articles, settings.bronze_path, ingestion_date)

    # ── Step 3: Silver ───────────────────────────────────────────────────────
    logger.info("step3_silver")
    silver_count = bronze_to_silver(
        spark, settings.bronze_path, settings.silver_path, ingestion_date
    )

    # ── Step 4: AI Scoring + Summarization ──────────────────────────────────
    # Memory management: stop Spark before loading Ollama (24GB ARM)
    logger.info("step4_ai_scoring", silver_articles=silver_count)
    stop_spark()

    from src.pipeline.silver import read_silver
    spark2 = get_spark()
    silver_df = read_silver(spark2, settings.silver_path, ingestion_date)
    silver_articles = [row.asDict() for row in silver_df.collect()]
    stop_spark()

    if use_mock_scores:
        scored, summaries = _mock_scores(silver_articles)
    else:
        scored, summaries = await _run_ai_pipeline(silver_articles)

    # ── Step 5: Gold ─────────────────────────────────────────────────────────
    logger.info("step5_gold")
    spark3 = get_spark()
    silver_to_gold(
        spark3,
        settings.silver_path,
        settings.gold_path,
        ingestion_date,
        scored,
        summaries,
        top_n=40,
    )

    # ── Step 6: PDF Digest ───────────────────────────────────────────────────
    logger.info("step6_pdf")
    from src.pipeline.gold import read_gold
    gold_df = read_gold(spark3, settings.gold_path, ingestion_date, digest_only=True)
    digest_articles = [row.asDict() for row in gold_df.collect()]
    stop_spark()

    pdf_paths = write_pdfs(digest_articles, total_collected, ingestion_date)

    # ── Step 7: Podcast ──────────────────────────────────────────────────────
    logger.info("step7_podcast")
    if use_mock_scores or skip_podcast:
        logger.info("podcast_skipped", reason="mock_mode_or_skip_flag")
    else:
        from src.agents.scriptwriter import ScriptWriter
        from src.output.podcast_producer import PodcastProducer
        from src.agents.router import LLMRouter

        router_for_podcast = LLMRouter()
        gemini = router_for_podcast.get_client("scriptwriting")
        writer = ScriptWriter(gemini)
        script = await writer.generate(digest_articles, ingestion_date)

        if script.turns:
            producer = PodcastProducer()
            podcast_path = await producer.produce(script, ingestion_date)
            print(f"\n🎙️  Podcast saved: {podcast_path}  ({script.estimated_minutes} min)")
        else:
            logger.warning("podcast_empty_script")

    logger.info(
        "pipeline_complete",
        date=str(ingestion_date),
        collected=total_collected,
        silver=silver_count,
        digest_articles=len(digest_articles),
    )
    for p in pdf_paths:
        print(f"\n📄 PDF saved: {p}")


async def _run_ai_pipeline(
    silver_articles: list[dict],
) -> tuple[list[dict], dict]:
    from src.agents.router import LLMRouter
    from src.agents.scorer import score_batch
    from src.agents.summarizer import summarize_batch

    router = LLMRouter()
    health = await router.check_all()

    # Scoring: Ollama preferred, mock fallback
    if health.get("ollama"):
        ollama = router.get_client("scoring")
        scored = await score_batch(ollama, silver_articles, top_n=40)
    else:
        logger.warning("ollama_unavailable_using_mock_scores")
        scored, _ = _mock_scores(silver_articles)

    # Summarization: Gemini (independent of Ollama)
    summaries: dict = {}
    if health.get("gemini"):
        top_urls = {s["url"] for s in sorted(scored, key=lambda x: -x["overall_score"])[:40]}
        top_articles = [a for a in silver_articles if a["url"] in top_urls]
        gemini = router.get_client("summarization")
        summaries = await summarize_batch(gemini, top_articles)
    else:
        logger.warning("gemini_unavailable_skipping_summaries")

    return scored, summaries


def _mock_scores(articles: list[dict]) -> tuple[list[dict], dict]:
    """Fallback mock scores when Ollama is unavailable."""
    import random
    random.seed(42)
    scored = []
    summaries = {}
    for a in articles:
        scored.append({
            "url": a["url"],
            "overall_score": round(random.uniform(4.0, 8.5), 1),
            "relevance_score": round(
                random.uniform(6.0, 9.5) if a.get("is_databricks_related") else random.uniform(1.0, 5.0),
                1,
            ),
            "novelty_score": round(random.uniform(4.0, 9.0), 1),
            "one_line_summary": a["title"][:80],
            "reasoning": "",
        })
        summaries[a["url"]] = {
            "full_summary": f"{a['title']} — 실제 운영 시 Gemini가 한국어 요약을 생성합니다.",
            "key_points": [],
            "tech_keywords": [],
        }
    return scored, summaries


if __name__ == "__main__":
    mock = "--mock" in sys.argv
    no_podcast = "--no-podcast" in sys.argv
    asyncio.run(run_pipeline(use_mock_scores=mock, skip_podcast=no_podcast))
```

**Step 2: import 오류 없는지 확인**

```bash
uv run python -c "from src.run_daily import run_pipeline; print('OK')"
```

Expected: `OK`

**Step 3: 전체 테스트 통과 확인**

```bash
uv run pytest tests/ -v --ignore=tests/test_pipeline/test_gold_quota.py -x
```

Expected: 기존 테스트 전부 PASS (새 코드가 기존 테스트 깨지 않음)

**Step 4: 커밋**

```bash
git add src/run_daily.py
git commit -m "feat: wire write_pdfs into run_daily, expand scoring to top_n=40"
```

---

### Task 5: weasyprint 의존성 추가 + 마크다운 파일 삭제

**Files:**
- Modify: `pyproject.toml`
- Delete: `src/output/markdown_writer.py`
- Delete: `src/output/templates/digest.md.j2`

**Step 1: weasyprint 설치**

```bash
uv add weasyprint
```

Expected: `pyproject.toml`에 `weasyprint` 추가됨

**Step 2: 마크다운 파일 삭제**

```bash
rm src/output/markdown_writer.py
rm src/output/templates/digest.md.j2
```

**Step 3: 삭제된 파일 참조 남아있는지 확인**

```bash
grep -r "markdown_writer\|digest\.md\.j2" src/ tests/
```

Expected: 출력 없음 (참조 없음)

**Step 4: 전체 테스트 최종 통과 확인**

```bash
uv run pytest tests/ -v
```

Expected: 모든 테스트 PASS, markdown_writer 관련 import 오류 없음

**Step 5: Oracle Cloud 폰트 설치 명령을 scripts/setup.sh에 추가**

`scripts/setup.sh` (또는 `scripts/setup_ollama.sh`)에 아래 줄 추가:

```bash
# PDF 한글 폰트
sudo apt install -y fonts-noto-cjk
```

**Step 6: 최종 커밋**

```bash
git add pyproject.toml scripts/
git rm src/output/markdown_writer.py src/output/templates/digest.md.j2
git commit -m "chore: add weasyprint dep, remove markdown_writer (replaced by pdf_writer)"
```

---

## 전체 테스트 실행

```bash
uv run pytest tests/ -v
```

Expected: 전체 PASS. 새로 추가된 테스트:
- `tests/test_pipeline/test_gold_quota.py` — 2건
- `tests/test_output/test_pdf_writer.py` — 8건
