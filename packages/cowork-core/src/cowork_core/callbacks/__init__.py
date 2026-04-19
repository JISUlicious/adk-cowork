"""Per-turn / per-model-call lifecycle callbacks wired on the root + sub-agents.

Today this module exposes model-call callbacks (turn-budget guard + audit
logging). Tool-call callbacks (policy enforcement, audit) still live in
``cowork_core.policy`` for historical reasons.
"""

from cowork_core.callbacks.model import make_model_callbacks

__all__ = ["make_model_callbacks"]
