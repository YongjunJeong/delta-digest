"""Raw ingestion must preserve source evidence before Spark writes it."""
import json
from datetime import date, datetime

from src.common.models import RawArticle
from src.pipeline.bronze import articles_to_rows


def test_bronze_rows_preserve_raw_evidence_and_partition_date():
    collected = datetime(2026, 10, 9, 12, 0)
    article = RawArticle(
        source_name="Synthetic Feed", source_type="rss", title="Delta 예제",
        url="https://example.com/article", content="<p>Unmodified source</p>",
        collected_at=collected, raw_metadata={"tags": ["데이터"], "version": 1},
    )
    day = date(2026, 10, 9)
    row, = articles_to_rows([article], day)
    assert row["url"] == article.url
    assert row["content"] == article.content
    assert row["collected_at"] == collected
    assert row["published_at"] is None
    assert row["ingestion_date"] == day
    assert json.loads(row["raw_metadata"]) == article.raw_metadata
    assert article.raw_metadata == {"tags": ["데이터"], "version": 1}
    assert articles_to_rows([], day) == []
