"""Tests for PDF newsletter writer."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
    for i in range(12):
        articles.append(_make_article(f"http://db.com/{i}", f"DB 기사 {i}", is_db=True, relevance_score=9.0 - i * 0.1))
    for i in range(25):
        articles.append(_make_article(f"http://ai.com/{i}", f"AI 기사 {i}", overall_score=8.5 - i * 0.1))
    return articles


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


def test_build_ai_html_contains_ai_articles(sample_articles):
    """build_ai_html returns HTML containing AI article titles."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 7), total_collected=120)
    assert "AI 기사 0" in html
    assert "Delta Digest" in html
    assert "AI 핫뉴스" in html


def test_build_ai_html_excludes_db_section(sample_articles):
    """build_ai_html does NOT include Databricks section."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 7), total_collected=120)
    assert "Databricks" not in html


def test_build_db_html_contains_db_articles(sample_articles):
    """build_db_html returns HTML containing Databricks article titles."""
    from src.output.pdf_writer import build_db_html
    html = build_db_html(sample_articles, date(2026, 3, 7), total_collected=120)
    assert "DB 기사 0" in html
    assert "Databricks" in html


def test_build_db_html_excludes_ai_section(sample_articles):
    """build_db_html does NOT include AI 핫뉴스 section."""
    from src.output.pdf_writer import build_db_html
    html = build_db_html(sample_articles, date(2026, 3, 7), total_collected=120)
    assert "AI 핫뉴스" not in html


def test_key_points_parsed_from_json_string(sample_articles):
    """key_points stored as JSON string are parsed into list items in HTML."""
    from src.output.pdf_writer import build_ai_html
    html = build_ai_html(sample_articles, date(2026, 3, 7), total_collected=120)
    assert "포인트 1" in html


def test_write_pdfs_returns_two_paths(tmp_path, sample_articles):
    """write_pdfs returns exactly two Path objects with correct names."""
    mock_html_cls = MagicMock()
    mock_html_cls.return_value.write_pdf = MagicMock()

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        from src.output.pdf_writer import write_pdfs
        paths = write_pdfs(sample_articles, 120, date(2026, 3, 7), output_dir=tmp_path)

    assert len(paths) == 2
    assert paths[0].name == "2026-03-07-digest-ai.pdf"
    assert paths[1].name == "2026-03-07-digest-db.pdf"


def test_write_pdfs_calls_weasyprint_twice(tmp_path, sample_articles):
    """write_pdfs calls weasyprint HTML().write_pdf() exactly twice."""
    mock_html_cls = MagicMock()
    mock_instance = MagicMock()
    mock_html_cls.return_value = mock_instance

    with patch("src.output.pdf_writer.HTML", mock_html_cls):
        from src.output.pdf_writer import write_pdfs
        write_pdfs(sample_articles, 120, date(2026, 3, 7), output_dir=tmp_path)

    assert mock_html_cls.call_count == 2
    assert mock_instance.write_pdf.call_count == 2


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
