"""Agent-facing execution environment protocol + implementations."""

from cowork_core.execenv.base import ExecEnv, ExecEnvError
from cowork_core.execenv.localdir import LocalDirExecEnv
from cowork_core.execenv.managed import ManagedExecEnv

__all__ = [
    "ExecEnv",
    "ExecEnvError",
    "LocalDirExecEnv",
    "ManagedExecEnv",
]
