"""``email_send`` — send a previously drafted .eml via SMTP.

This tool always returns ``confirmation_required`` on the first call.
The user must approve before the email is actually sent. The approval
comes as a follow-up message; the agent then calls ``email_send`` again
with ``confirmed=True``.
"""

from __future__ import annotations

import smtplib
from email import policy
from email.parser import BytesParser

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def email_send(
    eml_id: str,
    tool_context: ToolContext,
    confirmed: bool = False,
) -> dict[str, object]:
    """Send an email that was previously created by email_draft.

    Args:
        eml_id: The eml_id returned by ``email_draft``.
        confirmed: Set to ``True`` only after the user has approved sending.
            On first call, leave as ``False`` to request confirmation.

    Returns:
        ``{"confirmation_required": True, ...}`` if not yet confirmed,
        ``{"status": "sent", ...}`` on success,
        or ``{"error": ...}`` on failure.
    """
    ctx = get_cowork_context(tool_context)
    email_cfg = ctx.config.email

    # Find the .eml file
    eml_path = ctx.session.scratch_dir / f"{eml_id}.eml"
    if not eml_path.exists():
        return {"error": f"draft not found: {eml_id}.eml"}

    # Parse the .eml
    with open(eml_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    to = msg.get("To", "")
    cc = msg.get("Cc", "")
    subject = msg.get("Subject", "")
    from_addr = msg.get("From", "")

    # If not confirmed, return confirmation request
    if not confirmed:
        body_preview = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body_preview = part.get_content()[:200]
                    break
        else:
            body_preview = msg.get_content()[:200]

        return {
            "confirmation_required": True,
            "tool": "email_send",
            "eml_id": eml_id,
            "summary": f"Send email to {to}: \"{subject}\"",
            "details": {
                "from": from_addr,
                "to": to,
                "cc": cc or None,
                "subject": subject,
                "body_preview": body_preview,
            },
        }

    # Confirmed — actually send
    if not email_cfg.configured:
        return {
            "error": "SMTP not configured. Set [email] in cowork.toml or "
            "environment variables COWORK_SMTP_HOST, etc.",
        }

    all_recipients = [
        addr.strip()
        for addr in (to + "," + cc).split(",")
        if addr.strip()
    ]

    try:
        if email_cfg.use_tls:
            server = smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port)

        if email_cfg.smtp_user:
            server.login(email_cfg.smtp_user, email_cfg.resolved_password)

        server.sendmail(from_addr, all_recipients, msg.as_string())
        server.quit()
    except Exception as e:
        return {"error": f"SMTP send failed: {e}"}

    return {
        "status": "sent",
        "to": to,
        "subject": subject,
        "eml_id": eml_id,
    }
