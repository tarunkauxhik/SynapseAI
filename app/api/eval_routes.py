"""
Eval endpoints: config, datasets, background eval runs (one at a time, cases in parallel)
and the latest saved run per agent model. A model can be re-run once EVAL_COOLDOWN_HOURS
have passed since its last run started.
"""

import asyncio
import glob
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.database.connection import db_manager
from app.llm.client import model_override
from evals.agent_adapter import ResearchAgentAdapter
from evals.graders import UnifiedGrader
from evals.runner import EvalRunner
from evals.types import EvalSummary

logger = logging.getLogger(__name__)
router = APIRouter()

# ponytail: one in-process run at a time (single Render instance); move to a queue if that changes
_current: Optional[asyncio.Task] = None
_start_lock = asyncio.Lock()  # DB calls yield, so check-and-start must be atomic


class RunEvalRequest(BaseModel):
    dataset: str = "eval_cases.json"
    agent_model: Optional[str] = None


def _datasets() -> dict:
    """file -> case count for every eval dataset on disk (the only files a run may load)."""
    found = {}
    for f in glob.glob("*.json") + glob.glob("evals/*.json"):
        try:
            content = json.loads(Path(f).read_text())
            if isinstance(content, list) and content and "input" in content[0]:
                found[f] = len(content)
        except Exception:
            pass
    return found


def _next_run_at(last_run: Optional[dict]) -> Optional[datetime]:
    """When this model may run again, or None if it may run now."""
    if not last_run:
        return None
    started = datetime.fromisoformat(last_run["created_at"])
    next_at = started + timedelta(hours=settings.eval_cooldown_hours)
    return next_at if next_at > datetime.now(timezone.utc) else None


async def _execute(run_id: str, dataset: str, agent_model: str):
    """Runs the cases in parallel, saving results each time a case finishes."""
    model_override.set(agent_model)  # this task (and its children) only; production tasks are unaffected
    runner = EvalRunner.from_json(
        name=f"{agent_model} on {dataset}",
        agent=ResearchAgentAdapter,  # a class: one adapter per case
        path=dataset,
        grader=UnifiedGrader(pass_threshold=0.6, model=settings.eval_judge_model),
    )
    runner.parallel = True
    runner.max_concurrent = settings.eval_concurrency
    save_lock = asyncio.Lock()  # parallel cases: write snapshots in order so an older one never lands last

    async def save(results):
        async with save_lock:
            summary = EvalSummary(name=runner.name, results=results).to_dict()
            rows = summary.pop("results")
            for row in rows:
                row.pop("output", None)  # the page links to the report instead of storing it twice
            await db_manager.update_eval_run(run_id, {"summary": summary, "results": rows})

    finished_at = lambda: datetime.now(timezone.utc).isoformat()
    try:
        summary = await runner.run(on_result=save)
        await save(summary.results)
        await db_manager.update_eval_run(run_id, {"status": "completed", "finished_at": finished_at(), "error": None})
    except Exception as e:
        logger.exception("Eval run failed")
        await db_manager.update_eval_run(run_id, {"status": "failed", "finished_at": finished_at(), "error": str(e)[:500]})


# --- Routes ---

@router.get("/config")
async def get_config():
    return {
        "agent_models": settings.eval_agent_model_list,
        "judge_model": settings.eval_judge_model,
        "cooldown_hours": settings.eval_cooldown_hours,
    }


@router.get("/eval/datasets")
async def get_datasets():
    return {"datasets": [
        {"name": Path(f).stem.replace("_", " ").title(), "file": f, "count": n}
        for f, n in _datasets().items()
    ]}


@router.get("/eval/runs/latest")
async def latest_runs():
    """Latest saved run per allowed agent model (side-by-side view) and when each may run again."""
    runs = {m: await db_manager.latest_eval_run(m) for m in settings.eval_agent_model_list}
    next_at = {m: _next_run_at(r) for m, r in runs.items()}
    return {"runs": runs, "next_run_at": {m: t.isoformat() if t else None for m, t in next_at.items()}}


@router.post("/eval/run", status_code=202)
async def run_eval(request: RunEvalRequest):
    global _current
    models = settings.eval_agent_model_list
    agent_model = request.agent_model or (models[0] if models else None)
    if agent_model not in models:
        raise HTTPException(status_code=400, detail=f"agent_model must be one of {models}.")
    case_count = _datasets().get(request.dataset)
    if case_count is None:
        raise HTTPException(status_code=400, detail="Unknown dataset.")

    async with _start_lock:
        if _current and not _current.done():
            raise HTTPException(status_code=409, detail="An eval run is already in progress.")
        next_at = _next_run_at(await db_manager.latest_eval_run(agent_model))
        if next_at:
            minutes = max(1, int((next_at - datetime.now(timezone.utc)).total_seconds() // 60))
            raise HTTPException(
                status_code=429,
                detail=f"Next run for {agent_model} available in {minutes // 60}h {minutes % 60}m.",
                headers={"Retry-After": str(minutes * 60)},
            )
        run_id = await db_manager.create_eval_run({
            "status": "running",
            "agent_model": agent_model,
            "judge_model": settings.eval_judge_model,
            "dataset": request.dataset,
            "total_cases": case_count,
        })
        _current = asyncio.create_task(_execute(run_id, request.dataset, agent_model))
    return {"run_id": run_id}
