---
name: plot
description: "Use when the user wants to create charts, graphs, or data visualizations as PNG images."
license: MIT
---

# plot

Create charts and plots using `matplotlib` with the Agg (non-GUI) backend.

## Bar chart

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

categories = ["Q1", "Q2", "Q3", "Q4"]
values = [120, 150, 170, 200]

fig, ax = plt.subplots()
ax.bar(categories, values)
ax.set_title("Quarterly Revenue")
ax.set_ylabel("Revenue ($K)")
fig.savefig("scratch/chart.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

## Line chart

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

months = ["Jan", "Feb", "Mar", "Apr", "May"]
sales = [30, 45, 38, 52, 61]

fig, ax = plt.subplots()
ax.plot(months, sales, marker="o")
ax.set_title("Monthly Sales")
ax.set_ylabel("Units")
ax.grid(True, alpha=0.3)
fig.savefig("scratch/sales.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

## Pie chart

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

labels = ["Product A", "Product B", "Product C"]
sizes = [45, 30, 25]

fig, ax = plt.subplots()
ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
ax.set_title("Market Share")
fig.savefig("scratch/pie.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

## Chart from pandas DataFrame

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_excel("scratch/data.xlsx")
fig, ax = plt.subplots(figsize=(10, 6))
df.plot(kind="bar", x=df.columns[0], ax=ax)
ax.set_title("Data Overview")
fig.savefig("scratch/overview.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

## Notes

- Always set `matplotlib.use("Agg")` before importing `pyplot` — there is no display.
- Always call `plt.close(fig)` to free memory.
- Output to `scratch/*.png`. Call `fs_promote` to move into `files/`.
- `matplotlib`, `pandas`, and `Pillow` are available in the sandbox.
