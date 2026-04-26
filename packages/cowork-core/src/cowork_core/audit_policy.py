"""Per-tool audit capture policy (Slice V1).

Each tool name has an entry in ``TOOL_AUDIT_POLICIES`` describing
which arg keys are safe to log + how to summarise the result. Tools
not in the table fall back to ``DEFAULT_POLICY`` — log only the
tool name + timestamp + ok/error flag, no args, no result.

The defaults are deliberately conservative so an audit log doesn't
accidentally accumulate file contents, email bodies, or memory
pages. Tools the operator wants to capture more for can be opted
in here without touching the tool registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CaptureResultKind = Literal["none", "summary", "full"]


@dataclass(frozen=True)
class ToolAuditPolicy:
    """Per-tool capture policy.

    ``args_keys`` — whitelist of arg keys to log. Any key NOT listed
    is dropped from the audit row. Empty set = log no args.

    ``truncate_arg_to_bytes`` — per-value cap after JSON encoding.
    Long values (e.g. python_exec code) are truncated mid-string with
    a ``…`` suffix.

    ``capture_result_kind``:

    * ``"none"`` (default for unknown tools) — log only ``{ok: bool}``.
      Keeps the audit log lean and prevents result content from
      leaking even when the operator hasn't policy'd a tool yet.
    * ``"summary"`` — log ``{ok, error?, repr}`` where ``repr`` is a
      truncated string repr of the result (256 bytes max). Catches
      common indicator keys (``exit_code``, ``path``, ``status``,
      ``count``) verbatim; everything else falls into ``repr``.
    * ``"full"`` — log the entire result JSON, truncated to 4 KB.
      No tools default to this; the operator opts a tool in via
      config if they really want full capture (Tier F).
    """

    args_keys: frozenset[str] = field(default_factory=frozenset)
    truncate_arg_to_bytes: int = 4096
    capture_result_kind: CaptureResultKind = "none"


# Default for tools without an explicit policy entry. Conservative:
# tool name + ok flag only. New tools added without an entry are
# logged safely; the operator can extend the table later.
DEFAULT_POLICY = ToolAuditPolicy()


# Per-tool policies. Match the names the tool registry uses
# (``ToolRegistry.register(FunctionTool(<func>))`` so the tool name
# is the function name).
TOOL_AUDIT_POLICIES: dict[str, ToolAuditPolicy] = {
    # ── Filesystem (paths only — never file content) ─────────────
    "fs_read":      ToolAuditPolicy(args_keys=frozenset({"path"}), capture_result_kind="summary"),
    "fs_write":     ToolAuditPolicy(args_keys=frozenset({"path"}), capture_result_kind="summary"),
    "fs_edit":      ToolAuditPolicy(args_keys=frozenset({"path"}), capture_result_kind="summary"),
    "fs_promote":   ToolAuditPolicy(args_keys=frozenset({"src", "dst"}), capture_result_kind="summary"),
    "fs_list":      ToolAuditPolicy(args_keys=frozenset({"path"}), capture_result_kind="summary"),
    "fs_glob":      ToolAuditPolicy(args_keys=frozenset({"pattern"}), capture_result_kind="summary"),
    "fs_stat":      ToolAuditPolicy(args_keys=frozenset({"path"}), capture_result_kind="summary"),
    # ── Shell + python — capture the command for security audit ───
    "shell_run":        ToolAuditPolicy(args_keys=frozenset({"argv"}), capture_result_kind="summary"),
    "python_exec_run":  ToolAuditPolicy(args_keys=frozenset({"code"}), truncate_arg_to_bytes=2048, capture_result_kind="summary"),
    # ── Network ───────────────────────────────────────────────────
    "http_fetch":   ToolAuditPolicy(args_keys=frozenset({"url"}), capture_result_kind="summary"),
    "search_web":   ToolAuditPolicy(args_keys=frozenset({"query"}), capture_result_kind="summary"),
    # ── Email — capture metadata, never bodies ────────────────────
    "email_draft":  ToolAuditPolicy(args_keys=frozenset({"to", "subject"}), capture_result_kind="summary"),
    "email_send":   ToolAuditPolicy(args_keys=frozenset({"eml_id", "confirmed"}), capture_result_kind="summary"),
    # ── Skills / memory ──────────────────────────────────────────
    "load_skill":   ToolAuditPolicy(args_keys=frozenset({"name"}), capture_result_kind="summary"),
    "memory_read":      ToolAuditPolicy(args_keys=frozenset({"scope", "name"}), capture_result_kind="summary"),
    "memory_write":     ToolAuditPolicy(args_keys=frozenset({"scope", "name"}), capture_result_kind="summary"),
    "memory_log":       ToolAuditPolicy(args_keys=frozenset({"scope", "kind", "title"}), capture_result_kind="summary"),
    "memory_remember":  ToolAuditPolicy(args_keys=frozenset({"scope"}), capture_result_kind="summary"),
}


def policy_for(tool_name: str) -> ToolAuditPolicy:
    """Return the audit policy for ``tool_name``. Falls back to
    ``DEFAULT_POLICY`` (log nothing structured) for unknown tools."""
    return TOOL_AUDIT_POLICIES.get(tool_name, DEFAULT_POLICY)
