"""Tech glossary agent — extracts new terms from articles and archives definitions."""
from __future__ import annotations

import json
from dataclasses import dataclass
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
        """Full pipeline: load -> find new -> define -> save. Returns new terms only."""
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
