"""``email_draft`` — compose a .eml file in the session scratch dir."""

from __future__ import annotations

import uuid
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def email_draft(
    to: str,
    subject: str,
    body: str,
    tool_context: ToolContext,
    cc: str = "",
    attachments: list[str] | None = None,
) -> dict[str, object]:
    """Compose an email draft and save it as a .eml file in scratch/.

    Args:
        to: Recipient email address(es), comma-separated.
        subject: Email subject line.
        body: Plain-text email body.
        cc: CC recipients, comma-separated. Optional.
        attachments: List of project-relative file paths to attach. Optional.

    Returns:
        ``{"eml_id": ..., "path": ..., "to": ..., "subject": ...}`` on success,
        or ``{"error": ...}`` on failure.
    """
    ctx = get_cowork_context(tool_context)

    if not to.strip():
        return {"error": "recipient (to) is required"}
    if not subject.strip():
        return {"error": "subject is required"}

    from_addr = ctx.config.email.default_from or "user@cowork.local"
    eml_id = uuid.uuid4().hex[:12]

    msg: MIMEMultipart | MIMEText
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))
        for att_path in attachments:
            try:
                full = ctx.workspace.resolve(
                    f"projects/{ctx.project.slug}/{att_path}"
                )
                with open(full, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={full.name}",
                )
                msg.attach(part)
            except Exception as e:
                return {"error": f"failed to attach {att_path}: {e}"}
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["X-Cowork-EML-ID"] = eml_id

    out_path = ctx.session.scratch_dir / f"{eml_id}.eml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(msg.as_string())

    return {
        "eml_id": eml_id,
        "path": f"scratch/{eml_id}.eml",
        "to": to,
        "subject": subject,
    }
