# Data model, model routing and operations

[Overview](../README.md) · [Korean reference](../README.ko.md)

## Collection and data contracts

`src/ingestion/run_all.py` coordinates collectors. RSS/Atom feed definitions and
filters live in `sources.yaml`; separate collectors handle arXiv, Hacker News and
GitHub Search. The GitHub collector is a search client, not a replica of GitHub's
Trending page. Availability and collection counts depend on external services.

`RawArticle` in `src/common/models.py` carries URL, title, raw content, author,
source name/type, publication/collection timestamps, category, priority and raw
metadata. `articles_to_rows()` serializes metadata as JSON and assigns the
requested ingestion date; it does not clean or reinterpret source text.

| Layer | Source of truth | Write behavior |
|---|---|---|
| Bronze | First stored raw article for a URL | Delta insert-only MERGE on URL; date partition |
| Silver | Cleaned content and derived attributes | HTML stripping, URL deduplication, word/language filters and topic flags; replace one date partition |
| Gold | Scores, summaries and digest selection | Joins model outputs and marks quota-selected URLs |

Schemas are in [`schemas.py`](../src/pipeline/schemas.py). Silver topic detection
uses explicit keywords/source names and Python UDFs, not model classification.
The language filter keeps short or undetectable text. Duplicate choice and language
classification are not a labelled extraction-quality evaluation.

Bronze skips URLs already stored on another date, so reading today's partition
will not produce a new snapshot of those articles. Input duplicates, interrupted
runs and multi-day replay still need real Spark/Delta integration checks. Delta
transaction history does not itself prove an end-to-end exactly-once workflow.

Gold's default quota is **10 Databricks + 20 AI + 10 other** when sufficient inputs
exist. Source limits and overlap can produce fewer items. This supersedes the
older Top 20 diagram. Some current selection tests mock dataframe operations;
they are not proof of real Spark query correctness.

## Model routing and degradation

`LLMRouter` maps scoring to Ollama and summarization/scriptwriting to Gemini.
The client interface returns response text and token/latency metadata; its JSON
methods include parse/retry behavior. Supporting another provider needs a tested
client implementation, not only a new provider name.

- Ollama defaults to `qwen2.5:7b` at `http://localhost:11434`.
- The Gemini client constructor currently defaults to `gemini-2.5-flash`.
  Settings do not read a `DIGEST_GEMINI_MODEL` variable.
- `_run_ai_pipeline()` limits scoring candidates to 200 by source priority.
- If Ollama health fails, `_mock_scores()` uses seeded random scores. This is
  synthetic fallback data, not a degraded model estimate.
- Gemini summaries run only when its health check succeeds. Health checks are
  live requests, not a credential-free readiness guarantee.
- Unconfigured Gemini can cause the generic router to return Ollama for a task;
  individual pipeline stages also apply their own health/skip conditions.

Scoring and summary decisions belong to this application policy. No general
ranking, factuality, cost or latency benchmark is included.

## Output and weekly flow

`write_pdfs()` creates separate AI and Databricks digest PDFs under
`outputs/digests/` by default. The glossary JSON is kept under
`outputs/glossary/`; a glossary PDF is produced only when new terms are available.
The older description of three guaranteed daily PDFs is therefore inaccurate.
Podcast generation is optional and uses scriptwriter/TTS processing. It may
contact an external speech service; local Ollama does not make the entire workflow
network-free.

The weekly entrypoint aggregates seven days of Gold. Generated files can be
replaced by later runs on the same date. Article content, outputs and provider
logs should be treated as private local artifacts until reviewed.

## Configuration

`Settings` reads `.env` and `DIGEST_`-prefixed variables:

| Variable | Default / meaning |
|---|---|
| `DIGEST_GEMINI_API_KEY` | Empty; enables the Gemini client when supplied |
| `DIGEST_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `DIGEST_OLLAMA_MODEL` | `qwen2.5:7b` |
| `DIGEST_SLACK_BOT_TOKEN`, `DIGEST_SLACK_CHANNEL_ID` | Empty; enable delivery when both are set |
| `DIGEST_DATA_DIR` | `./data`; Bronze/Silver/Gold paths |
| `DIGEST_OUTPUT_DIR` | `./outputs`; PDFs, glossary, podcast and logs |
| `DIGEST_SPARK_DRIVER_MEMORY` | `4g` |
| `DIGEST_SPARK_SHUFFLE_PARTITIONS` | `4` |
| `DIGEST_LOG_LEVEL` | `INFO` |

There is no required API key for the unit tests. Mock mode still contacts article
sources and can deliver Slack output. Never use real Slack credentials for an
unapproved demonstration run.

## Memory and process boundaries

Spark runs in `local[*]` with PySpark 3.5.4 and Delta 3.2.1. The pipeline stops Spark
between data and model stages to reduce overlapping memory use, then restarts it
for further dataframe work. It does not explicitly unload an Ollama model from the
separate Ollama service. Dataframe `collect()` moves data into driver memory.

Spark lifecycle management on exceptional exits needs further testing. The chosen
single-machine setup does not show distributed capacity or production operations.
Historical ARM host specifications and approximate timings in the Korean reference
are previous author-reported context, not measurements reproduced by this audit.
No current free-tier eligibility, API quota or zero-cost deployment is guaranteed.

## Running and scheduling

From the repository root, use module entrypoints:

```sh
uv sync --locked
uv run python -m src.run_daily --mock --no-podcast
uv run python -m src.run_daily --no-podcast
uv run python -m src.run_weekly
```

These are live pipeline commands, not safe offline tests. Review source access,
output directories and provider settings before invoking them. The audit executes
only tests, not these full entrypoints.

The checked-in `scripts/run_daily.sh` currently hard-codes a Homebrew Java path
although its comments describe an Oracle Linux host; it also invokes the script
path instead of the documented module entrypoint. It has not been made portable
in this documentation-only refinement. Do not copy its old cron example into a
cloud host unchanged. A future scheduler should provide that host's Java/Python
paths, desired timezone, private environment and log/output directories, then
verify the module command before scheduling it.

## Troubleshooting and validation

| Symptom | Evidence to check |
|---|---|
| Spark cannot start | Java path/version, Delta jar resolution and local Spark logs |
| No new daily rows | URL deduplication across dates, source response and partition date |
| Scores appear without Ollama | `ollama_unavailable_using_mock_scores` and fallback provenance |
| Missing summaries or glossary | Gemini health/credentials and skipped-stage logs |
| PDF import/render fails | WeasyPrint native-library availability |
| Slack output unexpectedly sent | Both Slack settings were present; mock mode does not disable delivery |
| Memory pressure | Driver collections, Spark lifecycle and Ollama service residency |

The preserved new Bronze regression verifies raw content, optional timestamps,
metadata serialization and partition date. Existing tests cover model/output
helpers and mocked quota logic. Full ingestion → Delta → model → delivery,
idempotent reprocessing, failure recovery and measured costs remain unverified.
