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

try:
    from weasyprint import HTML
except ImportError:
    HTML = None  # type: ignore


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
