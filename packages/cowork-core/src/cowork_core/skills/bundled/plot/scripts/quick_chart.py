# SPDX-License-Identifier: MIT
"""Reusable matplotlib helpers for the ``plot`` skill.

Each helper picks safe defaults (Agg backend, ``bbox_inches="tight"``,
``plt.close`` to free memory) so the agent can produce a chart in one
call without re-deriving boilerplate. Read the skill body via
``load_skill("plot")`` to see when to inline these into a
``python_exec_run`` call vs. writing fresh code.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # noqa: E402  — must precede pyplot import
import matplotlib.pyplot as plt  # noqa: E402


def bar_chart(
    categories: list[str],
    values: list[float],
    *,
    title: str = "",
    ylabel: str = "",
    output_path: str = "scratch/chart.png",
    dpi: int = 150,
) -> str:
    """Render a vertical bar chart and save to ``output_path``.

    Returns the saved path so the agent can chain a follow-up call
    (e.g. ``fs_promote``) without recomputing it.
    """
    fig, ax = plt.subplots()
    ax.bar(categories, values)
    if title:
        ax.set_title(title)
    if ylabel:
        ax.set_ylabel(ylabel)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return output_path


def line_chart(
    x: list[str | float],
    y: list[float],
    *,
    title: str = "",
    ylabel: str = "",
    output_path: str = "scratch/line.png",
    dpi: int = 150,
) -> str:
    """Single-series line chart with grid + circle markers."""
    fig, ax = plt.subplots()
    ax.plot(x, y, marker="o")
    if title:
        ax.set_title(title)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return output_path
