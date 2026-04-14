"""Email tools — draft and send emails via SMTP.

``email_draft`` writes a ``.eml`` file to the session scratch dir.
``email_send`` sends a previously drafted ``.eml`` via SMTP, with a
mandatory confirmation step.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.email.draft import email_draft
from cowork_core.tools.email.send import email_send
from cowork_core.tools.registry import ToolRegistry


def register_email_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(email_draft))
    registry.register(FunctionTool(email_send))


__all__ = ["email_draft", "email_send", "register_email_tools"]
