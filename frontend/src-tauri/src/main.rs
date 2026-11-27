#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, State};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const WAIT_SECS: u64 = 60;
/// Restarts allowed in a row. A backend that ran for STABLE_SECS earns a fresh budget.
const MAX_RESTARTS: u32 = 3;
const STABLE_SECS: u64 = 300;

/// What the UI sees: starting | ready | error, a plain message, and where to reach the backend.
/// `port` and `token` are fixed for the life of the window, so a restarted backend keeps them
/// and the page never has to ask again.
struct Shell {
    status: Mutex<(&'static str, String)>,
    port: u16,
    token: String,
}
type Shared = Arc<Shell>;

#[tauri::command]
fn backend_status(s: State<'_, Shared>) -> serde_json::Value {
    let st = s.status.lock().unwrap();
    serde_json::json!({
        "state": st.0,
        "message": st.1,
        "base": format!("http://127.0.0.1:{}", s.port),
        "token": s.token,
    })
}

/// A dropped folder is used as is; a dropped file maps to its parent folder.
/// Only reads metadata, never opens or writes the path.
#[tauri::command]
fn drop_folder(path: String) -> Option<String> {
    let p = PathBuf::from(path);
    let dir = if p.is_dir() { p } else { p.parent()?.to_path_buf() };
    Some(dir.to_string_lossy().into_owned())
}

fn set(s: &Shell, state: &'static str, message: impl Into<String>) {
    *s.status.lock().unwrap() = (state, message.into());
}

/// 32 random bytes from the Windows system RNG, as 64 hex characters. None if the RNG fails.
fn random_token() -> Option<String> {
    use windows_sys::Win32::Security::Cryptography::{BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG};
    let mut buf = [0u8; 32];
    let status = unsafe {
        BCryptGenRandom(std::ptr::null_mut(), buf.as_mut_ptr(), buf.len() as u32, BCRYPT_USE_SYSTEM_PREFERRED_RNG)
    };
    if status != 0 {
        return None;
    }
    Some(buf.iter().map(|b| format!("{b:02x}")).collect())
}

/// A port nobody listens on right now. Windows hands out a free ephemeral port for port 0.
/// (A tiny race remains until uvicorn binds it; /health then checks it is really ShadowTree.)
fn free_port() -> Option<u16> {
    TcpListener::bind(("127.0.0.1", 0)).ok()?.local_addr().ok().map(|a| a.port())
}

/// Plain HTTP GET /health. True only for a complete HTTP answer with the ShadowTree marker.
fn healthy(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let Ok(mut c) = TcpStream::connect_timeout(&addr, Duration::from_millis(800)) else { return false };
    let _ = c.set_read_timeout(Some(Duration::from_secs(10)));
    let _ = c.set_write_timeout(Some(Duration::from_secs(3)));
    let req = format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if c.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut raw = Vec::new();
    // A timeout still leaves partial data in `raw`; it is then not a complete answer.
    let complete = c.read_to_end(&mut raw).is_ok();
    let body: String = String::from_utf8_lossy(&raw).chars().filter(|c| !c.is_whitespace()).collect();
    complete && body.starts_with("HTTP/1.") && body.contains("\"app\":\"ShadowTree\"")
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

/// Start uvicorn on `port` with the token in its environment. The first start empties the log,
/// a restart appends to it, so the lines before a crash are kept.
fn spawn(backend: &Path, log: &Path, port: u16, token: &str, fresh_log: bool) -> Result<Child, String> {
    let out = if fresh_log { File::create(log) } else { OpenOptions::new().create(true).append(true).open(log) };
    let out = out.map_err(|_| format!("Cannot write {}", log.display()))?;
    let err = out.try_clone().map_err(|_| format!("Cannot write {}", log.display()))?;
    Command::new(backend.join(".venv").join("Scripts").join("python.exe"))
        .args(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", &port.to_string(),
               "--workers", "1", "--no-access-log"])
        .env("PYTHONUNBUFFERED", "1")
        .env("SHADOWTREE_API_TOKEN", token)
        .current_dir(backend)
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::from(out))
        .stderr(Stdio::from(err))
        .spawn()
        .map_err(|e| format!("Could not start the backend: {e}"))
}

/// Wait for /health. Err with a message (and the log tail) when it stops or never answers.
fn wait_ready(child: &mut Child, port: u16, log: &Path) -> Result<(), String> {
    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(WAIT_SECS) {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("The backend stopped ({status}).\n{}", tail(log, 15)));
        }
        if healthy(port) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(500));
    }
    let _ = child.kill();   // do not leave a half-started backend behind the error message
    Err(format!("The backend did not answer within {WAIT_SECS} seconds.\n{}", tail(log, 15)))
}

/// Start the backend, then watch it. If it stops (a crash in a native library, say) it is
/// started again on the same port with the same token, up to MAX_RESTARTS times in a row.
fn run_backend(s: Shared) {
    if s.token.is_empty() || s.port == 0 {
        return; // main() already set the error
    }
    let Some(repo) = find_repo() else {
        return set(&s, "error", "Could not find the ShadowTree folder (backend\\.venv\\Scripts\\python.exe). Set SHADOWTREE_REPO to the repo path.");
    };
    let backend = repo.join("backend");
    let _ = fs::create_dir_all(backend.join("data"));
    let log = backend.join("data").join("tauri-backend.log");
    if !job_for_self() {
        return set(&s, "error", "Could not set up the safety net that stops the backend when ShadowTree closes (Windows job object). Nothing was started.");
    }
    let mut restarts = 0u32;
    loop {
        let mut child = match spawn(&backend, &log, s.port, &s.token, restarts == 0) {
            Ok(c) => c,
            Err(msg) => return set(&s, "error", msg),
        };
        if let Err(msg) = wait_ready(&mut child, s.port, &log) {
            return set(&s, "error", msg);
        }
        set(&s, "ready", if restarts == 0 { "Backend started." } else { "Backend restarted." });
        let up = Instant::now();
        let status = loop {
            match child.try_wait() {
                Ok(Some(st)) => break st.to_string(),
                Ok(None) => thread::sleep(Duration::from_secs(1)),
                Err(e) => break e.to_string(),
            }
        };
        if up.elapsed() >= Duration::from_secs(STABLE_SECS) {
            restarts = 0;
        }
        restarts += 1;
        if restarts > MAX_RESTARTS {
            return set(&s, "error", format!(
                "The local helper stopped ({status}) and kept stopping after {MAX_RESTARTS} restarts. Close ShadowTree and start it again.\n{}",
                tail(&log, 15)));
        }
        if let Ok(mut f) = OpenOptions::new().append(true).open(&log) {
            let _ = writeln!(f, "\n[shell] backend stopped ({status}); restart {restarts} of {MAX_RESTARTS}\n");
        }
        set(&s, "starting", format!("The local helper stopped ({status}). Restarting it..."));
    }
}

fn main() {
    let token = random_token().unwrap_or_default();
    let port = free_port().unwrap_or(0);
    let shell: Shared = Arc::new(Shell {
        status: Mutex::new(("starting", "Starting ShadowTree...".into())),
        port,
        token,
    });
    if shell.token.is_empty() {
        set(&shell, "error", "Could not make the access key for the local helper (Windows random number generator). Nothing was started.");
    } else if shell.port == 0 {
        set(&shell, "error", "Could not find a free local port for the helper. Nothing was started.");
    }
    let worker = shell.clone();

    tauri::Builder::default()
        // Must be first: a second start exits here and focuses the first window.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .setup(move |_app| {
            thread::spawn(move || run_backend(worker));
            Ok(())
        })
        .plugin(tauri_plugin_dialog::init())
        .manage(shell)
        .invoke_handler(tauri::generate_handler![backend_status, drop_folder])
        .run(tauri::generate_context!())
        .expect("error while running ShadowTree");
}
