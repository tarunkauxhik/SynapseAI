"""
Eval endpoints: config, datasets, background eval runs (one at a time) and the
latest saved run per agent model. Starting or cancelling a run needs EVAL_RUN_KEY.
"""

import asyncio
import glob
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
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
_current: Optional[tuple] = None  # (run_id, asyncio.Task)


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


def _check_key(key: str):
    if not settings.eval_run_key:
        raise HTTPException(status_code=403, detail="Eval runs are disabled on this server.")
    if not hmac.compare_digest(key.encode(), settings.eval_run_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid eval key.")


async def _execute(run_id: str, dataset: str, agent_model: str):
    """Runs every case, saving results after each one so the page can show progress."""
    model_override.set(agent_model)  # this task (and its children) only; production tasks are unaffected
    runner = EvalRunner.from_json(
        name=f"{agent_model} on {dataset}",
        agent=ResearchAgentAdapter(),
        path=dataset,
        grader=UnifiedGrader(pass_threshold=0.6, model=settings.eval_judge_model),
    )

    async def save(results):
        summary = EvalSummary(name=runner.name, results=results).to_dict()
        rows = summary.pop("results")
        for row in rows:
            row.pop("output", None)  # the page links to the report instead of storing it twice
        await db_manager.update_eval_run(run_id, {"summary": summary, "results": rows})

    def finished(status: str, **extra) -> dict:
        return {"status": status, "finished_at": datetime.now(timezone.utc).isoformat(), **extra}

    try:
        await runner.run(on_result=save)
        await db_manager.update_eval_run(run_id, finished("completed"))
    except asyncio.CancelledError:
        await db_manager.update_eval_run(run_id, finished("cancelled"))
        raise
    except Exception as e:
        logger.exception("Eval run failed")
        await db_manager.update_eval_run(run_id, finished("failed", error=str(e)[:500]))


# --- Routes ---

@router.get("/config")
async def get_config():
    return {
        "agent_models": settings.eval_agent_model_list,
        "judge_model": settings.eval_judge_model,
        "run_enabled": bool(settings.eval_run_key),
    }


@router.get("/eval/datasets")
async def get_datasets():
    return {"datasets": [
        {"name": Path(f).stem.replace("_", " ").title(), "file": f, "count": n}
        for f, n in _datasets().items()
    ]}


@router.get("/eval/runs/latest")
async def latest_runs():
    """Latest saved run per allowed agent model, for the side-by-side view."""
    return {"runs": {m: await db_manager.latest_eval_run(m) for m in settings.eval_agent_model_list}}


@router.post("/eval/run", status_code=202)
async def run_eval(request: RunEvalRequest, x_eval_key: str = Header(default="")):
    global _current
    _check_key(x_eval_key)

    models = settings.eval_agent_model_list
    agent_model = request.agent_model or (models[0] if models else None)
    if agent_model not in models:
        raise HTTPException(status_code=400, detail=f"agent_model must be one of {models}.")
    case_count = _datasets().get(request.dataset)
    if case_count is None:
        raise HTTPException(status_code=400, detail="Unknown dataset.")
    if _current and not _current[1].done():
        raise HTTPException(status_code=409, detail="An eval run is already in progress.")

    run_id = await db_manager.create_eval_run({
        "status": "running",
        "agent_model": agent_model,
        "judge_model": settings.eval_judge_model,
        "dataset": request.dataset,
        "total_cases": case_count,
    })
    _current = (run_id, asyncio.create_task(_execute(run_id, request.dataset, agent_model)))
    return {"run_id": run_id}


@router.delete("/eval/runs/{run_id}")
async def cancel_eval_run(run_id: str, x_eval_key: str = Header(default="")):
    _check_key(x_eval_key)
    if not _current or _current[0] != run_id or _current[1].done():
        raise HTTPException(status_code=404, detail="Run not found or already finished.")
    _current[1].cancel()
    return {"message": "Eval run cancelled"}
