# Installer QA checklist

Manual smoke test run against a freshly-built installer on a clean VM per OS.
Expected duration: ~10 minutes per OS.

## Prerequisites
- A GitHub Release draft produced by `.github/workflows/release.yml` for the
  version under test.
- Clean VMs (or containers) for each target:
  - **macOS**: fresh macOS Sonoma/Sequoia on Apple Silicon (arm64)
  - **Linux**: Ubuntu 24.04 LTS, no dev tools preinstalled
  - **Windows**: Windows 11 23H2, no dev tools preinstalled
- A reachable OpenAI-compatible endpoint. The QA script below assumes a local
  LM Studio at `http://HOST.docker.internal:1234/v1` (adjust per VM network).

## Per-OS steps

### 1. Install
| OS | Artifact | Install command |
|---|---|---|
| macOS | `Cowork_<ver>_aarch64.dmg` | Double-click → drag to `/Applications` |
| Linux | `cowork_<ver>_amd64.deb` | `sudo apt install ./cowork_<ver>_amd64.deb` |
| Linux | `cowork_<ver>_amd64.AppImage` | `chmod +x cowork*.AppImage && ./cowork*.AppImage` |
| Windows | `Cowork_<ver>_x64_en-US.msi` | Double-click → finish wizard |

### 2. Launch
- Launch from the OS app launcher (not from a terminal).
- **AC**: window opens at 1280×800 within ~5 seconds.
- **AC**: no unhandled-error dialog.

### 3. Backend handshake
- Open the app's native menu → Help → About (macOS) / Help → About (others).
- **AC**: the URL `http://127.0.0.1:<port>` is reachable from a browser on the
  same machine and returns `{"status":"ok",...}` at `/v1/health`.

### 4. One-turn session
- In the chat pane, type a trivial prompt (e.g. "say hello").
- **AC**: assistant responds within a minute and `end_turn` fires (chat input
  re-enables).

### 5. File drag-drop
- Drag a small `.txt` file from the OS file manager onto the window.
- **AC**: status bar shows `Uploaded <name>`.
- **AC**: the file appears in the project files pane and in
  `~/CoworkWorkspaces/projects/<slug>/files/`.

### 6. Open workspace dir
- Menu → File → Open Workspace Dir.
- **AC**: OS file manager opens at `~/CoworkWorkspaces`.

### 7. Clean shutdown
- Quit via menu → Quit (macOS) / close window (Linux, Windows).
- Wait 3 seconds, then check the process list:
  - macOS / Linux: `ps -ax | grep cowork_server`
  - Windows: `tasklist /fi "imagename eq python.exe"`
- **AC**: no orphan `cowork_server` / `python` process.

### 8. Uninstall
- Remove the app via the OS's standard uninstall flow.
- **AC**: `~/CoworkWorkspaces` is left intact (user data never removed by the
  installer).

## Pass criteria
All 8 steps pass on all three OSes. Any single failure blocks the release.
