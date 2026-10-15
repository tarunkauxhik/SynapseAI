"""
Wikipedia search tool with Policy Compliance (User-Agent) and Pydantic integration.
"""

import logging
import asyncio
import re
import time
from typing import List
import aiohttp
from urllib.parse import quote

from app.models.research import ResearchSource

logger = logging.getLogger(__name__)

class WikipediaTool:
    """
    Tool for searching Wikipedia.

    IMPORTANT: You MUST provide a 'user_agent' string that identifies your bot
    and provides contact info (e.g., "MyResearchBot/1.0 (me@example.com)").
    Wikipedia blocks requests without this.
    """

    _RATE_LIMIT_DELAY = 1.0 # Wikipedia requests polite 1 request/sec for bots
    _TIMEOUT = aiohttp.ClientTimeout(total=30)
    _last_request_time = 0.0

    def __init__(self, user_agent: str = "SynapseAIBot/1.0 (research-tool@localhost)"):
        self.base_url = "https://en.wikipedia.org/w/api.php"
        self.user_agent = user_agent

    async def _enforce_rate_limit(self):
        """Sleeps if requests are too frequent."""
        current_time = time.time()
        time_since = current_time - self._last_request_time
        if time_since < self._RATE_LIMIT_DELAY:
            await asyncio.sleep(self._RATE_LIMIT_DELAY - time_since)
        self._last_request_time = time.time()

    async def search(self, query: str, max_results: int = 3) -> List[ResearchSource]:
        """
        Search for articles and return them as ResearchSource objects.
        """
        await self._enforce_rate_limit()

        try:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "format": "json",
                "utf8": 1,
                "formatversion": 2
            }

            logger.info(f"Wiki Search: {query}")
            # One session per search (Wikipedia requires the User-Agent header)
            async with aiohttp.ClientSession(headers={"User-Agent": self.user_agent}, timeout=self._TIMEOUT) as session:
                async with session.get(self.base_url, params=params) as response:
                    if response.status != 200:
                        logger.warning(f"Wiki API Error: {response.status}")
                        return []

                    data = await response.json()

            results = []
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "")

                # Convert Snippet HTML to text (simple cleanup)
                snippet = self._clean_html(item.get("snippet", ""))

                results.append(ResearchSource(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{quote(title)}",
                    content=f"Snippet: {snippet}",
                    credibility_score=0.9 # Wikipedia is generally high credibility
                ))

            return results

        except Exception as e:
            logger.error(f"Wiki Search Exception: {e}")
            return []

    @staticmethod
    def _clean_html(text: str) -> str:
        """Removes simple HTML tags from search snippets."""
        text = re.sub(r'<[^>]+>', '', text) # Remove tags
        text = re.sub(r'\s+', ' ', text)    # Normalize whitespace
        return text.strip()
