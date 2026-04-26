"""Download python-build-standalone and install cowork wheels into it.

Produces a relocatable Python bundle under:

    packages/cowork-app/src-tauri/resources/python/<target-triple>/

The bundle includes:
  - CPython 3.12 standalone interpreter
  - cowork-core + cowork-server + cowork-server-app installed into
    its site-packages (cowork-server-web is hosted-only and NOT
    bundled — the desktop sidecar is single-user-only)
  - All runtime dependencies (FastAPI, uvicorn, google-adk, etc.)

Usage:
    uv run python scripts/bundle_python.py              # host platform only
    uv run python scripts/bundle_python.py --target aarch64-apple-darwin
    uv run python scripts/bundle_python.py --clean

After bundling, verify with:
    .../python/<triple>/bin/python -m cowork_server_app --help
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

# Pinned python-build-standalone release. Bump explicitly when refreshing.
PBS_RELEASE = "20260408"
PYTHON_VERSION = "3.12.13"

# target-triple -> (archive filename, sha256 when we fill it in — None means "skip check")
TARGETS: dict[str, str] = {
    "aarch64-apple-darwin": f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz",
    "x86_64-apple-darwin": f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-x86_64-apple-darwin-install_only.tar.gz",
    "x86_64-unknown-linux-gnu": f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "aarch64-unknown-linux-gnu": f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-aarch64-unknown-linux-gnu-install_only.tar.gz",
    "x86_64-pc-windows-msvc": f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-x86_64-pc-windows-msvc-install_only.tar.gz",
}

BASE_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}"

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = REPO_ROOT / "packages" / "cowork-app" / "src-tauri" / "resources" / "python"
CACHE_DIR = REPO_ROOT / ".cache" / "pbs"


def host_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return "aarch64-apple-darwin" if machine in ("arm64", "aarch64") else "x86_64-apple-darwin"
    if system == "linux":
        return "aarch64-unknown-linux-gnu" if machine in ("arm64", "aarch64") else "x86_64-unknown-linux-gnu"
    if system == "windows":
        return "x86_64-pc-windows-msvc"
    raise RuntimeError(f"unsupported host: {system}/{machine}")


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"[cache] {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {url}")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.rename(dest)


def extract(archive: Path, dest: Path) -> None:
    print(f"[extract] {archive.name} -> {dest}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest)
    # python-build-standalone archives extract into a top-level `python/` dir.
    top = dest / "python"
    if top.exists():
        # Move contents up one level so `bin/python` lives directly under `dest`.
        for item in top.iterdir():
            shutil.move(str(item), str(dest / item.name))
        top.rmdir()


def python_executable(bundle_root: Path, triple: str) -> Path:
    if "windows" in triple:
        return bundle_root / "python.exe"
    return bundle_root / "bin" / "python3"


def install_cowork(bundle_root: Path, triple: str, editable: bool = False) -> None:
    py = python_executable(bundle_root, triple)
    if not py.exists():
        # Some PBS layouts use `bin/python` (no 3 suffix).
        alt = bundle_root / "bin" / "python"
        if alt.exists():
            py = alt
    print(f"[pip] using {py}")

    # Ensure pip is available.
    subprocess.run([str(py), "-m", "ensurepip", "--upgrade"], check=True)
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        check=True,
    )

    # Install the workspace packages from source. Order matters: core first.
    # In editable mode (dev), source edits apply without re-bundling; do NOT
    # use for release builds since editable installs pin a host-local path.
    # The bundled sidecar uses cowork-server-app (single-user backend), which
    # depends on cowork-server (shared base). cowork-server-web is NOT
    # bundled — it's the hosted multi-user backend, deployed separately.
    cmd = [str(py), "-m", "pip", "install", "--no-cache-dir"]
    pkgs = [
        "cowork-core",
        "cowork-server",
        "cowork-server-app",
    ]
    if editable:
        for pkg in pkgs:
            cmd += ["-e", str(REPO_ROOT / "packages" / pkg)]
    else:
        for pkg in pkgs:
            cmd.append(str(REPO_ROOT / "packages" / pkg))
    subprocess.run(cmd, check=True)


def verify(bundle_root: Path, triple: str) -> None:
    py = python_executable(bundle_root, triple)
    if not py.exists():
        py = bundle_root / "bin" / "python"
    # `python -m cowork_server_app` starts uvicorn and blocks — use an import probe instead.
    probe = (
        "from cowork_server_app import create_app; "
        "from cowork_core import CoworkConfig; print('ok')"
    )
    print(f"[verify] {py} -c <import probe>")
    subprocess.run([str(py), "-c", probe], check=True)


def check_no_empty_files(bundle_root: Path) -> None:
    """Abort if files that MUST have content are 0 bytes.

    CPython and pep-compliant packages legitimately ship empty files —
    namespace ``__init__.py``, PEP 561 ``py.typed`` markers,
    ``.dist-info/REQUESTED``, etc. — so a blanket 0-byte sweep trips
    false positives constantly. We check only the files whose emptiness
    would silently break the bundle:

    * binaries in ``bin/`` (and ``python.exe`` on Windows)
    * shared libraries (``.so`` / ``.dylib`` / ``.dll`` / ``.pyd``)
    * editable-install ``.pth`` pointers (caused the real corruption
      that motivated this check)
    * dist-info ``METADATA`` and ``RECORD`` (ditto)
    """
    critical: list[Path] = []

    bin_dir = bundle_root / "bin"
    if bin_dir.is_dir():
        critical.extend(
            p for p in bin_dir.iterdir()
            if p.is_file() and not p.is_symlink() and p.stat().st_size == 0
        )
    # Windows python.exe lives at the bundle root, not under bin/.
    py_exe = bundle_root / "python.exe"
    if py_exe.is_file() and py_exe.stat().st_size == 0:
        critical.append(py_exe)

    for suffix in (".so", ".dylib", ".dll", ".pyd"):
        critical.extend(
            p for p in bundle_root.rglob(f"*{suffix}")
            if p.is_file() and p.stat().st_size == 0
        )

    for p in bundle_root.rglob("*.dist-info/METADATA"):
        if p.is_file() and p.stat().st_size == 0:
            critical.append(p)
    for p in bundle_root.rglob("*.dist-info/RECORD"):
        if p.is_file() and p.stat().st_size == 0:
            critical.append(p)
    for p in bundle_root.rglob("site-packages/_editable_impl_*.pth"):
        if p.is_file() and p.stat().st_size == 0:
            critical.append(p)

    if critical:
        preview = "\n  ".join(str(p.relative_to(bundle_root)) for p in critical[:10])
        more = f"\n  …and {len(critical) - 10} more" if len(critical) > 10 else ""
        raise SystemExit(
            f"[abort] bundle at {bundle_root} contains {len(critical)} "
            f"zero-byte critical file(s) — extraction or pip install was "
            f"likely interrupted. Re-run with --clean. Examples:\n"
            f"  {preview}{more}"
        )


def bundle(triple: str, editable: bool = False) -> Path:
    if triple not in TARGETS:
        raise SystemExit(f"unknown target triple: {triple}")
    archive_name = TARGETS[triple]
    archive = CACHE_DIR / archive_name
    download(f"{BASE_URL}/{archive_name}", archive)

    bundle_root = RESOURCES_DIR / triple
    extract(archive, bundle_root)
    install_cowork(bundle_root, triple, editable=editable)
    check_no_empty_files(bundle_root)

    # Only verify when the bundle matches the host — cross-compiled bundles
    # can't be executed on the current machine.
    if triple == host_triple():
        verify(bundle_root, triple)

    size_mb = sum(p.stat().st_size for p in bundle_root.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"[done] {triple}: {size_mb:.1f} MB at {bundle_root}")
    return bundle_root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="target triple; defaults to host", default=None)
    ap.add_argument("--clean", action="store_true", help="remove existing bundle first")
    ap.add_argument(
        "--editable",
        action="store_true",
        help="install cowork packages with pip -e so source edits apply without rebundling (dev only)",
    )
    args = ap.parse_args()

    triple = args.target or host_triple()
    if args.clean:
        out = RESOURCES_DIR / triple
        if out.exists():
            print(f"[clean] {out}")
            shutil.rmtree(out)

    bundle(triple, editable=args.editable)


if __name__ == "__main__":
    main()
