---
name: pdf-read
description: "Use when the user wants to extract text or metadata from a PDF file."
license: MIT
---

# pdf-read

Extract text and metadata from `.pdf` files using `pypdf`.

## Extract all text

```python
from pypdf import PdfReader

reader = PdfReader("scratch/input.pdf")
for i, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    print(f"--- Page {i+1} ---")
    print(text)
```

## Extract metadata

```python
from pypdf import PdfReader

reader = PdfReader("scratch/input.pdf")
meta = reader.metadata
print(f"Title: {meta.title}")
print(f"Author: {meta.author}")
print(f"Pages: {len(reader.pages)}")
print(f"Creator: {meta.creator}")
```

## Extract specific pages

```python
from pypdf import PdfReader

reader = PdfReader("scratch/input.pdf")
# Extract just pages 2-4 (0-indexed)
for page in reader.pages[1:4]:
    print(page.extract_text() or "")
```

## Save extracted text to file

```python
from pypdf import PdfReader

reader = PdfReader("scratch/input.pdf")
lines = []
for page in reader.pages:
    lines.append(page.extract_text() or "")
with open("scratch/extracted.txt", "w") as f:
    f.write("\n\n".join(lines))
```

## Notes

- Use `python_exec_run` with these snippets. The `pypdf` library is available.
- This skill is read-only. PDF creation and form-filling are out of scope for v0.1.
- Scanned PDFs (images) won't yield text — OCR is not included.
- Always read from `scratch/` or `files/` paths.
