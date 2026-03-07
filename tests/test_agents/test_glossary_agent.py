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
    agent.load_archive()

    articles = [{"tech_keywords": json.dumps(["Delta Lake", "Spark"])}]
    new_terms = agent.find_new_terms(articles)

    assert "Delta Lake" in new_terms
    assert "Spark" in new_terms


def test_find_new_terms_parses_list_and_json_string(tmp_path):
    """find_new_terms handles tech_keywords as both list and JSON string."""
    agent = GlossaryAgent(client=MagicMock(), glossary_dir=tmp_path)
    agent.load_archive()

    articles = [
        {"tech_keywords": ["LLM", "RAG"]},
        {"tech_keywords": json.dumps(["LoRA", "DPO"])},
        {"tech_keywords": None},
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
