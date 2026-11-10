#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(target_os = "macos")]
mod mac_quit;

use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::oneshot;

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>>;

struct Backend {
    child: Mutex<Child>,
    input: Mutex<ChildStdin>,
    pending: Pending,
    sequence: AtomicU64,
    quitting: AtomicBool,
    alive: Arc<AtomicBool>,
}

impl Backend {
    fn start(app: &tauri::AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let root = if cfg!(debug_assertions) {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .to_path_buf()
        } else {
            app.path().resource_dir()?
        };
        let runtime = root.join(if cfg!(debug_assertions) {
            ".runtime"
        } else {
            "runtime"
        });
        let data = app.path().app_data_dir()?;
        std::fs::create_dir_all(data.join("logs"))?;
        let logfile = data.join("logs/worker.log");
        if logfile
            .metadata()
            .map(|m| m.len() > 2_000_000)
            .unwrap_or(false)
        {
            let _ = std::fs::rename(&logfile, data.join("logs/worker.previous.log"));
        }
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(logfile)?;
        let mut command = Command::new(runtime.join("python/bin/python3.11"));
        command
            .arg("-B")
            .arg(root.join("backend/worker.py"))
            .arg(data)
            .env("PYTHONUNBUFFERED", "1")
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log));
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        let mut child = command.spawn()?;
        let input = child.stdin.take().unwrap();
        let output = child.stdout.take().unwrap();
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let requests = pending.clone();
        let handle = app.clone();
        let alive = Arc::new(AtomicBool::new(true));
        let live = alive.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(output).lines().map_while(Result::ok) {
                if let Ok(message) = serde_json::from_str::<Value>(&line) {
                    if let Some(id) = message["id"].as_u64() {
                        if let Some(sender) = requests.lock().unwrap().remove(&id) {
                            let result = if let Some(error) = message["error"].as_str() {
                                Err(error.to_owned())
                            } else {
                                Ok(message["result"].clone())
                            };
                            let _ = sender.send(result);
                        }
                    } else {
                        let _ = handle.emit("backend-event", message);
                    }
                }
            }
            live.store(false, Ordering::SeqCst);
            for (_, sender) in requests.lock().unwrap().drain() {
                let _ = sender.send(Err("后台进程已退出，请重新启动应用。".to_owned()));
            }
            let _ = handle.emit("backend-event", json!({"event":"disconnected"}));
        });
        Ok(Self {
            child: Mutex::new(child),
            input: Mutex::new(input),
            pending,
            sequence: AtomicU64::new(1),
            quitting: AtomicBool::new(false),
            alive,
        })
    }

    async fn request(&self, method: String, params: Value) -> Result<Value, String> {
        if !self.alive.load(Ordering::SeqCst) {
            return Err("后台不可用，请重新启动应用。".into());
        }
        let id = self.sequence.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, sender);
        let message = json!({"id":id,"method":method,"params":params}).to_string() + "\n";
        let sent = self.input.lock().unwrap().write_all(message.as_bytes());
        if let Err(error) = sent {
            self.pending.lock().unwrap().remove(&id);
            return Err(error.to_string());
        }
        let result = match tokio::time::timeout(Duration::from_secs(160), receiver).await {
            Ok(Ok(value)) => value,
            _ => Err("请求超时，请重试。".into()),
        };
        self.pending.lock().unwrap().remove(&id);
        result
    }

    fn stop(&self) {
        let _ = self
            .input
            .lock()
            .unwrap()
            .write_all(b"{\"method\":\"shutdown\"}\n");
        let mut child = self.child.lock().unwrap();
        for _ in 0..60 {
            if child.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        // Also terminate descendants if a network request outlives graceful shutdown.
        #[cfg(unix)]
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGTERM);
        }
        std::thread::sleep(Duration::from_millis(200));
        #[cfg(unix)]
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
async fn backend_call(
    state: tauri::State<'_, Backend>,
    method: String,
    params: Value,
) -> Result<Value, String> {
    if ![
        "state", "settings", "search", "rank", "category", "latest", "filters", "detail",
        "enqueue", "cancel", "retry", "folder", "playback_open", "playback_close",
    ]
    .contains(&method.as_str())
    {
        return Err("不支持的操作".into());
    }
    state.request(method, params).await
}

#[tauri::command]
async fn choose_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("选择下载保存位置")
            .blocking_pick_folder()
            .map(|path| {
                path.into_path()
                    .map(|p| p.to_string_lossy().into_owned())
                    .map_err(|e| e.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn open_directory(path: String) -> Result<(), String> {
    let path = PathBuf::from(path);
    if !path.is_absolute() || !path.is_dir() {
        return Err("文件夹不存在".into());
    }
    #[cfg(target_os = "macos")]
    let mut command = Command::new("/usr/bin/open");
    #[cfg(target_os = "windows")]
    let mut command = Command::new("explorer");
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let mut command = Command::new("xdg-open");
    command.arg(path).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn quit_app(app: tauri::AppHandle) {
    if app.state::<Backend>().quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    let handle = app.clone();
    let _ = tauri::async_runtime::spawn_blocking(move || handle.state::<Backend>().stop()).await;
    app.exit(0);
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(Backend::start(app.handle())?);
            #[cfg(target_os = "macos")]
            mac_quit::install(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_call,
            choose_directory,
            open_directory,
            quit_app
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if !window.state::<Backend>().quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.emit("exit-request", ());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("无法启动红果桌面应用");
    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit)
            && !app.state::<Backend>().quitting.swap(true, Ordering::SeqCst)
        {
            app.state::<Backend>().stop();
        }
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            if !app.state::<Backend>().quitting.load(Ordering::SeqCst) {
                api.prevent_exit();
                let _ = app.emit("exit-request", ());
            }
        }
    });
}
