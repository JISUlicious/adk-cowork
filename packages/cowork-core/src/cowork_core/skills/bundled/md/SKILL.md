---
name: md
description: "Use when the user wants to read, write, or convert Markdown documents."
license: MIT
---

# md

Read, write, and render Markdown using `markdown-it-py`.

## Read and display

Use `fs_read` to read any `.md` file directly — no special library needed.

## Write Markdown

Use `fs_write` to create `.md` files directly. Markdown is plain text.

```
fs_write("scratch/notes.md", "# Meeting Notes\n\n- Item one\n- Item two\n")
```

## Convert Markdown to HTML

```python
from markdown_it import MarkdownIt

md = MarkdownIt()
source = open("scratch/notes.md").read()
html = md.render(source)
with open("scratch/notes.html", "w") as f:
    f.write(html)
```

## Generate a Markdown table

```python
headers = ["Name", "Role", "Status"]
rows = [
    ["Alice", "Engineer", "Active"],
    ["Bob", "Designer", "On leave"],
]
lines = ["| " + " | ".join(headers) + " |"]
lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
for row in rows:
    lines.append("| " + " | ".join(row) + " |")
with open("scratch/table.md", "w") as f:
    f.write("\n".join(lines) + "\n")
```

## Notes

- For simple read/write, use `fs_read` and `fs_write` directly — no `python_exec_run` needed.
- Use `python_exec_run` only when you need HTML conversion or programmatic generation.
- `markdown-it-py` is available in the sandbox.
