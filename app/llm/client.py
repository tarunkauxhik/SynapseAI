"""
OpenAI-compatible LLM Client for Deep Research Agent.
Handles text generation and structured JSON outputs using Pydantic.
"""

import json
import logging
import re
from contextvars import ContextVar
from typing import Type, TypeVar, Optional
from pydantic import BaseModel, ValidationError

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Generic type variable for Pydantic models
T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Per-asyncio-task model override. Only eval runs set it (inside their own task),
# so production research tasks always use LLM_MODEL.
model_override: ContextVar[Optional[str]] = ContextVar("llm_model_override", default=None)


def strip_reasoning(text: str) -> str:
    """Removes <think>...</think> blocks (and a truncated trailing one)."""
    return _THINK_RE.sub("", text or "").split("<think>")[0].strip()


def extract_json(text: str) -> str:
    """Pulls the JSON object out of a reply that may contain <think> blocks, code fences or prose."""
    text = strip_reasoning(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("No JSON object found in LLM response.")
    return text[start:end + 1]


class LLMClient:
    """
    Async wrapper around any OpenAI-compatible chat completions API.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        # The SDK retries 429/5xx/connection errors with exponential backoff.
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=120.0, max_retries=2)

    async def _complete(self, system_prompt: str, prompt: str, temperature: float, json_mode: bool = False, model: Optional[str] = None) -> str:
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = await self.client.chat.completions.create(
            # Explicit model (eval judge) > eval-run override > LLM_MODEL
            model=model or model_override.get() or self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            # MiniMax: skip thinking (faster, no <think> in content). Models that don't know it ignore it.
            extra_body={"thinking": {"type": "disabled"}},
            **extra,
        )
        return strip_reasoning(response.choices[0].message.content or "")

    async def generate_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful research assistant.",
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> str:
        """
        Generate a standard string response.
        """
        return await self._complete(system_prompt, prompt, temperature, model=model)

    async def generate_structured_response(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str = "You are a precise data extraction assistant.",
        temperature: float = 0.1
    ) -> T:
        """
        Generates a response and parses it into the provided Pydantic model.
        Uses JSON mode with model-specific examples; retries once on invalid JSON.
        """
        # Get model-specific example based on the response model name
        model_name = response_model.__name__
        example = self._get_model_example(model_name)

        schema_instruction = f"""
You must respond with a valid JSON object.

{example}

RULES:
- Output ONLY the JSON object, no markdown or extra text
- Fill in ALL required fields with actual data based on the user's request
- Follow the exact structure shown in the example above
"""

        full_system_prompt = f"{system_prompt}\n\n{schema_instruction}"

        last_error: Optional[Exception] = None
        for attempt in (1, 2):
            content = await self._complete(full_system_prompt, prompt, temperature, json_mode=True)
            try:
                data = json.loads(extract_json(content))
                # Unwrap if the LLM wraps the object in "properties"
                if isinstance(data, dict) and isinstance(data.get("properties"), dict):
                    data = data["properties"]
                return response_model.model_validate(data)
            except (ValueError, ValidationError) as e:
                last_error = e
                logger.warning(f"Invalid {model_name} JSON (attempt {attempt}): {e} | raw: {content[:300]!r}")

        raise RuntimeError(f"LLM failed to generate valid {model_name} JSON: {last_error}")

    def _get_model_example(self, model_name: str) -> str:
        """Returns a concrete example for each model type."""
        examples = {
            "ResearchPlan": '''
Output a JSON object with this exact structure:
{
    "main_topic": "The main research topic",
    "subtopics": ["Subtopic 1", "Subtopic 2", "Subtopic 3"],
    "search_queries": ["search query 1", "search query 2", "search query 3"],
    "required_data_points": ["Data point 1", "Data point 2"]
}''',
            "ResearchReport": '''
Output a JSON object with this exact structure:
{
    "title": "Report Title",
    "abstract": "A brief summary of the report...",
    "sections": [
        {
            "title": "Section Title",
            "content": "Detailed content of this section...",
            "source_ids": []
        }
    ],
    "conclusion": "Final conclusions...",
    "references": [
        {
            "id": null,
            "title": "Source Title",
            "url": "https://example.com",
            "content": "Excerpt from source...",
            "relevance_score": 0.0,
            "credibility_score": 0.9
        }
    ],
    "metadata": {}
}''',
            "CritiqueFeedback": '''
Output a JSON object with this EXACT structure (arrays contain STRINGS ONLY):
{
    "overall_score": 5.5,
    "critique_round": 1,
    "strengths": ["Good coverage of main topic", "Well-structured report"],
    "weaknesses": ["Lacks depth in analysis", "Missing recent data"],
    "missing_information": ["Statistics on the topic", "More historical context"],
    "actionable_suggestions": ["Add more data", "Expand analysis section"],
    "decision": "revise"
}

CRITICAL - DO NOT USE OBJECTS:
- WRONG: "strengths": [{"description": "...", "evidence": "..."}]
- CORRECT: "strengths": ["The report covers the topic well", "Good sources"]
- All arrays must contain PLAIN TEXT STRINGS only
- decision must be "approve" or "revise"
- overall_score: 0.0 to 10.0 (be strict, most reports score 4-6)'''
        }
        return examples.get(model_name, "Output a valid JSON object matching the requested structure.")

# --- Dependency Injection ---
# Use this function to get the client instance in your agents
_client_instance: Optional[LLMClient] = None

async def get_llm_client() -> LLMClient:
    global _client_instance
    if _client_instance is None:
        # Import settings inside the function to avoid circular imports
        from app.config import settings
        _client_instance = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return _client_instance


if __name__ == "__main__":
    # Self-check for the parsing helpers: python -m app.llm.client
    assert extract_json('<think>use {braces}</think>\n```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Sure! {"a": {"b": 2}} done') == '{"a": {"b": 2}}'
    assert strip_reasoning("<think>cut off mid-thought") == ""
    try:
        extract_json("<think>{}</think>no json")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("ok")
