#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, State};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const PORT: u16 = 8000;
const WAIT_SECS: u64 = 60;

/// What the UI sees: starting | ready | error, plus a plain message.
#[derive(Clone)]
struct Status {
    state: &'static str,
    message: String,
}
type Shared = Arc<Mutex<Status>>;

#[tauri::command]
fn backend_status(s: State<'_, Shared>) -> serde_json::Value {
    let s = s.lock().unwrap();
    serde_json::json!({ "state": s.state, "message": s.message })
}

/// A dropped folder is used as is; a dropped file maps to its parent folder.
/// Only reads metadata, never opens or writes the path.
#[tauri::command]
fn drop_folder(path: String) -> Option<String> {
    let p = PathBuf::from(path);
    let dir = if p.is_dir() { p } else { p.parent()?.to_path_buf() };
    Some(dir.to_string_lossy().into_owned())
}

fn set(s: &Shared, state: &'static str, message: impl Into<String>) {
    *s.lock().unwrap() = Status { state, message: message.into() };
}

#[derive(PartialEq)]
enum Health {
    Down,        // nothing listens
    Unknown,     // connected, but no full answer yet (busy, slow, timeout)
    ShadowTree,  // full HTTP answer with "app":"ShadowTree"
    Foreign,     // full HTTP answer without the marker
}

/// Plain HTTP GET on 127.0.0.1:8000. Only a complete HTTP response without the
/// marker counts as Foreign; a timeout or an empty read is Unknown.
fn health() -> Health {
    let addr: SocketAddr = ([127, 0, 0, 1], PORT).into();
    let Ok(mut c) = TcpStream::connect_timeout(&addr, Duration::from_millis(800)) else { return Health::Down };
    let _ = c.set_read_timeout(Some(Duration::from_secs(10)));
    let _ = c.set_write_timeout(Some(Duration::from_secs(3)));
    let req = "GET /health HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nConnection: close\r\n\r\n";
    if c.write_all(req.as_bytes()).is_err() {
        return Health::Unknown;
    }
    let mut raw = Vec::new();
    // A timeout still leaves partial data in `raw`; it is then not a complete answer.
    let complete = c.read_to_end(&mut raw).is_ok();
    let body: String = String::from_utf8_lossy(&raw).chars().filter(|c| !c.is_whitespace()).collect();
    if complete && body.starts_with("HTTP/1.") && body.contains("\"app\":\"ShadowTree\"") {
        Health::ShadowTree
    } else if complete && body.starts_with("HTTP/1.") {
        Health::Foreign
    } else {
        Health::Unknown
    }
}

fn find_repo() -> Option<PathBuf> {
    let py = |p: &Path| p.join("backend").join(".venv").join("Scripts").join("python.exe").is_file();
    if let Ok(v) = std::env::var("SHADOWTREE_REPO") {
        let p = PathBuf::from(v);
        if py(&p) {
            return Some(p);
        }
    }
    let exe = std::env::current_exe().ok()?;
    exe.ancestors().skip(1).find(|p| py(p)).map(|p| p.to_path_buf())
}

/// Job object with KILL_ON_JOB_CLOSE: Windows kills every process in it when the
/// last handle closes, which happens when this app exits or is killed.
/// The handle is deliberately never closed.
fn job_for_self() -> bool {
    use windows_sys::Win32::System::JobObjects::*;
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return false;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        // This process joins the job BEFORE the backend is spawned, so the backend and
        // every grandchild inherit it with no gap.
        ok != 0 && AssignProcessToJobObject(job, windows_sys::Win32::System::Threading::GetCurrentProcess()) != 0
    }
}

fn tail(path: &Path, n: usize) -> String {
    let text = fs::read_to_string(path).unwrap_or_default();
    let lines: Vec<&str> = text.lines().collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

fn start_backend(s: Shared) {
    // 1. Already running? A slow answer is retried for ~20 s, never called foreign.
    let probe = Instant::now();
    loop {
        match health() {
            Health::ShadowTree => return set(&s, "ready", "Using the ShadowTree backend that is already running."),
            Health::Foreign => {
                return set(&s, "error", "Port 8000 is used by another program, not ShadowTree. Close it and start ShadowTree again.")
            }
            Health::Down => break,
            Health::Unknown => {
                if probe.elapsed() > Duration::from_secs(20) {
                    return set(&s, "error", "Something on port 8000 is not answering. Close it, or wait and start ShadowTree again.");
                }
                thread::sleep(Duration::from_millis(1000));
            }
        }
    }
    // 2. Spawn our own.
    let Some(repo) = find_repo() else {
        return set(&s, "error", "Could not find the ShadowTree folder (backend\\.venv\\Scripts\\python.exe). Set SHADOWTREE_REPO to the repo path.");
    };
    let backend = repo.join("backend");
    let data = backend.join("data");
    let _ = fs::create_dir_all(&data);
    let log = data.join("tauri-backend.log");
    let Ok(out) = File::create(&log) else {
        return set(&s, "error", format!("Cannot write {}", log.display()));
    };
    let Ok(err) = out.try_clone() else {
        return set(&s, "error", format!("Cannot write {}", log.display()));
    };
    if !job_for_self() {
        return set(&s, "error", "Could not set up the safety net that stops the backend when ShadowTree closes (Windows job object). Nothing was started.");
    }
    let child = Command::new(backend.join(".venv").join("Scripts").join("python.exe"))
        .args(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-access-log"])
        .env("PYTHONUNBUFFERED", "1")
        .current_dir(&backend)
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::from(out))
        .stderr(Stdio::from(err))
        .spawn();
    let mut child = match child {
        Ok(c) => c,
        Err(e) => return set(&s, "error", format!("Could not start the backend: {e}")),
    };
    // 3. Wait for /health.
    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(WAIT_SECS) {
        if let Ok(Some(status)) = child.try_wait() {
            return set(&s, "error", format!("The backend stopped ({status}).\n{}", tail(&log, 15)));
        }
        if health() == Health::ShadowTree {
            return set(&s, "ready", "Backend started.");
        }
        thread::sleep(Duration::from_millis(500));
    }
    set(&s, "error", format!("The backend did not answer within {WAIT_SECS} seconds.\n{}", tail(&log, 15)));
}

fn main() {
    let shared: Shared = Arc::new(Mutex::new(Status { state: "starting", message: "Starting ShadowTree...".into() }));
    let worker = shared.clone();

    tauri::Builder::default()
        // Must be first: a second start exits here and focuses the first window.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .setup(move |_app| {
            thread::spawn(move || start_backend(worker));
            Ok(())
        })
        .plugin(tauri_plugin_dialog::init())
        .manage(shared)
        .invoke_handler(tauri::generate_handler![backend_status, drop_folder])
        .run(tauri::generate_context!())
        .expect("error while running ShadowTree");
}
