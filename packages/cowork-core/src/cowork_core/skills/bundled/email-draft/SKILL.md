---
name: email-draft
description: "Use when the user wants to compose an email draft saved as a .eml file with optional attachments."
license: MIT
---

# email-draft

Compose email drafts as `.eml` files using Python's `email.mime` stdlib.

## Simple text email

```python
from email.mime.text import MIMEText

msg = MIMEText("Hi Alice,\n\nPlease find the report attached.\n\nBest,\nBob")
msg["Subject"] = "Q4 Report"
msg["From"] = "bob@example.com"
msg["To"] = "alice@example.com"

with open("scratch/draft.eml", "w") as f:
    f.write(msg.as_string())
```

## Email with attachment

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

msg = MIMEMultipart()
msg["Subject"] = "Q4 Report"
msg["From"] = "bob@example.com"
msg["To"] = "alice@example.com"

body = MIMEText("Hi Alice,\n\nPlease find the report attached.\n\nBest,\nBob")
msg.attach(body)

# Attach a file from scratch/
filepath = "scratch/report.docx"
with open(filepath, "rb") as f:
    part = MIMEBase("application", "octet-stream")
    part.set_payload(f.read())
encoders.encode_base64(part)
part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(filepath)}")
msg.attach(part)

with open("scratch/draft.eml", "w") as f:
    f.write(msg.as_string())
```

## Email with multiple recipients

```python
from email.mime.text import MIMEText

msg = MIMEText("Team,\n\nMeeting moved to 3pm.\n\nThanks")
msg["Subject"] = "Meeting Update"
msg["From"] = "bob@example.com"
msg["To"] = "alice@example.com, charlie@example.com"
msg["Cc"] = "manager@example.com"

with open("scratch/draft.eml", "w") as f:
    f.write(msg.as_string())
```

## Notes

- Use `python_exec_run` with these snippets. Only stdlib `email` is needed.
- This skill creates `.eml` drafts — it does NOT send email.
- The user can open `.eml` files in any email client to review and send.
- Call `fs_promote` to move the draft into `files/`.
- Sending email requires explicit user confirmation (policy §2.6) and is out of scope for this skill.
