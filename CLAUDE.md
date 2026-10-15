# SynapseAI

Self-correcting multi-agent research app. A user submits a topic. The Researcher plans and writes a cited report from web data. The Critic scores it 0-10. If the score is below 6.5, the Reviser rewrites it once.

**Stack:** FastAPI (Python 3.11, Docker on Render), Next.js 16 frontend (Vercel), Supabase Postgres. The LLM is MiniMax-M3, called through an OpenAI-compatible gateway (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).

## Request flow
1. `POST /research` ([app/api/routes.py](app/api/routes.py)) inserts a `research_tasks` row, starts `coordinator.launch(task_id)` (an asyncio task, cancellable) and returns 202.
2. [app/orchestrator/coordinator.py](app/orchestrator/coordinator.py) runs these stages:
   - PLANNING: `researcher.generate_plan`, then the plan is saved.
   - IN_PROGRESS: one Tavily search (using only `search_queries[0]`) runs in parallel with a Wikipedia search on `main_topic`, then the draft is written.
   - REVIEWING: the Critic scores the draft.
   - REVISING: runs once if the score is below 6.5.
   - COMPLETED.
3. Every step writes to Supabase and broadcasts on `/ws/{task_id}`. The WebSocket carries only log lines.
4. The frontend polls `GET /research/{id}/status` every 3s, which provides the stage and report. Polling stops once the status is completed or failed.

A typical task makes 4 LLM calls and takes about 100s on MiniMax-M3. Revising is the slowest step at about 55s.

## LLM client ([app/llm/client.py](app/llm/client.py))
- Uses the `openai` SDK `AsyncOpenAI` with `timeout=120` and `max_retries=2` (the SDK backs off on 429, 5xx and connection errors).
- Sends `extra_body={"thinking": {"type": "disabled"}}`. MiniMax-M3 honors it. M2.x ignores it and still emits `<think>` blocks in `content`.
- Structured calls use `response_format=json_object`. The reply then goes through `extract_json`, which strips `<think>` blocks and code fences and takes the outermost `{...}`. The result is validated against the Pydantic model, and the call retries once if parsing or validation fails.
- Self-check: `python -m app.llm.client`.

## Reliability
- `DELETE /research/{id}` cancels the asyncio task. `update_task_status` never overwrites a `failed` status.
- On startup, `fail_stale_tasks` marks every non-terminal task as failed, because work in memory dies with a Render restart.
- `ground_references` ([app/agents/base.py](app/agents/base.py)) keeps only references whose URL was gathered, then renumbers them 1..n and remaps `source_ids` and inline `[n]` citations. It runs on the draft, matching against the gathered sources, and on the revision, which keeps the draft's list (the Reviser is told to return `references: []`). Self-check: `python -m app.agents.base`.
- `GET /health` does one tiny Supabase read and returns 503 if it fails. An external cron pings it every 14 minutes, 9 AM to 10 PM IST.

## Layout
- `app/`: backend.
  - `api/`: routes, eval routes.
  - `agents/`: researcher, critic, reviser.
  - `llm/`, `database/connection.py`: Supabase; tables `research_tasks` and `task_logs` only.
  - `tools/`: Tavily, Wikipedia (aiohttp, one session per call, 30s timeout).
  - `models/`.
- `evals/`: eval harness. `POST /eval/run` runs every case in `eval_cases.json` synchronously and grades each with one LLM call.
- `frontend/`: Next.js.
  - `src/lib/api.ts`: reads `NEXT_PUBLIC_API_URL`, which is inlined at build time.
  - `components/ProgressTracker.tsx`: shows `status.logs` (history) plus live WebSocket lines not yet polled, deduplicated on timestamp + message. The stage comes from the parent page's polling.
- `supabase_schema_fixed.sql`: the DB schema.

## Env vars (names only; never print `.env` values)
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_KEY`), `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TAVILY_API_KEY`, `CORS_ORIGINS`.

## Run locally
- Backend: `pip install -r requirements.txt && uvicorn app.api.routes:app --reload` (port 8000).
- Frontend: `cd frontend && npm install && npm run dev`.

## Known limitations
- Only the first planned query is searched.
- Wikipedia results are snippets only.
- Web search is Tavily only; with no key or no results the task uses Wikipedia only (a warning is logged). The DuckDuckGo fallback was removed because DDG blocks the aiohttp user agent.
- The Supabase client is synchronous and briefly blocks the event loop on each DB call.
