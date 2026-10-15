from __future__ import annotations
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Union

from .types import EvalCase, EvalResult, EvalSummary
from .evaluator import Evaluator
from .graders import Grader


# =============================================================================
# Eval Runner
# =============================================================================

class EvalRunner:
    
    def __init__(
        self,
        name: str,
        agent: Any,
        grader: Optional[Grader] = None,
        parallel: bool = False,
        max_concurrent: int = 5,
    ):
        self.name = name
        self.agent = agent
        self.grader = grader
        self.parallel = parallel
        self.max_concurrent = max_concurrent
        self.cases: List[EvalCase] = []
    
    # -------------------------------------------------------------------------
    # Case Management
    # -------------------------------------------------------------------------

    def add_case(self, input: str, expected: Any, name: Optional[str] = None, **metadata) -> "EvalRunner":
        self.cases.append(EvalCase(input=input, expected=expected, name=name, metadata=metadata))
        return self
    
    def add_cases(self, cases: List[EvalCase]) -> "EvalRunner":
        self.cases.extend(cases)
        return self
    
    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_json(cls, name: str, agent: Any, path: Union[str, Path], grader: Optional[Grader] = None) -> "EvalRunner":
        path = Path(path)
        data = json.loads(path.read_text())
        runner = cls(name, agent, grader)
        for item in data:
            runner.add_case(
                input=item["input"],
                expected=item["expected"],
                name=item.get("name"),
                **item.get("metadata", {}),
            )
        return runner
    
    @classmethod
    def from_list(cls, name: str, agent: Any, cases: List[dict], grader: Optional[Grader] = None) -> "EvalRunner":
        runner = cls(name, agent, grader)
        for item in cases:
            runner.add_case(
                input=item["input"],
                expected=item["expected"],
                name=item.get("name"),
                **item.get("metadata", {}),
            )
        return runner
    
    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    async def run(self, on_result=None) -> EvalSummary:
        """on_result(finished_results_in_case_order) is awaited each time a case finishes."""
        if self.parallel:
            results = await self._run_parallel(on_result)
        else:
            results = await self._run_sequential(on_result)
        return EvalSummary(name=self.name, results=results)

    def _evaluator(self) -> Evaluator:
        # Passing a class gives every case its own agent: the research adapter keeps
        # per-run state, so parallel cases must not share one instance.
        agent = self.agent() if isinstance(self.agent, type) else self.agent
        return Evaluator(agent, grader=self.grader)

    async def _run_sequential(self, on_result=None) -> List[EvalResult]:
        results = []
        for i, case in enumerate(self.cases):
            print(f"Running case {i+1}/{len(self.cases)}: {case.name}")
            result = await self._evaluator().run_case(case)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"  {status} Score: {result.score:.2f} | {result.reason[:50]}")
            if on_result:
                await on_result(results)
        return results

    async def _run_parallel(self, on_result=None) -> List[EvalResult]:
        """Up to max_concurrent cases at once; each is judged as soon as its research finishes."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        finished: dict = {}

        async def run_with_limit(i: int, case: EvalCase) -> EvalResult:
            async with semaphore:
                result = await self._evaluator().run_case(case)
            finished[i] = result
            print(f"  case {i+1}/{len(self.cases)} {'PASS' if result.passed else 'FAIL'} {result.score:.2f}: {case.name}")
            if on_result:
                await on_result([finished[k] for k in sorted(finished)])
            return result

        return list(await asyncio.gather(*(run_with_limit(i, c) for i, c in enumerate(self.cases))))

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def save_results(self, summary: EvalSummary, path: Optional[Union[str, Path]] = None) -> str:
        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = Path(f"eval_results_{self.name}_{timestamp}.json")
        else:
            path = Path(path)
        path.write_text(json.dumps(summary.to_dict(), indent=2))
        print(f"Results saved to: {path}")
        return str(path)
