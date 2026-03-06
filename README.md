# delta-digest

> Daily AI/Databricks tech digest — automated with Delta Lake Medallion Architecture + hybrid LLM

A personal knowledge system that collects, processes, and summarizes AI/Databricks news every day. Built as a portfolio project for a Databricks SE position.

**Zero cost to run**: Local LLM (Ollama) + Gemini Free API + Oracle Cloud Free Tier.

---

## Architecture

```
RSS / ArXiv / HN / GitHub
        │
        ▼
 ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
 │   Bronze    │────▶│    Silver    │────▶│    Gold     │
 │ (Delta Lake)│     │ HTML strip   │     │ AI scoring  │
 │ MERGE upsert│     │ Dedup        │     │ + Summaries │
 └─────────────┘     └──────────────┘     └─────────────┘
                                                 │
                                                 ▼
                                       outputs/digests/
                                       YYYY-MM-DD-digest.md
```

**Delta Lake Medallion Architecture** — Bronze (raw) → Silver (clean) → Gold (AI-enriched)

| Layer | Contents |
|-------|----------|
| Bronze | Raw articles, MERGE upsert by URL, date-partitioned |
| Silver | HTML-stripped, deduplicated, Databricks-related flagged |
| Gold | Scored + summarized, top-20 selected by quota |

---

## LLM Strategy (Hybrid, $0/month)

| Task | Model | Reason |
|------|-------|--------|
| Relevance scoring (~180 articles/day) | Ollama Qwen 2.5 7B (local) | High-volume JSON output, free |
| Korean summarization (top 20/day) | Gemini 2.5 Flash (Free API) | Quality Korean, long context |

The `LLMClient` abstraction allows swapping to Databricks Foundation Model API or Anthropic with one line.

---

## Digest Format

Each daily digest (`outputs/digests/YYYY-MM-DD-digest.md`) contains:

- **🔥 AI Hot News TOP 10** — highest overall score across all sources
- **🔷 Databricks/Delta Lake TOP 5** — highest Databricks relevance score
- **📌 Other picks (5)** — best from ArXiv, GitHub, HN

Each article includes a **3-5 sentence Korean summary** + key points (podcast-ready).

---

## Stack

- **PySpark 3.5** + **delta-spark 3.2** — local mode, Databricks-compatible
- **Python 3.11** + **uv** package manager
- **httpx** (async HTTP) + **feedparser** + BeautifulSoup
- **structlog** (structured logging) + **Pydantic** (config/models)
- **Jinja2** (digest template)
- **google-genai** SDK (Gemini 2.5 Flash)

---

## Setup

```bash
# 1. Clone & install
git clone https://github.com/YongjunJeong/delta-digest.git
cd delta-digest
uv sync

# 2. Environment
cp .env.example .env
# Edit .env: add DIGEST_GEMINI_API_KEY

# 3. Run (requires Java 11+)
export JAVA_HOME=/path/to/jdk11
uv run python src/run_daily.py

# Mock mode (no LLM needed)
uv run python src/run_daily.py --mock
```

### Oracle Cloud (production)
```bash
# Install Ollama for local scoring
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:7b

# Cron: daily at 5am
0 5 * * * /home/ubuntu/delta-digest/scripts/run_daily.sh
```

---

## Project Structure

```
src/
├── ingestion/        # Async collectors (RSS, HN, ArXiv, GitHub)
├── pipeline/         # Spark + Delta Lake (Bronze / Silver / Gold)
├── agents/           # LLM clients (Ollama + Gemini) + scorer/summarizer
├── output/           # Jinja2 digest template + writer
└── run_daily.py      # End-to-end orchestrator
```

---

## Roadmap

- [x] Phase 1-3: Collect → Process → Digest
- [ ] Phase 4: TTS podcast (edge-tts)
- [ ] Phase 5: RAG Q&A (ChromaDB + FastAPI)
