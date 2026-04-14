"""Policy layer — permission modes and hooks."""

from cowork_core.policy.hooks import make_audit_callbacks
from cowork_core.policy.permissions import make_permission_callback

__all__ = ["make_audit_callbacks", "make_permission_callback"]
