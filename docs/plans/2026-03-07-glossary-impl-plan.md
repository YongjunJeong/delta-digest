# Glossary Archiving Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 매일 뉴스 기사에서 기술 용어를 추출해 한 줄 정의와 함께 누적 아카이빙하고, 별도 glossary.pdf를 생성한다.

**Architecture:** GlossaryAgent가 Gold layer 상위 20개 기사의 tech_keywords를 수집하고 기존 glossary.json과 비교해 신규 용어만 Gemini에 배치 전송한다. 결과를 glossary.json에 append하고 weasyprint로 YYYY-MM-DD-glossary.pdf를 생성한다.

**Tech Stack:** Gemini 2.0 Flash (LLMClient), weasyprint, Jinja2, json (stdlib), pytest

---

### Task 1: config.py에 glossary_path 추가

**Files:**
- Modify: `src/common/config.py`
- Test: `tests/test_agents/test_glossary_agent.py` (이후 Task에서 사용)

**Step 1: 실패하는 테스트 작성**

`tests/test_agents/test_glossary_agent.py` 파일을 새로 만든다:

```python
"""Tests for GlossaryAgent."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.config import settings


def test_glossary_path_property():
    """settings.glossary_path returns outputs/glossary."""
    assert settings.glossary_path == settings.output_dir / "glossary"
```

**Step 2: 테스트 실패 확인**

```bash
cd /Users/yongjun/Desktop/Portfolio/delta-digest
uv run pytest tests/test_agents/test_glossary_agent.py::test_glossary_path_property -v
```

Expected: `FAILED` — `Settings object has no attribute 'glossary_path'`

**Step 3: config.py 수정**

`src/common/config.py`에 `podcasts_path` 프로퍼티 아래에 추가:

```python
@property
def glossary_path(self) -> Path:
    return self.output_dir / "glossary"
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_agents/test_glossary_agent.py::test_glossary_path_property -v
```

Expected: `PASSED`

**Step 5: 커밋**

```bash
git add src/common/config.py tests/test_agents/test_glossary_agent.py
git commit -m "feat: add glossary_path to settings"
```

---

### Task 2: GlossaryAgent 구현 (TDD)

**Files:**
- Create: `src/agents/glossary_agent.py`
- Modify: `tests/test_agents/test_glossary_agent.py` (테스트 추가)

**Step 1: 테스트 추가 (test_glossary_agent.py에 append)**

```python
from src.agents.glossary_agent import GlossaryAgent, GlossaryTerm


# ── find_new_terms ────────────────────────────────────────────────────────────

def test_find_new_terms_filters_existing(tmp_path):
    """find_new_terms returns only terms not already in archive."""
    archive = {"RAG": {"definition": "...", "first_seen": "2026-03-01"}}
    (tmp_path / "glossary.json").write_text(
        json.dumps(archive), encoding="utf-8"
    )
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    articles = [{"tech_keywords": json.dumps(["RAG", "LoRA", "RLHF"])}]
    new_terms = agent.find_new_terms(articles)

    assert "RAG" not in new_terms
    assert "LoRA" in new_terms
    assert "RLHF" in new_terms


def test_find_new_terms_case_insensitive(tmp_path):
    """find_new_terms treats 'rag' and 'RAG' as the same term."""
    archive = {"RAG": {"definition": "...", "first_seen": "2026-03-01"}}
    (tmp_path / "glossary.json").write_text(
        json.dumps(archive), encoding="utf-8"
    )
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    articles = [{"tech_keywords": json.dumps(["rag", "RAG", "Rag"])}]
    new_terms = agent.find_new_terms(articles)

    assert new_terms == []


def test_find_new_terms_handles_empty_archive(tmp_path):
    """find_new_terms works when archive file does not exist yet."""
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()  # no file exists

    articles = [{"tech_keywords": json.dumps(["Delta Lake", "Spark"])}]
    new_terms = agent.find_new_terms(articles)

    assert "Delta Lake" in new_terms
    assert "Spark" in new_terms


def test_find_new_terms_parses_list_and_json_string(tmp_path):
    """find_new_terms handles tech_keywords as both list and JSON string."""
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    articles = [
        {"tech_keywords": ["LLM", "RAG"]},               # already a list
        {"tech_keywords": json.dumps(["LoRA", "DPO"])},   # JSON string
        {"tech_keywords": None},                           # missing/None
    ]
    new_terms = agent.find_new_terms(articles)

    assert set(new_terms) == {"LLM", "RAG", "LoRA", "DPO"}


# ── save_archive ──────────────────────────────────────────────────────────────

def test_save_archive_persists_to_json(tmp_path):
    """save_archive writes new terms to glossary.json."""
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    new_defs = {"RAG": "검색 증강 생성.", "LoRA": "저랭크 적응 기법."}
    agent.save_archive(new_defs, today="2026-03-07")

    saved = json.loads((tmp_path / "glossary.json").read_text(encoding="utf-8"))
    assert saved["RAG"]["definition"] == "검색 증강 생성."
    assert saved["RAG"]["first_seen"] == "2026-03-07"
    assert "LoRA" in saved


def test_save_archive_returns_glossary_terms(tmp_path):
    """save_archive returns GlossaryTerm list with is_new=True."""
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    result = agent.save_archive({"RAG": "정의."}, today="2026-03-07")

    assert len(result) == 1
    assert result[0].term == "RAG"
    assert result[0].is_new is True


# ── update (integration) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_skips_gemini_when_no_new_terms(tmp_path):
    """update() does NOT call Gemini if all terms already archived."""
    archive = {"RAG": {"definition": "...", "first_seen": "2026-03-01"}}
    (tmp_path / "glossary.json").write_text(json.dumps(archive), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.generate_json = AsyncMock()
    agent = GlossaryAgent(client=mock_client, glossary_dir=tmp_path)

    articles = [{"tech_keywords": json.dumps(["RAG"])}]
    result = await agent.update(articles, ingestion_date=date(2026, 3, 7))

    assert result == []
    mock_client.generate_json.assert_not_called()


@pytest.mark.asyncio
async def test_update_calls_gemini_for_new_terms(tmp_path):
    """update() calls Gemini once and returns new GlossaryTerm list."""
    mock_client = MagicMock()
    mock_client.generate_json = AsyncMock(return_value={"LoRA": "저랭크 적응 기법이다."})
    agent = GlossaryAgent(client=mock_client, glossary_dir=tmp_path)

    articles = [{"tech_keywords": json.dumps(["LoRA"])}]
    result = await agent.update(articles, ingestion_date=date(2026, 3, 7))

    assert len(result) == 1
    assert result[0].term == "LoRA"
    mock_client.generate_json.assert_called_once()


# ── all_terms ─────────────────────────────────────────────────────────────────

def test_all_terms_sorted_alphabetically(tmp_path):
    """all_terms returns GlossaryTerm list sorted by term name."""
    archive = {
        "Spark": {"definition": "스파크.", "first_seen": "2026-03-01"},
        "RAG": {"definition": "RAG.", "first_seen": "2026-03-02"},
        "LoRA": {"definition": "LoRA.", "first_seen": "2026-03-03"},
    }
    (tmp_path / "glossary.json").write_text(json.dumps(archive), encoding="utf-8")

    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    terms = agent.all_terms
    names = [t.term for t in terms]
    assert names == sorted(names)
```

**Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_agents/test_glossary_agent.py -v --ignore-glob="*test_glossary_path*"
```

Expected: `ERROR` — `cannot import name 'GlossaryAgent'`

**Step 3: glossary_agent.py 구현**

`src/agents/glossary_agent.py`:

```python
"""Tech glossary agent — extracts new terms from articles and archives definitions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import structlog

from src.agents.llm_client import LLMClient

logger = structlog.get_logger(__name__)

_DEFINITION_SYSTEM = (
    "당신은 AI/데이터 엔지니어링 기술 용어 전문가입니다. "
    "반드시 유효한 JSON만 반환하세요."
)

_DEFINITION_PROMPT = """다음 AI/데이터 엔지니어링 기술 용어 각각에 대해 한국어로 한 줄 정의를 작성하세요.
기술 용어 원문(영어)은 그대로 유지하고, "~다" 체로 간결하게 1-2문장 작성하세요.

용어 목록: {terms}

반드시 아래 JSON만 반환하세요:
{{"용어1": "정의...", "용어2": "정의..."}}"""


@dataclass
class GlossaryTerm:
    term: str
    definition: str
    first_seen: str  # "YYYY-MM-DD"
    is_new: bool = False


class GlossaryAgent:
    def __init__(self, client: LLMClient, glossary_dir: Path):
        self._client = client
        self._archive_path = glossary_dir / "glossary.json"
        self._archive: dict[str, dict] = {}

    def load_archive(self) -> None:
        """Load existing glossary from JSON file."""
        if self._archive_path.exists():
            self._archive = json.loads(
                self._archive_path.read_text(encoding="utf-8")
            )
        else:
            self._archive = {}

    def find_new_terms(self, articles: list[dict]) -> list[str]:
        """Collect tech_keywords from articles; return only terms not in archive."""
        collected: set[str] = set()
        for a in articles:
            kw = a.get("tech_keywords") or []
            if isinstance(kw, str):
                try:
                    kw = json.loads(kw)
                except (json.JSONDecodeError, TypeError):
                    kw = []
            for term in kw:
                if isinstance(term, str) and term.strip():
                    collected.add(term.strip())

        archived_lower = {k.lower() for k in self._archive}
        return sorted(t for t in collected if t.lower() not in archived_lower)

    async def generate_definitions(self, terms: list[str]) -> dict[str, str]:
        """Call Gemini once to get one-line Korean definitions for all terms."""
        if not terms:
            return {}
        prompt = _DEFINITION_PROMPT.format(terms=", ".join(terms))
        result = await self._client.generate_json(
            prompt=prompt, system=_DEFINITION_SYSTEM
        )
        return result if isinstance(result, dict) else {}

    def save_archive(
        self, new_definitions: dict[str, str], today: str
    ) -> list[GlossaryTerm]:
        """Persist new terms to archive. Returns list of new GlossaryTerm."""
        new_terms: list[GlossaryTerm] = []
        for term, definition in new_definitions.items():
            self._archive[term] = {"definition": definition, "first_seen": today}
            new_terms.append(
                GlossaryTerm(term=term, definition=definition, first_seen=today, is_new=True)
            )

        self._archive_path.parent.mkdir(parents=True, exist_ok=True)
        self._archive_path.write_text(
            json.dumps(self._archive, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info("glossary_archive_saved", total=len(self._archive))
        return new_terms

    @property
    def all_terms(self) -> list[GlossaryTerm]:
        """All archived terms sorted alphabetically."""
        return [
            GlossaryTerm(term=t, definition=v["definition"], first_seen=v["first_seen"])
            for t, v in sorted(self._archive.items())
        ]

    async def update(
        self,
        articles: list[dict],
        ingestion_date: date | None = None,
    ) -> list[GlossaryTerm]:
        """Full pipeline: load → find new → define → save. Returns new terms only."""
        if ingestion_date is None:
            ingestion_date = date.today()
        today_str = str(ingestion_date)

        self.load_archive()
        new_term_names = self.find_new_terms(articles)

        if not new_term_names:
            logger.info("glossary_no_new_terms", total_archived=len(self._archive))
            return []

        definitions = await self.generate_definitions(new_term_names)
        new_terms = self.save_archive(definitions, today_str)

        logger.info(
            "glossary_updated",
            new_terms=len(new_terms),
            total=len(self._archive),
        )
        return new_terms
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_agents/test_glossary_agent.py -v
```

Expected: `PASSED` 10건

**Step 5: 전체 테스트 통과 확인**

```bash
uv run pytest tests/ -v
```

Expected: 모두 PASS

**Step 6: 커밋**

```bash
git add src/agents/glossary_agent.py tests/test_agents/test_glossary_agent.py
git commit -m "feat: implement GlossaryAgent with archive dedup and Gemini batch definitions"
```

---

### Task 3: glossary.html.j2 템플릿 생성

**Files:**
- Create: `src/output/templates/glossary.html.j2`

**Step 1: 템플릿 파일 생성**

`src/output/templates/glossary.html.j2`:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>Delta Digest 용어집 {{ date }}</title>
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
      border-bottom: 3px solid #7c3aed;
      padding-bottom: 10px;
      margin-bottom: 18px;
    }
    .header-top { display: flex; justify-content: space-between; align-items: baseline; }
    .header h1 { font-size: 20pt; color: #1a1a2e; letter-spacing: -0.5px; }
    .badge {
      font-size: 9pt; font-weight: bold; color: #7c3aed;
      background: #f5f3ff; padding: 3px 8px; border-radius: 12px;
    }
    .meta { font-size: 8.5pt; color: #6b7280; margin-top: 4px; }
    .section-title {
      font-size: 12pt; font-weight: bold;
      padding: 5px 10px;
      margin: 20px 0 10px;
      border-left: 4px solid #7c3aed;
      background: #f5f3ff;
      color: #5b21b6;
    }
    .section-title.archive {
      border-left-color: #6b7280;
      background: #f9fafb;
      color: #374151;
    }
    .term-card {
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 9px 12px;
      margin-bottom: 8px;
      break-inside: avoid;
    }
    .term-name { font-size: 10.5pt; font-weight: bold; color: #7c3aed; margin-bottom: 3px; }
    .term-def { font-size: 9pt; color: #374151; line-height: 1.55; }
    .alpha-group { margin-bottom: 10px; break-inside: avoid; }
    .alpha-label {
      font-size: 8pt; font-weight: bold; color: #7c3aed;
      background: #f5f3ff; padding: 1px 6px; border-radius: 4px;
      display: inline-block; margin-bottom: 4px;
    }
    .archive-item { font-size: 8.5pt; margin-bottom: 4px; padding-left: 8px; }
    .archive-item .a-term { font-weight: bold; color: #1a1a2e; }
    .archive-item .a-def { color: #4b5563; }
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
    <h1>Delta Digest 용어집</h1>
    <span class="badge">오늘 신규 {{ new_terms | length }}개 · 누적 {{ total_count }}개</span>
  </div>
  <div class="meta">{{ date }}</div>
</div>

{% if new_terms %}
<div class="section-title">📚 오늘의 신규 용어 ({{ new_terms | length }}개)</div>
{% for term in new_terms %}
<div class="term-card">
  <div class="term-name">{{ term.term }}</div>
  <div class="term-def">{{ term.definition }}</div>
</div>
{% endfor %}
{% endif %}

{% if all_terms %}
<div class="section-title archive">📖 전체 용어 아카이브 ({{ all_terms | length }}개 · 가나다/ABC순)</div>
{% set ns = namespace(current_group='') %}
{% for term in all_terms %}
{% set first_char = term.term[0] | upper %}
{% if first_char != ns.current_group %}
{% if ns.current_group != '' %}</div>{% endif %}
<div class="alpha-group">
<span class="alpha-label">{{ first_char }}</span><br>
{% set ns.current_group = first_char %}
{% endif %}
<div class="archive-item">
  <span class="a-term">{{ term.term }}</span>
  <span class="a-def"> — {{ term.definition }}</span>
</div>
{% endfor %}
{% if ns.current_group != '' %}</div>{% endif %}
{% endif %}

<div class="footer">
  Generated by delta-digest at {{ generated_at }}
</div>

</body>
</html>
```

**Step 2: Jinja2 렌더링 sanity check**

```bash
uv run python -c "
from jinja2 import Environment, FileSystemLoader
from src.agents.glossary_agent import GlossaryTerm
env = Environment(loader=FileSystemLoader('src/output/templates'), autoescape=True)
tmpl = env.get_template('glossary.html.j2')
new_terms = [GlossaryTerm(term='RAG', definition='검색 증강 생성이다.', first_seen='2026-03-07', is_new=True)]
all_terms = [GlossaryTerm(term='RAG', definition='검색 증강 생성이다.', first_seen='2026-03-07')]
html = tmpl.render(date='2026-03-07', new_terms=new_terms, all_terms=all_terms, total_count=1, generated_at='2026-03-07 09:00 KST')
assert 'RAG' in html
assert '오늘의 신규 용어' in html
assert '전체 용어 아카이브' in html
print('Template OK, len:', len(html))
"
```

Expected: `Template OK, len: <숫자>`

**Step 3: 커밋**

```bash
git add src/output/templates/glossary.html.j2
git commit -m "feat: add glossary HTML template for PDF output"
```

---

### Task 4: pdf_writer.py에 write_glossary_pdf() 추가 (TDD)

**Files:**
- Modify: `src/output/pdf_writer.py`
- Modify: `tests/test_output/test_pdf_writer.py`

**Step 1: 테스트 추가 (test_pdf_writer.py 끝에 append)**

```python
# ── write_glossary_pdf ───────────────────────────────────────────────────────

def test_write_glossary_pdf_returns_correct_path(tmp_path):
    """write_glossary_pdf returns path with correct filename."""
    from src.agents.glossary_agent import GlossaryTerm
    from src.output.pdf_writer import write_glossary_pdf

    new_terms = [GlossaryTerm("RAG", "정의.", "2026-03-07", is_new=True)]
    all_terms = [GlossaryTerm("RAG", "정의.", "2026-03-07")]

    mock_html_cls = MagicMock()
    mock_html_cls.return_value.write_pdf = MagicMock()

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        path = write_glossary_pdf(new_terms, all_terms, date(2026, 3, 7), output_dir=tmp_path)

    assert path.name == "2026-03-07-glossary.pdf"


def test_write_glossary_pdf_calls_weasyprint_once(tmp_path):
    """write_glossary_pdf calls weasyprint exactly once."""
    from src.agents.glossary_agent import GlossaryTerm
    from src.output.pdf_writer import write_glossary_pdf

    new_terms = [GlossaryTerm("LoRA", "정의.", "2026-03-07", is_new=True)]
    all_terms = [GlossaryTerm("LoRA", "정의.", "2026-03-07")]

    mock_html_cls = MagicMock()
    mock_instance = MagicMock()
    mock_html_cls.return_value = mock_instance

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        write_glossary_pdf(new_terms, all_terms, date(2026, 3, 7), output_dir=tmp_path)

    assert mock_html_cls.call_count == 1
    assert mock_instance.write_pdf.call_count == 1
```

**Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_output/test_pdf_writer.py::test_write_glossary_pdf_returns_correct_path -v
```

Expected: `FAILED` — `cannot import name 'write_glossary_pdf'`

**Step 3: pdf_writer.py에 함수 추가**

`src/output/pdf_writer.py` 파일 끝에 추가:

```python
def write_glossary_pdf(
    new_terms: list,
    all_terms: list,
    ingestion_date: date | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Render and write glossary PDF. Returns output path."""
    if ingestion_date is None:
        ingestion_date = date.today()
    if output_dir is None:
        output_dir = settings.digests_path

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = ingestion_date.strftime("%Y-%m-%d")

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("glossary.html.j2")
    html = template.render(
        date=date_str,
        new_terms=new_terms,
        all_terms=all_terms,
        total_count=len(all_terms),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M KST"),
    )

    output_path = output_dir / f"{date_str}-glossary.pdf"
    HTML(string=html).write_pdf(str(output_path))
    logger.info("glossary_pdf_written", path=str(output_path), new_terms=len(new_terms))
    return output_path
```

**Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_output/test_pdf_writer.py -v
```

Expected: `PASSED` 11건 (기존 9 + 신규 2)

**Step 5: 커밋**

```bash
git add src/output/pdf_writer.py tests/test_output/test_pdf_writer.py
git commit -m "feat: add write_glossary_pdf to pdf_writer"
```

---

### Task 5: run_daily.py Step 6.5 추가

**Files:**
- Modify: `src/run_daily.py`

**Step 1: run_daily.py 수정**

`src/run_daily.py`에서 Step 6 PDF 블록 다음에 Step 6.5를 추가한다.

Step 6 블록 (현재):
```python
    # ── Step 6: PDF Digest ───────────────────────────────────────────────────────
    logger.info("step6_pdf")
    from src.pipeline.gold import read_gold
    gold_df = read_gold(spark3, settings.gold_path, ingestion_date, digest_only=True)
    digest_articles = [row.asDict() for row in gold_df.collect()]
    stop_spark()

    pdf_paths = write_pdfs(digest_articles, total_collected, ingestion_date)
```

Step 6.5를 그 뒤에 삽입:
```python
    # ── Step 6.5: Glossary ───────────────────────────────────────────────────────
    logger.info("step6_5_glossary")
    if not use_mock_scores and health.get("gemini"):
        from src.agents.glossary_agent import GlossaryAgent
        from src.output.pdf_writer import write_glossary_pdf

        top_articles = sorted(digest_articles, key=lambda x: -x.get("overall_score", 0))[:20]
        glossary_agent = GlossaryAgent(gemini, settings.glossary_path)
        new_terms = await glossary_agent.update(top_articles, ingestion_date)

        if new_terms:
            glossary_path = write_glossary_pdf(
                new_terms, glossary_agent.all_terms, ingestion_date
            )
            print(f"\n📚 Glossary saved: {glossary_path} ({len(new_terms)} new terms)")
        else:
            logger.info("glossary_pdf_skipped", reason="no_new_terms")
    else:
        logger.info("glossary_skipped", reason="mock_mode_or_gemini_unavailable")
```

주의: `health` 변수와 `gemini` 변수는 `_run_ai_pipeline` 내부에서만 사용됨.
`run_pipeline`에서 접근하려면 `_run_ai_pipeline`이 `health`와 `gemini`를 반환하거나,
Step 6.5를 위한 별도 클라이언트를 생성해야 한다.

현재 run_daily.py 구조상 `use_mock_scores=False`일 때 `_run_ai_pipeline` 내부에서만
`health`와 `gemini`를 갖고 있으므로, Step 6.5에서 독립적으로 Gemini 클라이언트를 만든다:

```python
    # ── Step 6.5: Glossary ───────────────────────────────────────────────────────
    logger.info("step6_5_glossary")
    if not use_mock_scores:
        from src.agents.glossary_agent import GlossaryAgent
        from src.agents.router import LLMRouter
        from src.output.pdf_writer import write_glossary_pdf

        glossary_router = LLMRouter()
        glossary_health = await glossary_router.check_all()
        if glossary_health.get("gemini"):
            gemini_client = glossary_router.get_client("summarization")
            top_articles = sorted(
                digest_articles, key=lambda x: -x.get("overall_score", 0)
            )[:20]
            glossary_agent = GlossaryAgent(gemini_client, settings.glossary_path)
            new_terms = await glossary_agent.update(top_articles, ingestion_date)

            if new_terms:
                glossary_path = write_glossary_pdf(
                    new_terms, glossary_agent.all_terms, ingestion_date
                )
                print(f"\n📚 Glossary saved: {glossary_path} ({len(new_terms)} new terms)")
            else:
                logger.info("glossary_pdf_skipped", reason="no_new_terms")
        else:
            logger.info("glossary_skipped", reason="gemini_unavailable")
    else:
        logger.info("glossary_skipped", reason="mock_mode")
```

**Step 2: import 확인**

`LLMRouter.check_all()`은 `{"gemini": bool, "ollama": bool}` dict를 반환한다. 위 코드에서 이미 사용 중.

**Step 3: import 오류 없는지 확인**

```bash
uv run python -c "from src.run_daily import run_pipeline; print('OK')"
```

Expected: `OK`

**Step 4: 전체 테스트 통과**

```bash
uv run pytest tests/ -v
```

Expected: 모두 PASS

**Step 5: final print 줄에 glossary_path 변수 참조 오류 없는지 확인**

Step 7 (Podcast) 블록에서 `output_path` 대신 `pdf_paths` 참조하는지 확인 —
이미 Task 4에서 수정됨.

**Step 6: 커밋**

```bash
git add src/run_daily.py
git commit -m "feat: add Step 6.5 glossary update to run_daily pipeline"
```

---

## 전체 테스트 실행

```bash
uv run pytest tests/ -v
```

Expected: 전체 PASS. 신규 추가된 테스트:
- `tests/test_agents/test_glossary_agent.py` — 10건
- `tests/test_output/test_pdf_writer.py` — 11건 (기존 9 + 신규 2)
