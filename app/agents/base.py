"""Base agent class for all research agents."""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Type, TypeVar
from urllib.parse import unquote

# Import the model base class for type hinting
from pydantic import BaseModel

# Use the getter function we created to avoid circular imports/global state issues
from app.llm.client import get_llm_client
from app.models.research import (
    AgentType,
    ResearchReport,
    ResearchSource,
    ResearchTask, # We use the Task object as the main context
)

logger = logging.getLogger(__name__)

# Define a generic type variable that must be a Pydantic model
T = TypeVar("T", bound=BaseModel)

# Inline citations: [3], [1, 4], [Source 2]
_CITE_RE = re.compile(r"\[(?:Source\s*)?(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


def _norm_url(url: Optional[str]) -> str:
    """Comparable URL: decoded, no trailing slash, lowercase, spaces as underscores (Wikipedia)."""
    return unquote(url or "").strip().rstrip("/").replace(" ", "_").lower()


def ground_references(report: ResearchReport, allowed: List[ResearchSource], keep_all: bool = False) -> ResearchReport:
    """
    Keeps only references whose URL is in `allowed`, renumbers them 1..n and remaps
    section source_ids and inline [n] citations; citations to dropped references are removed.
    keep_all=True keeps every allowed source (the Reviser keeps the draft's list).
    """
    by_url = {}
    for s in allowed:
        if s.url:
            by_url.setdefault(_norm_url(s.url), s)
    positions = [_norm_url(s.url) for s in allowed]

    # The report's own reference ids -> allowed URL (None = not gathered, dropped)
    ref_urls = {}
    for i, ref in enumerate(report.references, 1):
        key = _norm_url(ref.url)
        ref_urls[str(ref.id) if ref.id is not None else str(i)] = key if key in by_url else None
        if key not in by_url:
            logger.warning(f"Dropped reference not among gathered sources: {ref.url!r} ({ref.title!r})")

    def resolve(old) -> Optional[str]:
        old = str(old).strip()
        if old in ref_urls:
            return ref_urls[old]
        # Not in the report's list: a number is the source's position in `allowed` (prompt order)
        if old.isdigit() and 1 <= int(old) <= len(positions) and positions[int(old) - 1] in by_url:
            return positions[int(old) - 1]
        return None

    texts = [report.abstract, report.conclusion] + [s.content for s in report.sections]
    cited = list(ref_urls.values())
    cited += [resolve(sid) for sec in report.sections for sid in sec.source_ids]
    cited += [resolve(n) for t in texts for m in _CITE_RE.finditer(t) for n in m.group(1).split(",")]
    urls = list(by_url) if keep_all else [u for u in dict.fromkeys(cited) if u]
    new_id = {u: str(n) for n, u in enumerate(urls, 1)}

    def remap(ids) -> List[str]:
        return list(dict.fromkeys(new_id[u] for u in map(resolve, ids) if u in new_id))

    def remap_text(text: str) -> str:
        def sub(m):
            ids = remap(m.group(1).split(","))
            return f"[{', '.join(ids)}]" if ids else ""
        return _CITE_RE.sub(sub, text)

    report.references = [by_url[u].model_copy(update={"id": new_id[u]}) for u in urls]
    for sec in report.sections:
        sec.source_ids = remap(sec.source_ids)
        sec.content = remap_text(sec.content)
    report.abstract = remap_text(report.abstract)
    report.conclusion = remap_text(report.conclusion)
    return report

class BaseAgent(ABC):
    """
    Base class for all research agents.
    Handles common LLM interactions and logging.
    """
    
    def __init__(self, agent_type: AgentType):
        self.agent_type = agent_type
        # We don't store the client in self to avoid pickling issues if you scale later.
        # We fetch it dynamically when needed.
    
    @abstractmethod
    async def process(
        self,
        task: ResearchTask,
        **kwargs
    ) -> Any:
        """
        Process the current state of the research task.
        
        Args:
            task: The full state object (containing query, current_report, feedback, etc.)
            kwargs: Additional context if needed
        """
        pass
    
    async def generate_llm_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful AI assistant.",
        temperature: float = 0.7
    ) -> str:
        """
        Generate a plain text response from the LLM.
        """
        client = await get_llm_client()
        return await client.generate_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature
        )
    
    async def generate_structured_llm_response(
        self,
        prompt: str,
        response_model: Type[T],  # <--- CRITICAL CHANGE: Pass the class type
        system_prompt: str = "You are a helpful AI assistant.",
        temperature: float = 0.3
    ) -> T:  # <--- Returns an instance of T (e.g., ResearchPlan), not Dict
        """
        Generate a structured Pydantic model response from the LLM.
        """
        client = await get_llm_client()
        return await client.generate_structured_response(
            prompt=prompt,
            response_model=response_model,
            system_prompt=system_prompt,
            temperature=temperature
        )

if __name__ == "__main__":
    # Self-check for ground_references: python -m app.agents.base
    from app.models.research import ResearchSection
    A = ResearchSource(title="A", url="https://a.com/x/", content="a")
    B = ResearchSource(title="B", url="https://en.wikipedia.org/wiki/Solid-state%20battery", content="b")
    draft = ResearchReport(
        title="t", abstract="See [3].", conclusion="Fake [2].",
        sections=[ResearchSection(title="s", content="a [1] b [2] c [3] d [1, 3] e [Source 3] f [9]", source_ids=["1", "2", "3"])],
        references=[
            ResearchSource(id=1, title="A", url="https://a.com/x", content=""),
            ResearchSource(id=2, title="Invented", url="https://fake.com", content=""),
            ResearchSource(id=3, title="B", url="https://en.wikipedia.org/wiki/Solid-state_battery", content=""),
        ],
    )
    r = ground_references(draft, [A, B])
    assert [(x.id, x.title) for x in r.references] == [("1", "A"), ("2", "B")], r.references
    assert r.sections[0].source_ids == ["1", "2"]
    assert r.sections[0].content == "a [1] b  c [2] d [1, 2] e [2] f ", r.sections[0].content
    assert (r.abstract, r.conclusion) == ("See [2].", "Fake .")

    # Reviser: keeps the draft's list even if it renumbers or invents
    revised = ResearchReport(
        title="t", abstract="x [5]", conclusion="y [7]", sections=[],
        references=[ResearchSource(id=5, title="B again", url="https://en.wikipedia.org/wiki/Solid-state_battery", content=""),
                    ResearchSource(id=7, title="New", url="https://new.com", content="")],
    )
    r2 = ground_references(revised, r.references, keep_all=True)
    assert [x.id for x in r2.references] == ["1", "2"] and r2.abstract == "x [2]" and r2.conclusion == "y ", (r2.abstract, r2.conclusion)
    print("ok")
