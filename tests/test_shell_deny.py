"""Tests for W5 — global ``shell_run`` deny rules.

The deny rules are the last line of defence inside ``shell_run``: even
when an agent has the tool on its W1 surface AND the user has granted
approval through the gate, these patterns still block. They cover
escalation, partition manipulation, system shutdown, and recursive
deletes against canonical system roots — commands no normal office
workflow needs.
"""

from __future__ import annotations

import pytest
from cowork_core.tools.shell.deny import check_shell_deny


class TestAlwaysDenyPrograms:
    """argv[0] alone is enough to block — args don't matter."""

    @pytest.mark.parametrize("program", [
        "sudo", "su", "doas", "pkexec",
        "passwd", "chpasswd",
        "fdisk", "gdisk", "parted",
        "mkfs", "mkfs.ext4", "mkfs.xfs", "mkfs.fat",
        "shutdown", "reboot", "halt", "poweroff",
        "systemctl", "service",
    ])
    def test_program_is_denied(self, program: str) -> None:
        reason = check_shell_deny([program, "anything"])
        assert reason is not None
        assert program in reason

    @pytest.mark.parametrize("program", [
        "/usr/bin/sudo", "/bin/su", "/sbin/mkfs.ext4",
    ])
    def test_absolute_path_also_denied(self, program: str) -> None:
        """Match by basename so /bin/sudo and sudo are equivalent —
        the allowlist evaluator does the same so it's important they
        agree on the lookup key."""
        reason = check_shell_deny([program])
        assert reason is not None


class TestRmRecursiveDeny:
    """``rm`` is fine for non-system paths; recursive deletion against
    system paths is blocked."""

    def test_rm_rf_root_denied(self) -> None:
        assert check_shell_deny(["rm", "-rf", "/"]) is not None

    def test_rm_rf_home_denied(self) -> None:
        assert check_shell_deny(["rm", "-rf", "~"]) is not None
        assert check_shell_deny(["rm", "-rf", "$HOME"]) is not None

    def test_rm_rf_etc_denied(self) -> None:
        assert check_shell_deny(["rm", "-rf", "/etc"]) is not None

    def test_rm_rf_etc_subdir_denied(self) -> None:
        """Recursive into a system subtree is just as bad as the root."""
        assert check_shell_deny(["rm", "-rf", "/etc/foo"]) is not None
        assert check_shell_deny(["rm", "-rf", "/usr/local/bin"]) is not None

    def test_rm_rf_scratch_allowed(self) -> None:
        """Project-local cleanup must remain possible — only system
        paths are blocked."""
        assert check_shell_deny(["rm", "-rf", "scratch/old"]) is None
        assert check_shell_deny(["rm", "-rf", "build"]) is None

    def test_rm_without_recursive_allowed(self) -> None:
        """Non-recursive rm (single file) is fine even on system paths
        — kernel will reject it anyway, and a 'rm /etc/hosts' is a real
        diagnostic command sometimes."""
        assert check_shell_deny(["rm", "/etc/hosts"]) is None

    @pytest.mark.parametrize("flag", ["-r", "-R", "-rf", "-Rf", "-fr",
                                       "--recursive", "-rfv"])
    def test_recursive_flag_variants(self, flag: str) -> None:
        assert check_shell_deny(["rm", flag, "/etc"]) is not None


class TestDdDeny:
    def test_dd_against_device_denied(self) -> None:
        assert check_shell_deny(["dd", "if=/dev/sda", "of=foo.img"]) is not None
        assert check_shell_deny(["dd", "if=foo.img", "of=/dev/sda"]) is not None

    def test_dd_file_to_file_allowed(self) -> None:
        assert check_shell_deny(["dd", "if=in.bin", "of=out.bin"]) is None


class TestChmodChownDeny:
    def test_chmod_on_system_path_denied(self) -> None:
        assert check_shell_deny(["chmod", "-R", "777", "/etc"]) is not None
        assert check_shell_deny(["chmod", "777", "/"]) is not None

    def test_chmod_local_file_allowed(self) -> None:
        assert check_shell_deny(["chmod", "+x", "scripts/run.sh"]) is None

    def test_chown_on_system_path_denied(self) -> None:
        assert check_shell_deny(["chown", "-R", "user", "/usr"]) is not None


class TestEdgeCases:
    def test_empty_argv_returns_none(self) -> None:
        """No program to deny."""
        assert check_shell_deny([]) is None

    def test_unrelated_command_passes(self) -> None:
        """The deny list is small by design; everyday commands pass."""
        assert check_shell_deny(["pandoc", "-o", "out.pdf", "in.md"]) is None
        assert check_shell_deny(["git", "status"]) is None
        assert check_shell_deny(["ls", "-la"]) is None
        assert check_shell_deny(["python", "-c", "print('hi')"]) is None
