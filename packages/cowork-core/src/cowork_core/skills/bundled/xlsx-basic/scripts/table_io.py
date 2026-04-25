# SPDX-License-Identifier: MIT
"""Reusable table I/O helpers for the ``xlsx-basic`` skill.

Wraps the common pandas-based read / write patterns with sensible
defaults: first row is the header, sheet selection by name or
positional index, and writes that don't trip over openpyxl's
default formatting.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def read_table(
    path: str,
    *,
    sheet: str | int = 0,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read a sheet from ``path`` into a DataFrame.

    ``sheet`` accepts a sheet name (str) or a 0-based positional
    index (int). When ``columns`` is supplied, only those column
    names are returned (handy for narrowing very-wide sheets
    before piping into a chart helper).
    """
    df = pd.read_excel(path, sheet_name=sheet)
    if columns is not None:
        df = df[columns]
    return df


def write_table(
    df: pd.DataFrame,
    path: str,
    *,
    sheet_name: str = "Sheet1",
    index: bool = False,
) -> str:
    """Write ``df`` to ``path`` (single sheet). Returns the path."""
    df.to_excel(path, sheet_name=sheet_name, index=index)
    return path


def write_tables(
    sheets: dict[str, pd.DataFrame],
    path: str,
    *,
    index: bool = False,
) -> str:
    """Write multiple DataFrames to a single workbook, one per sheet.

    The dict's keys become sheet names. Caller controls order via
    insertion order (Python 3.7+).
    """
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=index)
    return path


def cell(workbook_path: str, sheet: str, address: str) -> Any:
    """Read a single cell from an existing workbook by address
    (e.g. ``"B2"``). Useful when you need a formula's stored value
    without loading the whole sheet into a DataFrame."""
    from openpyxl import load_workbook

    wb = load_workbook(workbook_path, data_only=True)
    try:
        return wb[sheet][address].value
    finally:
        wb.close()
