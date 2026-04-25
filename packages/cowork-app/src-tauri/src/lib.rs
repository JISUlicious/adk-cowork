mod sidecar;

use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;

use sidecar::{ServerInfo, SidecarState};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Emitter, Manager, RunEvent};
use tauri_plugin_dialog::DialogExt;

#[tauri::command]
fn get_server(state: tauri::State<'_, SidecarState>) -> Result<ServerInfo, String> {
    state
        .info
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "server not ready".to_string())
}

fn workspace_root() -> PathBuf {
    if let Ok(p) = std::env::var("COWORK_WORKSPACE_ROOT") {
        let expanded = shellexpand::tilde(&p).into_owned();
        return PathBuf::from(expanded);
    }
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join("CoworkWorkspaces")
}

fn open_path(path: &std::path::Path) -> Result<(), String> {
    let cmd = if cfg!(target_os = "macos") {
        "open"
    } else if cfg!(target_os = "windows") {
        "explorer"
    } else {
        "xdg-open"
    };
    Command::new(cmd)
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("failed to open {}: {e}", path.display()))
}

#[tauri::command]
fn open_workspace() -> Result<(), String> {
    let root = workspace_root();
    std::fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    open_path(&root)
}

/// Blocking folder picker. Returns the absolute path the user selected, or
/// ``None`` if they cancelled. Caller (React) treats ``None`` as a no-op.
///
/// We use ``blocking_pick_folder`` because the frontend awaits on the invoke
/// and cancellation should surface as a simple ``null`` return rather than
/// an error.
#[tauri::command]
async fn pick_workdir(app: AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog().file().pick_folder(move |picked| {
        let _ = tx.send(picked);
    });
    // The dialog callback fires off the main thread; block the async task
    // briefly until it resolves so we can return a plain value to JS.
    let picked = tauri::async_runtime::spawn_blocking(move || {
        rx.recv().map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())??;
    Ok(picked.map(|p| p.to_string()))
}

/// Native multi-file picker for composer attachments. Returns the list
/// of absolute paths the user selected, or an empty list if cancelled.
#[tauri::command]
async fn pick_files(app: AppHandle) -> Result<Vec<String>, String> {
    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog().file().pick_files(move |picked| {
        let _ = tx.send(picked);
    });
    let picked = tauri::async_runtime::spawn_blocking(move || {
        rx.recv().map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())??;
    Ok(picked
        .map(|v| v.into_iter().map(|p| p.to_string()).collect())
        .unwrap_or_default())
}

/// Remember the most-recent workdir so the UI can re-open it on next launch.
///
/// Slice M4-A: persists to a single-line JSON file under the platform's
/// app config dir. Reads on init; writes synchronously on every `set`.
/// File I/O failures are logged but never panic — the in-memory copy
/// stays authoritative, so a corrupt or unwritable file just degrades
/// to the previous v1 in-memory-only behaviour.
struct RecentWorkdir {
    state: Mutex<Option<String>>,
    storage: Option<PathBuf>,
}

impl Default for RecentWorkdir {
    fn default() -> Self {
        Self {
            state: Mutex::new(None),
            storage: None,
        }
    }
}

impl RecentWorkdir {
    /// Construct with an on-disk backing file. Reads the file once at
    /// construction time; missing / unreadable / malformed → no recent
    /// workdir. Writes happen on every `set`.
    fn with_storage(storage: PathBuf) -> Self {
        let initial = Self::read(&storage);
        Self {
            state: Mutex::new(initial),
            storage: Some(storage),
        }
    }

    fn get(&self) -> Option<String> {
        self.state.lock().unwrap().clone()
    }

    fn set(&self, path: String) {
        *self.state.lock().unwrap() = Some(path.clone());
        if let Some(storage) = &self.storage {
            if let Err(e) = Self::write(storage, &path) {
                log::warn!(
                    "RecentWorkdir: failed to persist to {}: {e}",
                    storage.display(),
                );
            }
        }
    }

    fn read(storage: &std::path::Path) -> Option<String> {
        let raw = std::fs::read_to_string(storage).ok()?;
        let value: serde_json::Value = serde_json::from_str(&raw).ok()?;
        match value.get("path")?.as_str() {
            Some(s) if !s.is_empty() => Some(s.to_string()),
            _ => None,
        }
    }

    fn write(storage: &std::path::Path, value: &str) -> std::io::Result<()> {
        if let Some(parent) = storage.parent() {
            std::fs::create_dir_all(parent)?;
        }
        // Atomic write: temp file + rename so a crash mid-write can't
        // produce an empty / half-written JSON that next boot would
        // see and treat as "no recent workdir".
        let tmp = storage.with_extension("json.tmp");
        let body = serde_json::to_string(&serde_json::json!({ "path": value }))
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        std::fs::write(&tmp, body)?;
        std::fs::rename(tmp, storage)
    }
}

#[tauri::command]
fn recent_workdir(state: tauri::State<'_, RecentWorkdir>) -> Option<String> {
    state.get()
}

#[tauri::command]
fn set_recent_workdir(path: String, state: tauri::State<'_, RecentWorkdir>) {
    state.set(path);
}

#[tauri::command]
fn read_dropped_file(path: String) -> Result<Vec<u8>, String> {
    // Cap at 64 MB to avoid accidental memory blowups on huge drops.
    const MAX: u64 = 64 * 1024 * 1024;
    let meta = std::fs::metadata(&path).map_err(|e| e.to_string())?;
    if meta.len() > MAX {
        return Err(format!("file too large: {} bytes (max {MAX})", meta.len()));
    }
    std::fs::read(&path).map_err(|e| e.to_string())
}

/// Copy ``src`` into ``workdir`` using the source filename.
///
/// Used by the desktop file-drop handler in local-dir (workdir) mode:
/// the agent already operates directly on ``workdir``, so the sensible
/// drop behavior is "make the file appear in the agent's view" — i.e.
/// copy it into the folder. Staying in Rust avoids round-tripping the
/// file bytes through the webview + HTTP.
///
/// Overwrites an existing file of the same name in ``workdir`` (common
/// case: re-drop a file that's been edited). Returns the copied
/// destination path as a string for UI feedback.
#[tauri::command]
fn copy_into_workdir(src: String, workdir: String) -> Result<String, String> {
    use std::path::PathBuf;

    let src_path = PathBuf::from(&src);
    let workdir_path = PathBuf::from(&workdir);

    if !workdir_path.is_dir() {
        return Err(format!("workdir is not a directory: {workdir}"));
    }
    let workdir_abs = std::fs::canonicalize(&workdir_path)
        .map_err(|e| format!("canonicalize workdir: {e}"))?;

    let name = src_path
        .file_name()
        .ok_or_else(|| format!("source has no filename: {src}"))?;
    let dest: PathBuf = workdir_abs.join(name);

    // Defensive: ``Path::join`` with a simple filename can't escape, but
    // guard anyway in case the source name ever contains a path separator.
    if !dest.starts_with(&workdir_abs) {
        return Err(format!("destination escapes workdir: {}", dest.display()));
    }

    std::fs::copy(&src_path, &dest).map_err(|e| format!("copy failed: {e}"))?;
    Ok(dest.display().to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Dev-only: auto-load the repo-root `.env` so developers can set
    // per-checkout vars (COWORK_PYTHON, COWORK_MODEL_*, etc.) without
    // polluting their shell. Packaged release builds skip this — we
    // don't want installed apps to read arbitrary .env files from
    // wherever the user happens to launch them.
    #[cfg(debug_assertions)]
    {
        // Walk up from CARGO_MANIFEST_DIR to find `<repo>/.env`.
        let manifest = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // manifest = .../packages/cowork-app/src-tauri → repo = .../
        if let Some(repo_root) = manifest.ancestors().nth(3) {
            let env_file = repo_root.join(".env");
            if env_file.exists() {
                match dotenvy::from_path(&env_file) {
                    Ok(_) => log::info!("loaded dev env from {}", env_file.display()),
                    Err(e) => log::warn!(
                        "failed to load {}: {e}",
                        env_file.display(),
                    ),
                }
            }
        }
    }

    sidecar::install_signal_handlers();
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            get_server,
            open_workspace,
            read_dropped_file,
            copy_into_workdir,
            pick_workdir,
            pick_files,
            recent_workdir,
            set_recent_workdir
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Slice M4-A — persistent RecentWorkdir. Resolve the
            // platform's app config dir now (we have an AppHandle here)
            // and hand the storage path to the state object. If the
            // path resolution itself fails (rare — would need a broken
            // tauri config), fall back to in-memory only.
            let recent = match app.path().app_config_dir() {
                Ok(dir) => RecentWorkdir::with_storage(dir.join("recent_workdir.json")),
                Err(e) => {
                    log::warn!("RecentWorkdir: app_config_dir unavailable: {e}; in-memory only");
                    RecentWorkdir::default()
                }
            };
            app.manage(recent);

            // Native menu. Items emit events the frontend can subscribe to
            // instead of hard-coding behavior here.
            let handle = app.handle();
            let new_project = MenuItem::with_id(handle, "new_project", "New Project", true, Some("CmdOrCtrl+N"))?;
            let open_folder = MenuItem::with_id(handle, "open_folder", "Open Folder…", true, Some("CmdOrCtrl+O"))?;
            let open_ws = MenuItem::with_id(handle, "open_workspace", "Open Workspace Dir", true, Some("CmdOrCtrl+Shift+O"))?;
            let quit = PredefinedMenuItem::quit(handle, None)?;
            let file_menu = Submenu::with_items(
                handle,
                "File",
                true,
                &[&new_project, &open_folder, &open_ws, &PredefinedMenuItem::separator(handle)?, &quit],
            )?;

            let copy = PredefinedMenuItem::copy(handle, None)?;
            let paste = PredefinedMenuItem::paste(handle, None)?;
            let cut = PredefinedMenuItem::cut(handle, None)?;
            let select_all = PredefinedMenuItem::select_all(handle, None)?;
            let edit_menu = Submenu::with_items(handle, "Edit", true, &[&cut, &copy, &paste, &select_all])?;

            let about = PredefinedMenuItem::about(handle, Some("About Cowork"), None)?;
            let help_menu = Submenu::with_items(handle, "Help", true, &[&about])?;

            let menu = Menu::with_items(handle, &[&file_menu, &edit_menu, &help_menu])?;
            app.set_menu(menu)?;
            app.on_menu_event(|app, event| {
                // Forward to the frontend as a Tauri event so React can react.
                let _ = app.emit("menu", event.id().0.clone());
            });

            // Launch the Python server.
            match sidecar::spawn(app.handle()) {
                Ok(info) => log::info!("cowork-server ready at {}", info.url),
                Err(e) => log::error!("cowork-server failed to start: {e}"),
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                let state = app.state::<SidecarState>();
                sidecar::shutdown(&state);
            }
            _ => {}
        });
}

// ─────────────────────────── tests ────────────────────────────────────
//
// Folder-picker smoke tests. We can't exercise the full `pick_workdir`
// command here (it needs a running Tauri shell + a real native dialog)
// but we can cover the state machine that the UI relies on for remembering
// the last-picked workdir across invokes. Anything else is an integration
// test on the Python/server side.

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_storage_path(name: &str) -> PathBuf {
        let mut p = std::env::temp_dir();
        // Per-test subdirectory keeps parallel runs from stomping on
        // each other's storage file.
        let unique = format!(
            "cowork-app-test-{}-{}-{}",
            name,
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
        );
        p.push(unique);
        p.push("recent_workdir.json");
        p
    }

    #[test]
    fn recent_workdir_starts_empty() {
        let r = RecentWorkdir::default();
        assert_eq!(r.get(), None);
    }

    #[test]
    fn recent_workdir_set_then_get_roundtrips() {
        let r = RecentWorkdir::default();
        r.set("/Users/alice/docs".to_string());
        assert_eq!(r.get(), Some("/Users/alice/docs".to_string()));
    }

    #[test]
    fn recent_workdir_set_overwrites_previous() {
        let r = RecentWorkdir::default();
        r.set("/a".to_string());
        r.set("/b".to_string());
        assert_eq!(r.get(), Some("/b".to_string()));
    }

    #[test]
    fn recent_workdir_concurrent_access_is_safe() {
        use std::sync::Arc;
        use std::thread;

        let r = Arc::new(RecentWorkdir::default());
        let mut handles = vec![];
        for i in 0..8 {
            let r = Arc::clone(&r);
            handles.push(thread::spawn(move || {
                r.set(format!("/path/{i}"));
                r.get();
            }));
        }
        for h in handles {
            h.join().unwrap();
        }
        // Whatever landed last should be readable.
        let v = r.get();
        assert!(v.is_some());
        let s = v.unwrap();
        assert!(s.starts_with("/path/"));
    }

    // ─────────────── Slice M4-A — persistence ───────────────

    #[test]
    fn persistent_set_writes_file_and_survives_reload() {
        let storage = temp_storage_path("survives_reload");
        // Fresh instance starts empty even though parent dir doesn't exist.
        let r1 = RecentWorkdir::with_storage(storage.clone());
        assert_eq!(r1.get(), None);

        r1.set("/Users/alice/projects/foo".to_string());

        // A *new* instance reads the same path and finds the same value.
        let r2 = RecentWorkdir::with_storage(storage.clone());
        assert_eq!(r2.get(), Some("/Users/alice/projects/foo".to_string()));

        // Cleanup — best-effort.
        let _ = std::fs::remove_file(&storage);
        if let Some(parent) = storage.parent() {
            let _ = std::fs::remove_dir(parent);
        }
    }

    #[test]
    fn persistent_set_uses_atomic_temp_then_rename() {
        let storage = temp_storage_path("atomic_temp");
        let r = RecentWorkdir::with_storage(storage.clone());
        r.set("/x".to_string());
        // The temp file should not exist after a successful write.
        let tmp = storage.with_extension("json.tmp");
        assert!(!tmp.exists(), "temp file should be renamed away");
        assert!(storage.exists(), "final file should exist");

        let _ = std::fs::remove_file(&storage);
        if let Some(parent) = storage.parent() {
            let _ = std::fs::remove_dir(parent);
        }
    }

    #[test]
    fn persistent_malformed_file_treated_as_empty() {
        let storage = temp_storage_path("malformed");
        std::fs::create_dir_all(storage.parent().unwrap()).unwrap();
        std::fs::write(&storage, "not valid json {{{").unwrap();

        let r = RecentWorkdir::with_storage(storage.clone());
        assert_eq!(r.get(), None);

        let _ = std::fs::remove_file(&storage);
        if let Some(parent) = storage.parent() {
            let _ = std::fs::remove_dir(parent);
        }
    }

    #[test]
    fn persistent_empty_path_in_file_treated_as_empty() {
        // A file with `{"path": ""}` shouldn't make us claim a workdir.
        let storage = temp_storage_path("empty_path");
        std::fs::create_dir_all(storage.parent().unwrap()).unwrap();
        std::fs::write(&storage, r#"{"path": ""}"#).unwrap();

        let r = RecentWorkdir::with_storage(storage.clone());
        assert_eq!(r.get(), None);

        let _ = std::fs::remove_file(&storage);
        if let Some(parent) = storage.parent() {
            let _ = std::fs::remove_dir(parent);
        }
    }
}
