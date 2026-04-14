mod sidecar;

use std::path::PathBuf;
use std::process::Command;

use sidecar::{ServerInfo, SidecarState};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Emitter, Manager, RunEvent};

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    sidecar::install_signal_handlers();
    tauri::Builder::default()
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            get_server,
            open_workspace,
            read_dropped_file
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Native menu. Items emit events the frontend can subscribe to
            // instead of hard-coding behavior here.
            let handle = app.handle();
            let new_project = MenuItem::with_id(handle, "new_project", "New Project", true, Some("CmdOrCtrl+N"))?;
            let open_ws = MenuItem::with_id(handle, "open_workspace", "Open Workspace Dir", true, Some("CmdOrCtrl+Shift+O"))?;
            let quit = PredefinedMenuItem::quit(handle, None)?;
            let file_menu = Submenu::with_items(
                handle,
                "File",
                true,
                &[&new_project, &open_ws, &PredefinedMenuItem::separator(handle)?, &quit],
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
