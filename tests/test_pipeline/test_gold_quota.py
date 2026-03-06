"""Tests for Gold layer quota selection logic."""
import inspect

from src.pipeline.gold import _select_digest_urls


def test_select_digest_urls_default_quota():
    """_select_digest_urls default args are 10/20/10 (total 40 articles)."""
    sig = inspect.signature(_select_digest_urls)
    assert sig.parameters["top_databricks"].default == 10
    assert sig.parameters["top_ai"].default == 20
    assert sig.parameters["top_other"].default == 10


def test_select_digest_urls_explicit_quota_returns_correct_count():
    """With explicit 10/20/10 args and enough data, returns exactly 40 URLs."""
    from unittest.mock import MagicMock, patch

    # Pool of 50 rows — exceeds total quota (10+20+10=40)
    POOL_SIZE = 50
    rows = [{"url": f"http://example.com/{i}"} for i in range(POOL_SIZE)]

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

    with patch("src.pipeline.gold.col", side_effect=lambda name: MagicMock(name=name)):
        result = _select_digest_urls(mock_df, top_databricks=10, top_ai=20, top_other=10)

    assert len(result) == 40  # exactly: 10 + 20 + 10
