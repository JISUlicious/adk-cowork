---
name: xlsx-basic
description: "Use when the user wants to read, create, or edit .xlsx Excel spreadsheets."
license: MIT
---

# xlsx-basic

Read, create, and edit `.xlsx` files using `openpyxl` and `pandas`.

## Reading with pandas

```python
import pandas as pd

df = pd.read_excel("scratch/input.xlsx", sheet_name="Sheet1")
print(df.head())
print(df.describe())
```

## Reading with openpyxl (cell-level access)

```python
from openpyxl import load_workbook

wb = load_workbook("scratch/input.xlsx")
ws = wb.active
for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
    print(row)
```

## Creating from data

```python
import pandas as pd

data = {"Name": ["Alice", "Bob"], "Score": [95, 87]}
df = pd.DataFrame(data)
df.to_excel("scratch/output.xlsx", index=False)
```

## Creating with formatting

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

wb = Workbook()
ws = wb.active
ws.title = "Report"

# Header row
headers = ["Name", "Q1", "Q2", "Total"]
for col, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=h)
    cell.font = Font(bold=True)
    cell.fill = PatternFill("solid", fgColor="DAEEF3")

# Data rows
ws.append(["Alice", 100, 200, "=B2+C2"])
ws.append(["Bob", 150, 175, "=B3+C3"])

wb.save("scratch/output.xlsx")
```

## Notes

- Use `python_exec_run` with these snippets. Both `openpyxl` and `pandas` are available.
- Formulas persist as strings — they evaluate when the user opens the file in Excel/Sheets.
- Always read from and write to `scratch/` paths.
- Call `fs_promote` to move the final spreadsheet into `files/`.
