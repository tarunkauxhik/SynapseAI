"""
Supabase Database Manager.
Optimized for Document-Oriented Architecture (JSONB).
"""

import asyncio
import functools
import logging
from datetime import datetime, timezone
from typing import List, Optional

from supabase import create_client, Client
from app.config import settings
from app.models.research import (
    ResearchTask,
    ResearchReport,
    ResearchPlan,
    CritiqueFeedback,
    AgentMessage,
    ResearchStatus
)

logger = logging.getLogger(__name__)


def _threaded(fn):
    """Runs a blocking Supabase call in a worker thread, so it doesn't freeze the event loop
    (the sync client takes ~0.2-1s per call). Callers still `await` it as before."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)
    return wrapper

class SupabaseManager:
    """
    Manages Supabase operations.
    Treats 'ResearchTask' as the single source of truth (Document Store pattern).
    """
    
    def __init__(self):
        self.client: Optional[Client] = None
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Initialize the client (once; every eval case's coordinator calls this)."""
        if self._initialized:
            return True
        try:
            key = settings.supabase_service_role_key or settings.supabase_key
            self.client = create_client(settings.supabase_url, key)
            self._initialized = True
            logger.info("Supabase Connected.")
            return True
        except Exception as e:
            logger.error(f"Supabase Init Failed: {e}")
            return False

    def _ensure_initialized(self):
        if not self._initialized:
            raise RuntimeError("DB Not Initialized.")

    @_threaded
    def ping(self):
        """Tiny read used by /health (raises on failure)."""
        self._ensure_initialized()
        self.client.table("research_tasks").select("id").limit(1).execute()

    @_threaded
    def fail_stale_tasks(self) -> int:
        """Marks tasks left running by a previous process as failed. Call once at startup."""
        self._ensure_initialized()
        active = [s.value for s in ResearchStatus if s not in (ResearchStatus.COMPLETED, ResearchStatus.FAILED)]
        try:
            res = self.client.table("research_tasks").update({
                "status": ResearchStatus.FAILED.value,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).in_("status", active).execute()
            return len(res.data or [])
        except Exception as e:
            logger.error(f"Fail Stale Tasks Failed: {e}")
            return 0

    # --- TASK OPERATIONS ---

    @_threaded
    def create_task(self, task: ResearchTask) -> Optional[str]:
        """
        Creates a new task. Returns the Task ID.
        """
        self._ensure_initialized()
        try:
            # CRITICAL FIX: Explicitly exclude fields that are NOT in the 'research_tasks' table
            # 1. 'id': Let the database generate the UUID
            # 2. 'agent_messages': These belong in the separate 'task_logs' table
            # 3. 'agent_logs': Just in case your model uses this name alias
            # 4. 'tools_called': In-memory tracking for evals only, not stored in DB
            data = task.model_dump(
                mode='json', 
                exclude={'id', 'agent_messages', 'agent_logs', 'tools_called'} 
            ) 
            
            # Insert and return ID
            res = self.client.table("research_tasks").insert(data).execute()
            
            if res.data:
                new_id = res.data[0]['id']
                logger.info(f"Task Created: {new_id}")
                return new_id
            
            # Log the full error response from Supabase if it fails
            logger.error(f"Supabase Insert Failed. Response: {res}")
            return None
            
        except Exception as e:
            logger.error(f"Create Task Exception: {e}") 
            return None

    @_threaded
    def get_task(self, task_id: str) -> Optional[ResearchTask]:
        try:
            # Fetch task from research_tasks table
            res = self.client.table("research_tasks")\
                .select("*")\
                .eq("id", task_id)\
                .single()\
                .execute()

            if res.data:
                task = ResearchTask(**res.data)
                
                # Also fetch agent_logs from task_logs table
                logs_res = self.client.table("task_logs")\
                    .select("*")\
                    .eq("task_id", task_id)\
                    .order("created_at")\
                    .execute()
                
                if logs_res.data:
                    from app.models.research import AgentMessage, AgentType
                    for log_entry in logs_res.data:
                        try:
                            task.agent_logs.append(AgentMessage(
                                agent_type=AgentType(log_entry.get("agent_type", "researcher")),
                                message=log_entry.get("message", ""),
                                step_name=log_entry.get("metadata", {}).get("step_name", "general"),
                                # Original timestamp, so it matches the WebSocket copy of this line
                                timestamp=log_entry.get("metadata", {}).get("timestamp") or log_entry.get("created_at"),
                            ))
                        except Exception:
                            # Just add message as-is if parsing fails
                            pass
                
                return task
            return None
        except Exception as e:
            logger.error(f"Get Task Failed: {e}")
            return None

    # --- EVAL RUNS (table: eval_runs) ---

    @_threaded
    def create_eval_run(self, data: dict) -> str:
        """Inserts a run (status 'running') and returns its id. Raises on failure."""
        self._ensure_initialized()
        res = self.client.table("eval_runs").insert(data).execute()
        return res.data[0]["id"]

    @_threaded
    def update_eval_run(self, run_id: str, data: dict):
        self._ensure_initialized()
        try:
            self.client.table("eval_runs").update(data).eq("id", run_id).execute()
        except Exception as e:
            logger.error(f"Update Eval Run Failed: {e}")

    @_threaded
    def latest_eval_run(self, agent_model: str) -> Optional[dict]:
        self._ensure_initialized()
        res = self.client.table("eval_runs").select("*")\
            .eq("agent_model", agent_model)\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()
        return res.data[0] if res.data else None

    @_threaded
    def fail_stale_eval_runs(self) -> int:
        """Marks eval runs left 'running' by a previous process as failed. Call once at startup."""
        self._ensure_initialized()
        try:
            res = self.client.table("eval_runs").update({
                "status": "failed",
                "error": "Server restarted during the run.",
                "finished_at": datetime.now(timezone.utc).isoformat()
            }).eq("status", "running").execute()
            return len(res.data or [])
        except Exception as e:
            logger.error(f"Fail Stale Eval Runs Failed (is the eval_runs table created?): {e}")
            return 0

    @_threaded
    def update_task_status(self, task_id: str, status: ResearchStatus):
        """Status update. Sets completed_at when COMPLETED. A FAILED task is never changed again."""
        self._ensure_initialized()
        try:
            update_data = {
                "status": status.value,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            # Set completed_at when task is completed
            if status == ResearchStatus.COMPLETED:
                update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            
            self.client.table("research_tasks").update(update_data)\
                .eq("id", task_id)\
                .neq("status", ResearchStatus.FAILED.value)\
                .execute()
        except Exception as e:
            logger.error(f"Status Update Failed: {e}")

    @_threaded
    def save_raw_search_results(self, task_id: str, results: list):
        """Saves the raw search results to the database."""
        self._ensure_initialized()
        try:
            self.client.table("research_tasks").update({
                "raw_search_results": results,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", task_id).execute()
            
            logger.info(f"Raw search results saved for Task {task_id}: {len(results)} results")
            
        except Exception as e:
            logger.error(f"Save Raw Search Results Failed: {e}")

    @_threaded
    def set_revision_count(self, task_id: str, count: int):
        """Saves the revision count (the coordinator holds the current value)."""
        self._ensure_initialized()
        try:
            self.client.table("research_tasks").update({
                "revision_count": count,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", task_id).execute()

            logger.info(f"Revision count set to {count} for Task {task_id}")

        except Exception as e:
            logger.error(f"Set Revision Count Failed: {e}")

    # --- STATE UPDATES (Report & Feedback) ---
    
    @_threaded
    def save_report(self, task_id: str, report: ResearchReport):
        """
        Updates the 'current_report' JSONB column.
        """
        self._ensure_initialized()
        try:
            # Dump the report to a dict
            report_json = report.model_dump(mode='json')
            
            self.client.table("research_tasks").update({
                "current_report": report_json,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", task_id).execute()
            
            logger.info(f"Report saved for Task {task_id}")
            
        except Exception as e:
            logger.error(f"Save Report Failed: {e}")

    @_threaded
    def save_plan(self, task_id: str, plan: ResearchPlan):
        """
        Updates the 'plan' JSONB column.
        """
        self._ensure_initialized()
        try:
            plan_json = plan.model_dump(mode='json')
            
            self.client.table("research_tasks").update({
                "plan": plan_json,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", task_id).execute()
            
            logger.info(f"Plan saved for Task {task_id}")
            
        except Exception as e:
            logger.error(f"Save Plan Failed: {e}")

    @_threaded
    def save_feedback(self, task_id: str, history: List[CritiqueFeedback]):
        """
        Saves the full 'feedback_history' array (the coordinator holds the current list).
        """
        self._ensure_initialized()
        try:
            history_json = [f.model_dump(mode='json') for f in history]
            
            self.client.table("research_tasks").update({
                "feedback_history": history_json,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", task_id).execute()
            
            logger.info(f"Feedback saved for Task {task_id}")

        except Exception as e:
            logger.error(f"Save Feedback Failed: {e}")

    # --- LOGGING ---

    @_threaded
    def log_agent_message(self, task_id: str, message: AgentMessage):
        """
        Inserts into the separate 'task_logs' table.
        """
        self._ensure_initialized()
        try:
            # Map AgentMessage fields to table columns
            data = {
                'task_id': task_id,
                'agent_type': message.agent_type.value,  # Enum to string
                'message': message.message,
                'metadata': {
                    'step_name': message.step_name,
                    'timestamp': message.timestamp.isoformat()
                }
            }

            # Ensure we use the correct table name from schema
            self.client.table("task_logs").insert(data).execute()

        except Exception as e:
            # Don't crash the app if logging fails
            logger.warning(f"Logging Failed: {e}")

# Global Instance
db_manager = SupabaseManager()