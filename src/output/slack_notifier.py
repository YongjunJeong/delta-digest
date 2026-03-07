"""Slack notification — success PDF delivery and failure alerts."""
from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class SlackNotifier:
    def __init__(self, token: str, channel_id: str) -> None:
        from slack_sdk import WebClient
        self._client = WebClient(token=token)
        self._channel = channel_id

    def notify_success(
        self,
        ingestion_date: str,
        stats: dict,
        pdf_paths: list[Path],
        new_since_yesterday: int,
    ) -> None:
        """Post success message and upload PDFs."""
        text = (
            f":white_check_mark: *Delta Digest {ingestion_date}*\n"
            f"수집 {stats['collected']}건 → 선별 {stats['digest']}건 "
            f"(DB {stats['db']} + AI {stats['ai']} + 기타 {stats['other']})\n"
            f"어제 없던 신규 기사 {new_since_yesterday}건"
        )
        self._client.chat_postMessage(channel=self._channel, text=text)

        for path in pdf_paths:
            if Path(path).exists():
                with open(path, "rb") as f:
                    self._client.files_upload_v2(
                        channel=self._channel,
                        file=f,
                        filename=Path(path).name,
                    )
        logger.info("slack_success_sent", date=ingestion_date, pdfs=len(pdf_paths))

    def upload_file(self, path: Path, message: str) -> None:
        """Upload a single file with a message."""
        if not Path(path).exists():
            return
        self._client.chat_postMessage(channel=self._channel, text=message)
        with open(path, "rb") as f:
            self._client.files_upload_v2(
                channel=self._channel,
                file=f,
                filename=Path(path).name,
            )
        logger.info("slack_file_uploaded", filename=Path(path).name)

    def notify_failure(self, ingestion_date: str, step: str, error: str) -> None:
        """Post failure alert."""
        text = (
            f":x: *Delta Digest 실패 ({ingestion_date})* — `{step}`\n"
            f"```{error[:500]}```"
        )
        try:
            self._client.chat_postMessage(channel=self._channel, text=text)
            logger.info("slack_failure_sent", date=ingestion_date, step=step)
        except Exception as e:
            logger.error("slack_failure_notify_error", error=str(e))
