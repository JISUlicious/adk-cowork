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
from cowork_core.storage import InMemoryProjectStore, InMemoryUserStore
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
        user_store=InMemoryUserStore(),
        project_store=InMemoryProjectStore(),
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


class TestEmailSendEndToEnd:
    """End-to-end SMTP happy path. Monkey-patches ``smtplib.SMTP`` to
    capture ``starttls`` / ``login`` / ``sendmail`` calls without
    spinning up a real SMTP server — this verifies the wire shape
    Cowork sends without making the test depend on aiosmtpd or a
    flaky network listener."""

    def test_smtp_send_with_credentials_and_tls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build a context with SMTP fully configured.
        ws = Workspace(root=tmp_path)
        reg = ProjectRegistry(workspace=ws)
        project = reg.create("EmailSendE2E")
        session = reg.new_session("emailsendE2E")
        cfg = CoworkConfig(
            email=EmailConfig(
                default_from="me@cowork.local",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_user="me@cowork.local",
                smtp_password="hunter2",
                use_tls=True,
            ),
        )
        ctx = CoworkToolContext(
            workspace=ws,
            registry=reg,
            project=project,
            session=session,
            config=cfg,
            skills=SkillRegistry(),
            env=ManagedExecEnv(project=project, session=session),
            approvals=InMemoryApprovalStore(),
            user_store=InMemoryUserStore(),
            project_store=InMemoryProjectStore(),
        )
        fake = MagicMock()
        fake.state = {COWORK_CONTEXT_KEY: ctx}

        # Capture SMTP calls.
        recorded: dict[str, object] = {}

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None:
                recorded["host"] = host
                recorded["port"] = port

            def starttls(self) -> None:
                recorded["starttls"] = True

            def login(self, user: str, password: str) -> None:
                recorded["user"] = user
                recorded["password"] = password

            def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
                recorded["from"] = from_addr
                recorded["to"] = to_addrs
                recorded["msg_len"] = len(msg)
                recorded["msg_contains_subject"] = "Subject: Hi from M5" in msg

            def quit(self) -> None:
                recorded["quit"] = True

        import cowork_core.tools.email.send as send_mod
        monkeypatch.setattr(send_mod.smtplib, "SMTP", FakeSMTP)

        # Draft → confirmed send.
        draft = email_draft(
            to="alice@example.com",
            subject="Hi from M5",
            body="Hello!",
            cc="bob@example.com",
            tool_context=fake,
        )
        result = email_send(
            eml_id=str(draft["eml_id"]),
            confirmed=True,
            tool_context=fake,
        )

        assert result.get("status") == "sent", result
        assert result["to"] == "alice@example.com"
        # Wire shape verified.
        assert recorded["host"] == "smtp.example.com"
        assert recorded["port"] == 587
        assert recorded.get("starttls") is True
        assert recorded["user"] == "me@cowork.local"
        assert recorded["password"] == "hunter2"
        assert recorded["from"] == "me@cowork.local"
        assert "alice@example.com" in recorded["to"]  # type: ignore[operator]
        assert "bob@example.com" in recorded["to"]  # type: ignore[operator]
        assert recorded["msg_contains_subject"] is True
        assert recorded.get("quit") is True

    def test_smtp_no_tls_no_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Local relay path — no TLS, no auth. Cowork should not call
        ``starttls`` or ``login`` when those are turned off."""
        ws = Workspace(root=tmp_path)
        reg = ProjectRegistry(workspace=ws)
        project = reg.create("EmailLocalRelay")
        session = reg.new_session("emaillocalrelay")
        cfg = CoworkConfig(
            email=EmailConfig(
                default_from="me@cowork.local",
                smtp_host="localhost",
                smtp_port=25,
                use_tls=False,
            ),
        )
        ctx = CoworkToolContext(
            workspace=ws,
            registry=reg,
            project=project,
            session=session,
            config=cfg,
            skills=SkillRegistry(),
            env=ManagedExecEnv(project=project, session=session),
            approvals=InMemoryApprovalStore(),
            user_store=InMemoryUserStore(),
            project_store=InMemoryProjectStore(),
        )
        fake = MagicMock()
        fake.state = {COWORK_CONTEXT_KEY: ctx}

        recorded: dict[str, object] = {}

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None:
                recorded["init"] = (host, port)

            def starttls(self) -> None:
                recorded["starttls"] = True  # should never run

            def login(self, *_: object) -> None:
                recorded["login"] = True  # should never run

            def sendmail(self, *_: object) -> None:
                recorded["sendmail"] = True

            def quit(self) -> None:
                recorded["quit"] = True

        import cowork_core.tools.email.send as send_mod
        monkeypatch.setattr(send_mod.smtplib, "SMTP", FakeSMTP)

        draft = email_draft(
            to="alice@example.com",
            subject="No-TLS",
            body="Plain SMTP.",
            tool_context=fake,
        )
        result = email_send(
            eml_id=str(draft["eml_id"]),
            confirmed=True,
            tool_context=fake,
        )

        assert result.get("status") == "sent", result
        assert recorded["init"] == ("localhost", 25)
        assert "starttls" not in recorded
        assert "login" not in recorded
        assert recorded.get("sendmail") is True
        assert recorded.get("quit") is True

    def test_smtp_send_failure_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SMTP exceptions surface as ``{"error": ...}`` rather than
        propagating — keeps the agent loop alive."""
        ws = Workspace(root=tmp_path)
        reg = ProjectRegistry(workspace=ws)
        project = reg.create("EmailFailing")
        session = reg.new_session("emailfailing")
        cfg = CoworkConfig(
            email=EmailConfig(
                default_from="me@cowork.local",
                smtp_host="smtp.example.com",
                use_tls=False,
            ),
        )
        ctx = CoworkToolContext(
            workspace=ws,
            registry=reg,
            project=project,
            session=session,
            config=cfg,
            skills=SkillRegistry(),
            env=ManagedExecEnv(project=project, session=session),
            approvals=InMemoryApprovalStore(),
            user_store=InMemoryUserStore(),
            project_store=InMemoryProjectStore(),
        )
        fake = MagicMock()
        fake.state = {COWORK_CONTEXT_KEY: ctx}

        class FakeSMTP:
            def __init__(self, *_: object) -> None:
                raise OSError("connection refused")

        import cowork_core.tools.email.send as send_mod
        monkeypatch.setattr(send_mod.smtplib, "SMTP", FakeSMTP)

        draft = email_draft(
            to="alice@example.com",
            subject="Boom",
            body="…",
            tool_context=fake,
        )
        result = email_send(
            eml_id=str(draft["eml_id"]),
            confirmed=True,
            tool_context=fake,
        )
        assert "error" in result
        assert "SMTP send failed" in str(result["error"])
        assert "connection refused" in str(result["error"])
