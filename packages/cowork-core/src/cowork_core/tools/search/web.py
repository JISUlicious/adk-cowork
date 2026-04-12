"""``search.web`` — zero-setup DuckDuckGo text search.

DuckDuckGo is the v0.1 default because it needs no API key and no account.
Other providers (Brave, Tavily, SearXNG) will be added behind optional config
keys in later milestones; this file is the single place where provider
dispatch happens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context

if TYPE_CHECKING:
    from ddgs import DDGS

_MAX_RESULTS_CAP = 20


def _ddg_search(query: str, max_results: int) -> list[dict[str, str]]:
    from ddgs import DDGS

    ddgs: DDGS
    with DDGS() as ddgs:
        return [
            {
                "title": str(r.get("title") or ""),
                "url": str(r.get("href") or r.get("url") or ""),
                "snippet": str(r.get("body") or ""),
            }
            for r in ddgs.text(query, max_results=max_results)
        ]


def search_web(
    query: str,
    tool_context: ToolContext,
    max_results: int = 8,
) -> dict[str, object]:
    """Search the web via the configured provider (default: DuckDuckGo).

    Args:
        query: The search string.
        max_results: How many hits to return (1-20).

    Returns:
        ``{"query", "provider", "results": [{"title", "url", "snippet"}...]}``
        or ``{"error": ...}``.
    """
    if not query or not query.strip():
        return {"error": "query must be a non-empty string"}
    ctx = get_cowork_context(tool_context)
    provider = ctx.config.search.provider
    n = max(1, min(int(max_results), _MAX_RESULTS_CAP))
    if provider != "duckduckgo":
        return {"error": f"search provider not yet supported: {provider!r}"}
    try:
        results = _ddg_search(query.strip(), n)
    except Exception as e:
        return {"error": f"search failed: {e}"}
    return {"query": query, "provider": provider, "results": results}
