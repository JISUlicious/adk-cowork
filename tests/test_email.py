"""Tests for email tools (M5)."""

from __future__ import annotations

from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig, EmailConfig
from cowork_core.execenv import ManagedExecEnv
from cowork_core.approvals import InMemoryApprovalStore
from cowork_core.skills import SkillRegistry
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_core.tools.email.draft import email_draft
from cowork_core.tools.email.send import email_send
from cowork_core.workspace import ProjectRegistry, Workspace


@pytest.fixture()
def tctx(tmp_path: Path) -> MagicMock:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("EmailTest")
    session = reg.new_session("emailtest")
    cfg = CoworkConfig(email=EmailConfig(default_from="test@cowork.local"))
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=cfg,
        skills=SkillRegistry(),
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


class TestEmailDraft:
    def test_creates_eml_file(self, tctx: MagicMock) -> None:
        result = email_draft(
            to="alice@example.com",
            subject="Test Subject",
            body="Hello, world!",
            tool_context=tctx,
        )
        assert "eml_id" in result
        assert "path" in result
        assert result["to"] == "alice@example.com"
        assert result["subject"] == "Test Subject"

        # Verify the .eml file exists and is valid
        ctx = tctx.state[COWORK_CONTEXT_KEY]
        eml_path = ctx.session.scratch_dir / f"{result['eml_id']}.eml"
        assert eml_path.exists()

        with eml_path.open("rb") as f:
            msg = BytesParser(policy=email_policy.default).parse(f)
        assert msg["To"] == "alice@example.com"
        assert msg["Subject"] == "Test Subject"
        assert msg["From"] == "test@cowork.local"

    def test_rejects_empty_to(self, tctx: MagicMock) -> None:
        result = email_draft(to="", subject="Test", body="Hi", tool_context=tctx)
        assert "error" in result

    def test_rejects_empty_subject(self, tctx: MagicMock) -> None:
        result = email_draft(to="a@b.com", subject="", body="Hi", tool_context=tctx)
        assert "error" in result

    def test_cc_header(self, tctx: MagicMock) -> None:
        result = email_draft(
            to="alice@example.com",
            subject="Test",
            body="Hi",
            cc="bob@example.com",
            tool_context=tctx,
        )
        ctx = tctx.state[COWORK_CONTEXT_KEY]
        eml_path = ctx.session.scratch_dir / f"{result['eml_id']}.eml"
        with eml_path.open("rb") as f:
            msg = BytesParser(policy=email_policy.default).parse(f)
        assert msg["Cc"] == "bob@example.com"

    def test_with_attachment(self, tctx: MagicMock) -> None:
        ctx = tctx.state[COWORK_CONTEXT_KEY]
        # Create a file to attach
        att_path = ctx.workspace.resolve(f"projects/{ctx.project.slug}/files")
        att_path.mkdir(parents=True, exist_ok=True)
        (att_path / "report.txt").write_text("data here")

        result = email_draft(
            to="alice@example.com",
            subject="With attachment",
            body="See attached.",
            attachments=["files/report.txt"],
            tool_context=tctx,
        )
        assert "eml_id" in result
        assert "error" not in result


class TestEmailSend:
    def test_returns_confirmation_on_first_call(self, tctx: MagicMock) -> None:
        # First, draft an email
        draft_result = email_draft(
            to="alice@example.com",
            subject="Test",
            body="Hello!",
            tool_context=tctx,
        )
        eml_id = draft_result["eml_id"]

        # Call send without confirmed=True
        result = email_send(eml_id=str(eml_id), tool_context=tctx)
        assert result.get("confirmation_required") is True
        assert "summary" in result
        assert "alice@example.com" in str(result["summary"])

    def test_send_fails_without_smtp_config(self, tctx: MagicMock) -> None:
        draft_result = email_draft(
            to="alice@example.com",
            subject="Test",
            body="Hello!",
            tool_context=tctx,
        )
        eml_id = draft_result["eml_id"]

        # Call with confirmed=True but no SMTP config
        result = email_send(eml_id=str(eml_id), confirmed=True, tool_context=tctx)
        assert "error" in result
        assert "SMTP not configured" in str(result["error"])

    def test_send_missing_draft(self, tctx: MagicMock) -> None:
        result = email_send(eml_id="nonexistent", tool_context=tctx)
        assert "error" in result
        assert "not found" in str(result["error"])
