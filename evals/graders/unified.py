"""
Unified Grader - runs ALL grading logics in a single pass and aggregates results.
Provides comprehensive evaluation without running agent multiple times.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Optional
from .base import Grader
from ..types import EvalCase, ToolCall
from .client_adapter import get_llm_adapter


UNIFIED_GRADER_PROMPT = """
You are an expert evaluator performing a comprehensive assessment of an AI agent's response.

## Task
{input}

## Expected Output
{expected}

## Actual Output
{output}

## Tools Used by Agent
{tools_summary}

## Sources/Citations Found
{sources_summary}

Evaluate the response on ALL of the following dimensions:

1. **Content Quality** (0-100): Does the output meet expectations? Is it accurate, complete, and relevant?
2. **Tool Usage** (0-100): Did the agent use appropriate tools? Were the right tools called?
3. **Source Citation** (0-100): Are claims backed by sources? Are citations provided where needed?
4. **Reasoning Quality** (0-100): Is the reasoning coherent and logical?

For each dimension, provide a score and brief explanation.

Respond in this EXACT format:
CONTENT_SCORE: [0-100]
CONTENT_REASON: [explanation]
TOOL_SCORE: [0-100]
TOOL_REASON: [explanation]
SOURCE_SCORE: [0-100]
SOURCE_REASON: [explanation]
REASONING_SCORE: [0-100]
REASONING_REASON: [explanation]
OVERALL_VERDICT: [PASS/FAIL]
OVERALL_SCORE: [0-100]
OVERALL_REASON: [summary]
"""


class UnifiedGrader(Grader):
    """
    Unified grader that evaluates on ALL dimensions in a single LLM call:
    - Content Quality (like LLMGrader)
    - Tool Usage (like ToolUsageGrader)
    - Source Citation (like SourceCitationGrader)
    - Reasoning Quality (like ReasoningCoherenceGrader)
    
    This saves tokens by doing comprehensive evaluation in one pass.
    """
    
    def __init__(
        self,
        pass_threshold: float = 0.6,
        model: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            pass_threshold: Minimum overall score to pass (0-1 scale)
            model: Optional model override
            weights: Optional weights for each dimension (default: equal weights)
        """
        self.pass_threshold = pass_threshold
        self.model = model
        self.weights = weights or {
            "content": 0.35,
            "tool": 0.25,
            "source": 0.25,
            "reasoning": 0.15,
        }
        self._client = None
    
    async def _get_client(self):
        if self._client is None:
            self._client = get_llm_adapter(self.model)
        return self._client
    
    def _format_tools_summary(self, case: EvalCase) -> str:
        """Format tools called for prompt."""
        tools_called = case.metadata.get("tools_called", [])
        expected_tools = case.metadata.get("expected_tools", [])
        
        if not tools_called and not expected_tools:
            return "No tools information available."
        
        lines = []
        if expected_tools:
            lines.append(f"Expected tools: {', '.join(expected_tools)}")
        
        if tools_called:
            tool_names = []
            for t in tools_called:
                if isinstance(t, ToolCall):
                    tool_names.append(t.name)
                elif isinstance(t, dict):
                    tool_names.append(t.get("name", "unknown"))
                elif isinstance(t, str):
                    tool_names.append(t)
            lines.append(f"Tools actually used: {', '.join(tool_names)}")
        else:
            lines.append("Tools actually used: None detected")
        
        return "\n".join(lines)
    
    def _format_sources_summary(self, case: EvalCase) -> str:
        """Format sources for prompt."""
        sources = case.metadata.get("sources", [])
        expected_sources = case.metadata.get("expected_sources", [])
        
        if not sources and not expected_sources:
            return "No source information available."
        
        lines = []
        if expected_sources:
            lines.append(f"Expected sources: {', '.join(expected_sources[:5])}")
        if sources:
            lines.append(f"Sources found in output: {', '.join(sources[:5])}")
        
        return "\n".join(lines) if lines else "No sources specified."
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse the structured LLM response."""
        result = {
            "content": {"score": 50, "reason": "Could not parse"},
            "tool": {"score": 50, "reason": "Could not parse"},
            "source": {"score": 50, "reason": "Could not parse"},
            "reasoning": {"score": 50, "reason": "Could not parse"},
            "overall": {"score": 50, "reason": "Could not parse", "passed": False},
        }
        
        # Tolerant of markdown (**CONTENT_SCORE:** 85), "85/100" and stray spacing
        for key in result:
            score = re.search(rf"{key}_SCORE[*_:=\s]*(\d{{1,3}})", response, re.IGNORECASE)
            if score:
                result[key]["score"] = min(int(score.group(1)), 100)
            reason = re.search(rf"{key}_REASON[*_:=\s]*(.+)", response, re.IGNORECASE)
            if reason:
                result[key]["reason"] = reason.group(1).strip().strip("*").strip()
        verdict = re.search(r"OVERALL_VERDICT[*_:=\s]*(PASS|FAIL)", response, re.IGNORECASE)
        result["overall"]["passed"] = bool(verdict) and verdict.group(1).upper() == "PASS"

        return result
    
    async def grade_async(self, output: str, case: EvalCase) -> tuple[bool, float, str]:
        """
        Grade on all dimensions in single LLM call.
        """
        client = await self._get_client()
        
        tools_summary = self._format_tools_summary(case)
        sources_summary = self._format_sources_summary(case)
        
        prompt = UNIFIED_GRADER_PROMPT.format(
            input=case.input,
            expected=case.expected,
            output=output[:30000],  # A full report is ~15-25k chars; the judge must see its references
            tools_summary=tools_summary,
            sources_summary=sources_summary,
        )
        
        response = await client.get_completion_async([
            {"role": "user", "content": prompt}
        ])
        
        parsed = self._parse_response(response.content or "")
        
        # Calculate weighted score
        weighted_score = (
            parsed["content"]["score"] * self.weights["content"] +
            parsed["tool"]["score"] * self.weights["tool"] +
            parsed["source"]["score"] * self.weights["source"] +
            parsed["reasoning"]["score"] * self.weights["reasoning"]
        ) / 100  # Convert to 0-1 scale
        
        passed = weighted_score >= self.pass_threshold
        
        # Store breakdown in case metadata for frontend display
        case.metadata["grader_breakdown"] = {
            "ContentQuality": {
                "passed": parsed["content"]["score"] >= 60,
                "score": parsed["content"]["score"] / 100,
                "reason": parsed["content"]["reason"],
                "weight": self.weights["content"],
            },
            "ToolUsage": {
                "passed": parsed["tool"]["score"] >= 60,
                "score": parsed["tool"]["score"] / 100,
                "reason": parsed["tool"]["reason"],
                "weight": self.weights["tool"],
            },
            "SourceCitation": {
                "passed": parsed["source"]["score"] >= 60,
                "score": parsed["source"]["score"] / 100,
                "reason": parsed["source"]["reason"],
                "weight": self.weights["source"],
            },
            "ReasoningQuality": {
                "passed": parsed["reasoning"]["score"] >= 60,
                "score": parsed["reasoning"]["score"] / 100,
                "reason": parsed["reasoning"]["reason"],
                "weight": self.weights["reasoning"],
            },
        }
        
        reason = f"Overall: {parsed['overall']['reason']} | Content: {parsed['content']['score']}% | Tools: {parsed['tool']['score']}% | Sources: {parsed['source']['score']}% | Reasoning: {parsed['reasoning']['score']}%"
        
        return passed, weighted_score, reason
    
    def grade(self, output: str, case: EvalCase) -> tuple[bool, float, str]:
        import asyncio
        return asyncio.run(self.grade_async(output, case))


if __name__ == "__main__":
    # Self-check for the judge-output parser: python -m evals.graders.unified
    g = UnifiedGrader()
    p = g._parse_response(
        "**CONTENT_SCORE:** 85/100\nCONTENT_REASON: Solid.\nTOOL_SCORE: 70\n"
        "SOURCE_SCORE : 40\nREASONING_SCORE: 120\nOVERALL_VERDICT: **PASS**\nOVERALL_SCORE: 66"
    )
    assert (p["content"]["score"], p["tool"]["score"], p["source"]["score"], p["reasoning"]["score"]) == (85, 70, 40, 100), p
    assert p["content"]["reason"] == "Solid." and p["overall"]["passed"] and p["overall"]["score"] == 66
    assert g._parse_response("nothing useful")["content"]["score"] == 50  # default when missing
    print("ok")
