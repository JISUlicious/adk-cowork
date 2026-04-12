"""Cowork agents. M0 shipped only the root; sub-agents arrive in M3."""

from cowork_core.agents.root_agent import ROOT_INSTRUCTION_BASE, build_root_agent

__all__ = ["ROOT_INSTRUCTION_BASE", "build_root_agent"]
