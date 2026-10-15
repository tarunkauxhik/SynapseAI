"""
Web search tool using Tavily with Pydantic integration.
"""

import logging
import asyncio
import time
from typing import List, Optional
import aiohttp

from app.models.research import ResearchSource

logger = logging.getLogger(__name__)

class WebSearchTool:
    """
    Tool for searching the web via Tavily.
    No fallback: the Researcher runs Wikipedia alongside, which is then the only source.
    """

    _RATE_LIMIT_DELAY = 1.0 # 1 second between search requests
    _TIMEOUT = aiohttp.ClientTimeout(total=30)
    _last_request_time = 0.0

    def __init__(self, tavily_api_key: Optional[str] = None):
        self.tavily_api_key = tavily_api_key

    async def _enforce_rate_limit(self):
        current_time = time.time()
        time_since = current_time - self._last_request_time
        if time_since < self._RATE_LIMIT_DELAY:
            await asyncio.sleep(self._RATE_LIMIT_DELAY - time_since)
        self._last_request_time = time.time()

    async def search(self, query: str, max_results: int = 5) -> List[ResearchSource]:
        """
        Main entry point. Returns [] if Tavily is unavailable (Wikipedia-only research).
        """
        if not self.tavily_api_key:
            logger.warning("TAVILY_API_KEY not set: web search skipped, using Wikipedia only.")
            return []

        await self._enforce_rate_limit()

        # One session per search: safe when several tasks run at once
        async with aiohttp.ClientSession(timeout=self._TIMEOUT) as session:
            results = await self.search_tavily(session, query, max_results)

        if not results:
            logger.warning(f"Tavily returned no results for {query!r}: using Wikipedia only.")

        return results

    async def search_tavily(self, session: aiohttp.ClientSession, query: str, max_results: int = 5) -> List[ResearchSource]:
        """
        Uses Tavily API. Returns validated ResearchSource objects.
        """
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.tavily_api_key,
                "query": query,
                "max_results": max_results,
                # For Deep Research, we want the answer + raw content if possible
                "include_answer": True,
                "search_depth": "basic", # Use "advanced" for deeper (slower/more expensive) searches
            }

            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Tavily Error: {response.status}")
                    return []

                data = await response.json()
                results = []

                # Parse Tavily 'results' list
                for item in data.get("results", []):
                    # Tavily gives 'content' which is a long snippet.
                    # We map this to our 'content' field.
                    source = ResearchSource(
                        title=item.get("title", "Untitled"),
                        url=item.get("url"),
                        content=item.get("content", ""),
                        credibility_score=item.get("score", 0.8) # Tavily score is usually relevance
                    )
                    results.append(source)

                return results

        except Exception as e:
            logger.error(f"Tavily Exception: {e}")
            return []
