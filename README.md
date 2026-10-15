# SynapseAI

A self-correcting multi-agent research system that produces structured, cited reports from natural language queries.

Three specialized agents (Researcher, Critic, Reviser) collaborate in a feedback loop: the Researcher plans search strategies and drafts reports from live web data, the Critic scores the draft and identifies weaknesses, and the Reviser rewrites the draft once if it scores below the quality threshold (6.5/10).

---
## Architecture

```mermaid
flowchart TB
    subgraph Frontend["Frontend (Next.js, Vercel)"]
        ResearchForm[ResearchForm]
        ProgressTracker[ProgressTracker]
        ReportViewer[ReportViewer]
    end

    subgraph Backend["Backend (FastAPI, Render)"]
        API[API Routes]
        WS[WebSocket Manager]
        Coord[Orchestrator]
    end

    subgraph Agents["Agents (app/agents)"]
        Researcher[Researcher Agent]
        Critic[Critic Agent]
        Reviser[Reviser Agent]
    end

    subgraph Tools["Tools (app/tools)"]
        Tavily[Tavily\nPrimary]
        Wiki[Wikipedia\nKnowledge]
    end

    subgraph LLM["LLM (app/llm)"]
        LLM[OpenAI-compatible client\nMiniMax-M3 via gateway]
    end

    subgraph DB["Supabase (PostgreSQL)"]
        Tasks[(research_tasks)]
        Logs[(task_logs)]
    end

    subgraph Evals["Evals (evals/)"]
        Runner[EvalRunner]
        Grader[UnifiedGrader]
        Adapter[AgentAdapter]
    end

    ResearchForm --> API
    ProgressTracker --> WS
    API --> Coord
    WS --> Coord
    Coord --> Researcher
    Coord --> Critic
    Coord --> Reviser
    Coord --> Tasks
    Coord --> Logs
    Researcher --> Tavily
    Researcher --> Wiki
    Researcher --> LLM
    Critic --> LLM
    Reviser --> LLM
    Adapter --> Coord
    Runner --> Grader
    Runner --> Adapter
```

**Backend**: FastAPI, Python 3.11, MiniMax-M3 via an OpenAI-compatible gateway (set by `LLM_MODEL`), Supabase (PostgreSQL + JSONB)

**Frontend**: Next.js 16, React 19, Tailwind CSS v4, Framer Motion

**Infrastructure**: Docker, Render (backend), Vercel (frontend)

---

## How It Works

1. User submits a research topic via the frontend
2. Backend creates a task in Supabase, returns task ID immediately (HTTP 202)
3. Background workflow starts:
   - **Planning** — LLM generates 3-5 targeted search queries
   - **Gathering** — Tavily + Wikipedia run in parallel, results deduplicated
   - **Drafting** — LLM synthesizes sources into a structured report (Pydantic-validated JSON)
   - **Critiquing** — Critic agent scores the draft 0-10, lists weaknesses
   - **Revising** — Reviser agent rewrites based on feedback
4. Frontend tracks progress via WebSocket + HTTP polling
5. Final report rendered with citations

All structured LLM outputs use JSON mode; the client strips any `<think>` blocks or code fences, validates against the Pydantic model, and retries once on invalid JSON. API errors and rate limits are retried twice with backoff.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys: an OpenAI-compatible LLM endpoint (`LLM_BASE_URL` + `LLM_API_KEY`), [Supabase](https://supabase.com/) (free tier), [Tavily](https://tavily.com/) (optional, free tier)

### Backend

```bash
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, TAVILY_API_KEY

python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.api.routes:app --reload
```

Backend runs at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

Environment variables (see `.env.example`):

| Variable | Required | Purpose |
|----------|----------|---------|
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Backend DB access (falls back to `SUPABASE_KEY`) |
| `LLM_BASE_URL` | yes | OpenAI-compatible endpoint, e.g. `https://your-gateway/v1` |
| `LLM_API_KEY` | yes | Key for that endpoint |
| `LLM_MODEL` | no | Model ID (default `MiniMax-M3`) |
| `TAVILY_API_KEY` | no | Web search; without it only Wikipedia is used |
| `CORS_ORIGINS` | prod | Comma-separated frontend origins (default `http://localhost:3000`) |
| `EVAL_AGENT_MODELS` | no | Eval agent model allowlist, first = default (default `MiniMax-M3,MiniMax-M2.5-highspeed`) |
| `EVAL_JUDGE_MODEL` | no | Eval judge model, never used as an agent (default `MiniMax-M2.7`) |
| `EVAL_RUN_KEY` | no | Key required to start/cancel eval runs; unset = runs disabled. Never commit it |

`GET /health` does one tiny Supabase read; point an external cron at it to keep Render and Supabase awake.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

### Docker (Backend Only)

```bash
docker build -t synapseai-backend .
docker run -p 8000:8000 --env-file .env synapseai-backend
```

---

## Database Setup

Run `supabase_schema_fixed.sql` in your Supabase SQL Editor. This creates:

- `research_tasks` — Main state table (JSONB document store pattern)
- `task_logs` — Agent message audit trail (separate to avoid bloat)

---

## Evaluation Framework

The `/evals` route provides a benchmarking dashboard. Test cases in `eval_cases.json` are run through the agent pipeline and graded on four dimensions:

- **Content Quality** — Depth and relevance
- **Source Citation** — Accuracy and frequency
- **Reasoning Quality** — Logical coherence
- **Tool Usage** — Effective use of search tools

Results are visualized in the frontend at `/evals`.

---

## Project Structure

```
├── app/
│   ├── agents/          # Researcher, Critic, Reviser agents
│   ├── api/             # FastAPI routes + eval endpoints
│   ├── database/        # Supabase connection manager
│   ├── llm/             # OpenAI-compatible client with structured JSON output
│   ├── models/          # Pydantic models (the data contract)
│   ├── orchestrator/    # Coordinator state machine
│   └── tools/           # Web search (Tavily) + Wikipedia
├── evals/               # Evaluation runner, graders, types
├── frontend/            # Next.js 16 app
│   └── src/
│       ├── app/         # Pages (home, research/[taskId], evals)
│       ├── components/  # ResearchForm, ProgressTracker, ReportViewer
│       └── lib/         # API client, types
├── Dockerfile
├── supabase_schema_fixed.sql
└── eval_cases.json
```

---

## Tech Decisions

| Choice | Reasoning |
|--------|-----------|
| OpenAI-compatible client | Model and provider are env vars (`LLM_BASE_URL`, `LLM_MODEL`); swap models without code changes. |
| JSONB document store | Entire task state in one row. Avoids complex joins for write-heavy, read-once workload. |
| Pydantic for LLM output | `model_validate()` enforces schema on every LLM response. No format hallucinations reach the user. |
| Background tasks | HTTP 202 pattern — user gets instant response, research runs async (asyncio task, cancellable via `DELETE /research/{id}`). Tasks interrupted by a restart are marked failed on startup. |
| Separate logs table | Agent logs can grow to megabytes. Keeping them out of the main task row avoids bloated reads. |
