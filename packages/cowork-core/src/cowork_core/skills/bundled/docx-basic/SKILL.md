---
name: docx-basic
description: "Use when the user wants to read, create, or edit .docx Word documents."
license: MIT
---

# docx-basic

Read, create, and simple-edit `.docx` files using `python-docx`.

## Reading a .docx

```python
from docx import Document

doc = Document("scratch/input.docx")
for para in doc.paragraphs:
    print(para.text)
```

## Creating a .docx

```python
from docx import Document

doc = Document()
doc.add_heading("Title", level=0)
doc.add_paragraph("First paragraph of the document.")
doc.add_paragraph("A bullet point", style="List Bullet")
doc.save("scratch/output.docx")
```

## Editing a .docx (replace text)

```python
from docx import Document

doc = Document("scratch/input.docx")
for para in doc.paragraphs:
    if "OLD_TEXT" in para.text:
        for run in para.runs:
            run.text = run.text.replace("OLD_TEXT", "NEW_TEXT")
doc.save("scratch/output.docx")
```

## Adding a table

```python
from docx import Document

doc = Document()
table = doc.add_table(rows=1, cols=3, style="Table Grid")
hdr = table.rows[0].cells
hdr[0].text, hdr[1].text, hdr[2].text = "Name", "Role", "Email"
for name, role, email in data:
    row = table.add_row().cells
    row[0].text, row[1].text, row[2].text = name, role, email
doc.save("scratch/report.docx")
```

## Notes

- Use `python_exec_run` with these snippets. The `python-docx` library is available.
- Always read from and write to `scratch/` paths.
- Call `fs_promote` to move the final document into `files/`.
- Complex features (tracked changes, mail merge, embedded macros) are out of scope.
