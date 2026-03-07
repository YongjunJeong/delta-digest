# Slack / Language Filter / Time Travel / Weekly Digest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slack 성공/실패 알림 + PDF 전송, 언어 필터, Delta time travel 통계, 주간 다이제스트 PDF, 로그 rotation 구현.

**Architecture:** SlackNotifier를 run_daily.py try/except로 감싸 실패 알림 처리. Silver 단계에 langdetect UDF 추가. Gold에 time travel 헬퍼 추가. 주간 파이프라인은 별도 run_weekly.py 스크립트.

**Tech Stack:** slack_sdk, langdetect, PySpark Delta time travel (VERSION AS OF), WeasyPrint

---

### Task 1: 의존성 추가 + Config 확장

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/common/config.py`
- Modify: `.env.example`

**Step 1: 패키지 추가**

```bash
uv add slack_sdk langdetect
```

Expected: pyproject.toml에 두 패키지 추가됨

**Step 2: config.py에 Slack 설정 추가**

`src/common/config.py`의 `# LLM` 블록 아래에 추가:

```python
# Slack
slack_bot_token: str = ""
slack_channel_id: str = ""
```

**Step 3: .env.example에 추가**

```
DIGEST_SLACK_BOT_TOKEN=xoxb-...
DIGEST_SLACK_CHANNEL_ID=C...
```

**Step 4: 서버 .env에 실제 값 저장**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 \
  "cd ~/delta-digest && echo 'DIGEST_SLACK_BOT_TOKEN=SLACK_TOKEN_REDACTED' >> .env && echo 'DIGEST_SLACK_CHANNEL_ID=C0AKJL06K2M' >> .env"
```

**Step 5: Commit**

```bash
git add pyproject.toml src/common/config.py .env.example
git commit -m "feat: add slack_sdk and langdetect deps, Slack config"
```

---

### Task 2: SlackNotifier 구현

**Files:**
- Create: `src/output/slack_notifier.py`

**Step 1: 파일 생성**

```python
"""Slack notification — success PDF delivery and failure alerts."""
from __future__ import annotations

import structlog
from pathlib import Path

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
```

**Step 2: Commit**

```bash
git add src/output/slack_notifier.py
git commit -m "feat: add SlackNotifier for PDF delivery and failure alerts"
```

---

### Task 3: Delta Time Travel — 신규 기사 카운트

**Files:**
- Modify: `src/pipeline/gold.py`

**Step 1: `count_new_since_yesterday` 함수 추가** (`read_gold` 함수 아래에 추가)

```python
def count_new_since_yesterday(
    spark: SparkSession,
    gold_path: str,
    ingestion_date: date,
) -> int:
    """Return count of digest articles that did not exist yesterday.

    Uses Delta time travel to compare today's digest URLs against yesterday's.
    Returns total digest count if yesterday's version doesn't exist.
    """
    from delta.tables import DeltaTable
    from pyspark.sql.functions import col

    today_df = read_gold(spark, gold_path, ingestion_date, digest_only=True)
    today_urls = {r.url for r in today_df.select("url").collect()}

    try:
        dt = DeltaTable.forPath(spark, gold_path)
        history = dt.history(2).collect()
        if len(history) < 2:
            return len(today_urls)

        yesterday_version = history[1].version
        yesterday_df = (
            spark.read.format("delta")
            .option("versionAsOf", yesterday_version)
            .load(gold_path)
            .filter(col("digest_included") == True)  # noqa: E712
        )
        yesterday_urls = {r.url for r in yesterday_df.select("url").collect()}
        return len(today_urls - yesterday_urls)
    except Exception as e:
        logger.warning("time_travel_failed", error=str(e))
        return len(today_urls)
```

**Step 2: Commit**

```bash
git add src/pipeline/gold.py
git commit -m "feat: add Delta time travel to count new articles since yesterday"
```

---

### Task 4: run_daily.py에 Slack 통합

**Files:**
- Modify: `src/run_daily.py`

**Step 1: SlackNotifier 초기화 + try/except 추가**

`run_pipeline` 함수를 아래 구조로 수정:

- 함수 맨 위에 notifier 초기화:
```python
from src.output.slack_notifier import SlackNotifier
notifier: SlackNotifier | None = None
if settings.slack_bot_token and settings.slack_channel_id:
    notifier = SlackNotifier(settings.slack_bot_token, settings.slack_channel_id)
current_step = "init"
```

- 각 스텝 시작 시 `current_step = "step1_collect"` 등으로 갱신 (기존 `logger.info("stepN_...")` 바로 아래에 추가)

- Step 6 digest 직후, `stop_spark()` 전에 time travel 카운트:
```python
# Time travel: count new articles since yesterday
from src.pipeline.gold import count_new_since_yesterday
new_since_yesterday = count_new_since_yesterday(spark3, settings.gold_path, ingestion_date)
logger.info("new_since_yesterday", count=new_since_yesterday)
stop_spark()
```

- `write_pdfs` 이후 Slack 성공 알림 (step6 끝부분):
```python
if notifier:
    notifier.notify_success(
        ingestion_date=str(ingestion_date),
        stats={
            "collected": total_collected,
            "digest": len(digest_articles),
            "db": sum(1 for a in digest_articles if a.get("is_databricks_related")),
            "ai": sum(1 for a in digest_articles if not a.get("is_databricks_related")),
            "other": 0,
        },
        pdf_paths=pdf_paths,
        new_since_yesterday=new_since_yesterday,
    )
```

- 함수 전체를 `try/except Exception as e:` 로 감싸고, except 블록에:
```python
    logger.error("pipeline_failed", step=current_step, error=str(e))
    if notifier:
        notifier.notify_failure(str(ingestion_date), current_step, str(e))
    raise
```

**Step 2: Commit**

```bash
git add src/run_daily.py
git commit -m "feat: integrate Slack success/failure notifications into daily pipeline"
```

---

### Task 5: Silver 언어 필터

**Files:**
- Modify: `src/pipeline/silver.py`

**Step 1: langdetect UDF 추가** (기존 UDF 블록 아래에 추가)

```python
def _is_english_or_korean(title: str | None, content: str | None) -> bool:
    """Return True if article is in English or Korean. Unknown → keep."""
    try:
        from langdetect import detect, LangDetectException
        text = f"{title or ''} {content or ''}"[:500]
        if len(text.strip()) < 20:
            return True  # too short to detect — keep
        lang = detect(text)
        return lang in ("en", "ko")
    except Exception:
        return True  # detection failed — keep

lang_filter_udf = udf(_is_english_or_korean, BooleanType())
```

**Step 2: `bronze_to_silver` 필터 체인에 언어 필터 추가**

기존 `.filter(col("word_count") >= min_word_count)` 줄 아래에 추가:
```python
.filter(lang_filter_udf(col("title"), col("clean_content")))
```

**Step 3: Commit**

```bash
git add src/pipeline/silver.py
git commit -m "feat: filter non-English/Korean articles in Silver layer"
```

---

### Task 6: 로그 Rotation

**Files:**
- 서버 crontab 수정

**Step 1: 서버 crontab에 rotation 추가**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 \
  "crontab -l | { cat; echo '0 3 * * * find ~/delta-digest/outputs/logs -name \"*.log\" -mtime +30 -delete'; } | crontab -"
```

매일 KST 12:00 (UTC 03:00)에 30일 이상 된 로그 파일 삭제.

**Step 2: 확인**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 "crontab -l"
```

Expected: 기존 daily cron + 새 rotation cron 2줄 표시.

---

### Task 7: 주간 다이제스트

**Files:**
- Create: `src/run_weekly.py`
- Modify: 서버 crontab

**Step 1: `src/run_weekly.py` 생성**

```python
"""Weekly digest: aggregate 7 days of Gold data into a single PDF."""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

import structlog

from src.common.config import settings
from src.common.logging import setup_logging, get_logger
from src.pipeline.gold import read_gold
from src.pipeline.spark_session import get_spark, stop_spark
from src.output.pdf_writer import write_pdfs

setup_logging()
logger = get_logger("run_weekly")


async def run_weekly(reference_date: date | None = None) -> None:
    if reference_date is None:
        reference_date = date.today()

    week_start = reference_date - timedelta(days=6)
    logger.info("weekly_start", from_date=str(week_start), to_date=str(reference_date))

    spark = get_spark()

    # Collect digest articles for the past 7 days
    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for i in range(7):
        d = week_start + timedelta(days=i)
        try:
            df = read_gold(spark, settings.gold_path, d, digest_only=True)
            rows = [r.asDict() for r in df.collect()]
            for row in rows:
                if row["url"] not in seen_urls:
                    seen_urls.add(row["url"])
                    all_articles.append(row)
        except Exception:
            logger.warning("weekly_date_missing", date=str(d))

    stop_spark()
    logger.info("weekly_articles_loaded", total=len(all_articles))

    if not all_articles:
        logger.warning("weekly_no_articles")
        return

    # Reuse write_pdfs with week label
    week_label = f"{week_start.strftime('%Y-W%V')}"
    output_dir = settings.digests_path / "weekly"
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = write_pdfs(
        all_articles,
        total_collected=len(all_articles),
        ingestion_date=reference_date,
        output_dir=output_dir,
    )

    # Rename to weekly naming convention
    from pathlib import Path
    renamed = []
    for p in pdf_paths:
        suffix = "ai" if "digest-ai" in str(p) else "db"
        new_name = output_dir / f"{week_label}-weekly-{suffix}.pdf"
        Path(p).rename(new_name)
        renamed.append(new_name)
        print(f"Weekly PDF: {new_name}")

    # Slack notification
    if settings.slack_bot_token and settings.slack_channel_id:
        from src.output.slack_notifier import SlackNotifier
        notifier = SlackNotifier(settings.slack_bot_token, settings.slack_channel_id)
        notifier.notify_success(
            ingestion_date=f"{week_label} 주간",
            stats={
                "collected": len(all_articles),
                "digest": len(all_articles),
                "db": sum(1 for a in all_articles if a.get("is_databricks_related")),
                "ai": sum(1 for a in all_articles if not a.get("is_databricks_related")),
                "other": 0,
            },
            pdf_paths=renamed,
            new_since_yesterday=0,
        )


if __name__ == "__main__":
    asyncio.run(run_weekly())
```

**Step 2: 서버 crontab에 주간 cron 추가**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 \
  "crontab -l | { cat; echo '30 17 * * 0 cd ~/delta-digest && git pull origin main && JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 ~/.local/bin/uv run python src/run_weekly.py >> outputs/logs/weekly_\$(date +\%Y\%m\%d).log 2>&1'; } | crontab -"
```

매주 일요일 KST 02:30 (UTC 17:30) 실행.

**Step 3: Commit**

```bash
git add src/run_weekly.py
git commit -m "feat: add weekly digest pipeline aggregating 7 days of Gold data"
```

---

### Task 8: 서버 배포 + 전체 검증

**Step 1: push 및 서버 pull**

```bash
git push origin main
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 "cd ~/delta-digest && git pull origin main && ~/.local/bin/uv sync"
```

**Step 2: mock으로 Slack 알림 동작 확인**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 \
  "cd ~/delta-digest && JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 ~/.local/bin/uv run python src/run_daily.py --mock --no-podcast 2>&1 | tail -20"
```

Slack 채널에 메시지 + PDF 3개 도착하는지 확인.

**Step 3: crontab 최종 확인**

```bash
ssh -i ~/.ssh/oracle_mcp ubuntu@168.107.63.16 "crontab -l"
```

Expected: daily cron (17:00) + weekly cron (일 17:30) + log rotation (03:00) 3줄.
