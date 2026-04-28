"""Hardcoded shell deny rules — last line of defence inside ``shell_run``.

Per the W5 design, the per-agent allowlist + user-confirm flow is the
*usability* gate: an agent calls ``pandoc``, the user approves, the
command runs. The deny rules below operate one layer deeper: even
when an agent has shell_run on its W1 surface AND the user grants
approval, these patterns still block. They are commands so
catastrophic that no normal office workflow needs them, and
allowing them once a user clicks "approve" too quickly would be
hard to recover from.

The list is intentionally small — limited to escalation, partition
manipulation, system shutdown, and recursive deletes against
canonical system roots. Office work doesn't need any of these.

Constitution §3.5: ``shell_run`` is argv-only. Every check below
operates on argv elements directly; we never assemble a string and
run regex on it.
"""

from __future__ import annotations

from pathlib import PurePath


# Programs blocked regardless of args. Match against ``argv[0]`` taken
# basename-only so ``/bin/sudo`` and ``sudo`` are equivalent.
_ALWAYS_DENY_PROGRAMS: frozenset[str] = frozenset({
    # Privilege escalation
    "sudo", "su", "doas", "pkexec",
    # Credential mutation
    "passwd", "chpasswd",
    # Partition / filesystem
    "fdisk", "gdisk", "parted", "sgdisk", "cfdisk", "wipefs",
    "mkfs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4",
    "mkfs.xfs", "mkfs.btrfs", "mkfs.fat", "mkfs.vfat",
    "mkfs.ntfs", "mkfs.f2fs",
    # System lifecycle
    "shutdown", "reboot", "halt", "poweroff",
    "systemctl", "service",
})


# Canonical system paths — recursive deletes against any of these
# (or a strict prefix of them) are blocked.
_SYSTEM_PATHS: frozenset[str] = frozenset({
    "/", "~", "$HOME",
    "/etc", "/usr", "/var", "/bin", "/sbin", "/lib", "/lib64",
    "/opt", "/boot", "/sys", "/proc", "/dev",
    "/Users", "/home",  # macOS / Linux user homes
    "/Applications", "/Library", "/System",  # macOS
})


def _is_recursive_rm_flag(arg: str) -> bool:
    """Match POSIX ``rm`` recursive flags. Argv form, no shell expansion,
    so we only need to look at exact-string forms.

    Recognised: ``-r``, ``-R``, ``-rf``, ``-Rf``, ``-fr``, ``-fR``,
    ``--recursive``, plus combined forms like ``-rfv`` or ``-rfvi``
    (any flag bag containing both 'r' and 'f' or just 'r' / 'R').
    """
    if not arg.startswith("-") or arg.startswith("--"):
        return arg == "--recursive"
    body = arg[1:]
    return "r" in body or "R" in body


def _path_targets_system(arg: str) -> bool:
    """True iff ``arg`` is a system path that recursive deletion should
    refuse to touch."""
    if arg in _SYSTEM_PATHS:
        return True
    # Strict prefixes — `/etc/foo` should also be blocked. We use
    # PurePath comparison so trailing slashes don't slip through.
    try:
        target = PurePath(arg)
    except (TypeError, ValueError):
        return False
    for root in _SYSTEM_PATHS:
        if root.startswith("$") or root == "~":
            continue  # symbolic; only exact-string match
        try:
            target.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def check_shell_deny(argv: list[str]) -> str | None:
    """Return a human-readable reason if argv hits a global deny rule;
    ``None`` means "not denied by these rules" (per-agent allowlist
    + user confirm still apply).

    The function is intentionally side-effect free and total; callers
    can plug it into both the gate (before the call lands) and the
    tool body (defence-in-depth in case the gate is bypassed by a
    callback ordering bug).
    """
    if not argv:
        return None
    program = PurePath(argv[0]).name
    if program in _ALWAYS_DENY_PROGRAMS:
        return f"{program!r} is in the global deny list"

    if program == "rm":
        recursive = any(_is_recursive_rm_flag(a) for a in argv[1:])
        if recursive:
            for arg in argv[1:]:
                if arg.startswith("-"):
                    continue
                if _path_targets_system(arg):
                    return (
                        f"recursive rm against system path {arg!r} "
                        f"blocked"
                    )

    if program == "dd":
        for arg in argv[1:]:
            if arg.startswith("if=/dev/") or arg.startswith("of=/dev/"):
                return f"dd against device path {arg!r} blocked"

    if program == "chmod":
        for arg in argv[1:]:
            if _path_targets_system(arg):
                return f"chmod on system path {arg!r} blocked"

    if program == "chown":
        for arg in argv[1:]:
            if _path_targets_system(arg):
                return f"chown on system path {arg!r} blocked"

    return None


__all__ = ["check_shell_deny"]
