"""Cowork agents — root orchestrator + specialist sub-agents."""

from cowork_core.agents.root_agent import (
    ROOT_HEADER,
    ROOT_TAIL,
    ROOT_WORKING_CONTEXT_FALLBACK,
    build_root_agent,
)

__all__ = [
    "ROOT_HEADER",
    "ROOT_TAIL",
    "ROOT_WORKING_CONTEXT_FALLBACK",
    "build_root_agent",
]
