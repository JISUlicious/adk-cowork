//! Spawns the bundled cowork-server and parses its stdout handshake.
//!
//! The bundled Python interpreter + cowork-server wheels live under
//! `resources/python/<target-triple>/`. In dev mode we fall back to the
//! same layout relative to the Cargo manifest so `cargo tauri dev` works
//! without packaging.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::sync::atomic::{AtomicI32, Ordering};
use std::thread;
use std::time::Duration;

use tauri::{AppHandle, Manager};

/// PID of the spawned sidecar. Stored in a static so POSIX signal handlers
/// (which cannot capture) can find the child and terminate its group.
static CHILD_PID: AtomicI32 = AtomicI32::new(0);

#[cfg(unix)]
extern "C" fn signal_cleanup(_sig: libc::c_int) {
    let pid = CHILD_PID.load(Ordering::SeqCst);
    if pid > 0 {
        unsafe {
            libc::kill(-pid, libc::SIGTERM);
        }
    }
    // Re-raise default handler so the process actually exits.
    unsafe {
        libc::signal(_sig, libc::SIG_DFL);
        libc::raise(_sig);
    }
}

#[cfg(unix)]
pub fn install_signal_handlers() {
    unsafe {
        libc::signal(libc::SIGTERM, signal_cleanup as *const () as libc::sighandler_t);
        libc::signal(libc::SIGINT, signal_cleanup as *const () as libc::sighandler_t);
        libc::signal(libc::SIGHUP, signal_cleanup as *const () as libc::sighandler_t);
    }
}

#[cfg(not(unix))]
pub fn install_signal_handlers() {}

/// Published via Tauri `invoke("get_server")` once the handshake lands.
#[derive(Clone, Debug, serde::Serialize)]
pub struct ServerInfo {
    pub url: String,
    pub token: String,
}

/// Singleton holding the spawned child + the parsed handshake.
#[derive(Default)]
pub struct SidecarState {
    pub child: Mutex<Option<Child>>,
    pub info: Mutex<Option<ServerInfo>>,
}

fn target_triple() -> &'static str {
    // Keep these strings in sync with scripts/bundle_python.py TARGETS.
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "aarch64-apple-darwin"
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        "x86_64-apple-darwin"
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        "aarch64-unknown-linux-gnu"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "x86_64-unknown-linux-gnu"
    } else if cfg!(target_os = "windows") {
        "x86_64-pc-windows-msvc"
    } else {
        "unknown"
    }
}

/// Returns true when ``p`` exists and is non-empty. An empty file indicates a
/// corrupted or interrupted bundle (PBS extractions can leave 0-byte stubs
/// behind) and should fall through to the next candidate rather than get
/// spawned into a silently-failing process.
fn is_usable_binary(p: &std::path::Path) -> bool {
    std::fs::metadata(p)
        .map(|m| m.len() > 0)
        .unwrap_or(false)
}

fn python_binary(app: &AppHandle) -> Result<PathBuf, String> {
    let triple = target_triple();

    // Dev override: set ``COWORK_PYTHON=/path/to/python`` to use any
    // interpreter (system, uv, venv) and skip bundling entirely. Useful for
    // tight iteration loops where re-running scripts/bundle_python.py each
    // time would be a drag.
    if let Ok(override_path) = std::env::var("COWORK_PYTHON") {
        let bin = PathBuf::from(override_path);
        if is_usable_binary(&bin) {
            return Ok(bin);
        }
        log::warn!(
            "COWORK_PYTHON set to {} but file is missing or empty — falling through",
            bin.display(),
        );
    }

    // Packaged build: Tauri copies `resources/python/` next to the binary.
    if let Ok(resource_root) = app.path().resource_dir() {
        let packaged = resource_root.join("resources").join("python").join(triple);
        let bin = if cfg!(target_os = "windows") {
            packaged.join("python.exe")
        } else {
            packaged.join("bin").join("python3")
        };
        if is_usable_binary(&bin) {
            return Ok(bin);
        }
    }

    // Dev build: fall back to the in-tree bundle produced by the packager.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev = manifest
        .join("resources")
        .join("python")
        .join(triple);
    let bin = if cfg!(target_os = "windows") {
        dev.join("python.exe")
    } else {
        dev.join("bin").join("python3")
    };
    if is_usable_binary(&bin) {
        return Ok(bin);
    }
    Err(format!(
        "bundled Python not found (or is empty) for {triple}. \
         Either set COWORK_PYTHON=/path/to/python to point at a system \
         interpreter, or run `uv run python scripts/bundle_python.py \
         --target {triple} --editable` to refresh the bundle."
    ))
}

/// Launch the server as a child process and block the caller until the
/// handshake line arrives on stdout (or the child dies).
pub fn spawn(app: &AppHandle) -> Result<ServerInfo, String> {
    let python = python_binary(app)?;
    let mut cmd = Command::new(&python);
    cmd.arg("-m")
        .arg("cowork_server_app")
        .env("COWORK_PORT", "0")
        .env("COWORK_WATCH_PARENT", "1")
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    // Put the child in its own process group so we can signal the whole
    // tree on shutdown (and so Ctrl-C at a terminal doesn't hit it twice).
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt as _;
        unsafe {
            cmd.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn cowork-server: {e}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "child stdout was not captured".to_string())?;
    let reader = BufReader::new(stdout);

    let mut info: Option<ServerInfo> = None;
    for line in reader.lines() {
        let Ok(line) = line else { break };
        eprintln!("[cowork-server] {line}");
        if let Some(rest) = line.strip_prefix("COWORK_READY ") {
            let mut host = None;
            let mut port = None;
            let mut token = None;
            for kv in rest.split_whitespace() {
                if let Some((k, v)) = kv.split_once('=') {
                    match k {
                        "host" => host = Some(v.to_string()),
                        "port" => port = Some(v.to_string()),
                        "token" => token = Some(v.to_string()),
                        _ => {}
                    }
                }
            }
            if let (Some(h), Some(p), Some(t)) = (host, port, token) {
                info = Some(ServerInfo {
                    url: format!("http://{h}:{p}"),
                    token: t,
                });
                break;
            }
        }
    }

    let info = info.ok_or_else(|| "server exited before handshake".to_string())?;

    // Publish PID to the signal-handler-visible slot, then persist state on
    // the app so graceful shutdown paths can reach the child either way.
    CHILD_PID.store(child.id() as i32, Ordering::SeqCst);
    let state: tauri::State<SidecarState> = app.state();
    *state.child.lock().unwrap() = Some(child);
    *state.info.lock().unwrap() = Some(info.clone());

    Ok(info)
}

/// Terminate the child process on shutdown. Best-effort.
pub fn shutdown(state: &SidecarState) {
    CHILD_PID.store(0, Ordering::SeqCst);
    let mut guard = state.child.lock().unwrap();
    if let Some(mut child) = guard.take() {
        // Try a polite SIGTERM to the whole process group first, then kill.
        #[cfg(unix)]
        unsafe {
            let pid = child.id() as libc::pid_t;
            libc::kill(-pid, libc::SIGTERM);
            thread::sleep(Duration::from_millis(300));
            libc::kill(-pid, libc::SIGKILL);
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}
