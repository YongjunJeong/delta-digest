"""Generate daily Markdown digest from Gold layer data."""
import json
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _parse_key_points(article: dict) -> list[str]:
    """Parse key_points from JSON string or list."""
    kp = article.get("key_points", [])
    if isinstance(kp, str):
        try:
            kp = json.loads(kp)
        except (json.JSONDecodeError, TypeError):
            kp = []
    return kp if isinstance(kp, list) else []


def _split_sections(articles: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split digest articles into three sections by selection quota.

    Returns: (databricks_news, ai_news, other_news)
    Databricks: is_databricks_related=True, sorted by relevance_score desc
    AI hot news: remainder sorted by overall_score desc, up to 10
    Other: the rest
    """
    db_articles = sorted(
        [a for a in articles if a.get("is_databricks_related")],
        key=lambda x: (-x.get("relevance_score", 0), -x.get("overall_score", 0)),
    )[:5]
    db_urls = {a["url"] for a in db_articles}

    remaining = sorted(
        [a for a in articles if a["url"] not in db_urls],
        key=lambda x: -x.get("overall_score", 0),
    )
    ai_news = remaining[:10]
    other_news = remaining[10:]

    return db_articles, ai_news, other_news


def build_digest(
    articles: list[dict],
    total_collected: int,
    ingestion_date: date | None = None,
) -> str:
    """Render Jinja2 template with article data. Returns Markdown string."""
    if ingestion_date is None:
        ingestion_date = date.today()

    # Attach parsed key_points to each article
    for a in articles:
        a["key_points"] = _parse_key_points(a)

    databricks_news, ai_news, other_news = _split_sections(articles)

    # Source stats
    stats: dict[str, dict] = {}
    for a in articles:
        st = a.get("source_type", "unknown")
        if st not in stats:
            stats[st] = {"source_type": st, "total": 0, "selected": 0}
        stats[st]["total"] += 1
        if a.get("digest_included"):
            stats[st]["selected"] += 1
    source_stats = sorted(stats.values(), key=lambda x: x["total"], reverse=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
    template = env.get_template("digest.md.j2")

    return template.render(
        date=ingestion_date.strftime("%Y-%m-%d (%A)"),
        ai_news=ai_news,
        databricks_news=databricks_news,
        other_news=other_news,
        articles=articles,
        total_collected=total_collected,
        source_stats=source_stats,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M KST"),
    )


def write_digest(
    articles: list[dict],
    total_collected: int,
    ingestion_date: date | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Render and write digest Markdown file. Returns output path."""
    if ingestion_date is None:
        ingestion_date = date.today()
    if output_dir is None:
        output_dir = settings.digests_path

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ingestion_date.strftime('%Y-%m-%d')}-digest.md"

    content = build_digest(articles, total_collected, ingestion_date)
    output_path.write_text(content, encoding="utf-8")

    logger.info(
        "digest_written",
        path=str(output_path),
        articles=len(articles),
    )
    return output_path
