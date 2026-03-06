"""Tests for Gold layer quota selection logic."""
import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.gold import _select_digest_urls


def _make_mock_df(rows: list[dict]):
    """Build a MagicMock that mimics the Spark DataFrame calls used by _select_digest_urls."""
    def fake_filter(cond):
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
    rows = [{"url": f"http://example.com/{i}", "is_databricks_related": i < 15} for i in range(50)]
    mock_df = _make_mock_df(rows)

    # Patch pyspark col() so it doesn't require an active SparkContext
    with patch("src.pipeline.gold.col", side_effect=lambda name: MagicMock(name=name)):
        result = _select_digest_urls(mock_df, top_databricks=10, top_ai=20, top_other=10)
    assert len(result) <= 40


def test_select_digest_urls_default_quota():
    """_select_digest_urls default args are now 10/20/10."""
    sig = inspect.signature(_select_digest_urls)
    assert sig.parameters["top_databricks"].default == 10
    assert sig.parameters["top_ai"].default == 20
    assert sig.parameters["top_other"].default == 10
