#![windows_subsystem = "windows"]

use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::{process::CommandEvent, process::CommandChild, ShellExt};

struct Backend(Mutex<Option<CommandChild>>);

fn startup_error(handle: &tauri::AppHandle, message: &str) {
    handle.dialog().message(message).title("Second Brain - error de inicio").blocking_show();
    handle.exit(1);
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let (mut events, child) = app.shell()
                .sidecar("second-brain-backend")?
                .args(["--no-browser", "--parent-pid", &std::process::id().to_string()])
                .spawn()?;
            *app.state::<Backend>().0.lock().unwrap() = Some(child);
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) {
                                if let Some(url) = value["url"].as_str() {
                                    let parsed: reqwest::Url = match url.parse() {
                                        Ok(url) => url,
                                        Err(_) => { startup_error(&handle, "Invalid backend address."); return; }
                                    };
                                    if parsed.host_str() != Some("127.0.0.1") {
                                        startup_error(&handle, "Backend address is not local.");
                                        return;
                                    }
                                    let health = parsed.join("/health").unwrap();
                                    let client = reqwest::Client::builder()
                                        .timeout(std::time::Duration::from_secs(2)).build().unwrap();
                                    let mut ready = false;
                                    for _ in 0..60 {
                                        if let Ok(response) = client.get(health.clone()).send().await {
                                            if response.status().is_success() { ready = true; break; }
                                        }
                                        std::thread::sleep(std::time::Duration::from_millis(500));
                                    }
                                    if !ready {
                                        startup_error(&handle, "Backend did not become ready. Check local logs.");
                                        return;
                                    }
                                    if let Err(error) = tauri::WebviewWindowBuilder::new(
                                        &handle, "main", tauri::WebviewUrl::External(parsed)
                                    ).title("Segundo Cerebro").inner_size(1200.0, 820.0)
                                     .min_inner_size(760.0, 560.0).build() {
                                        eprintln!("Window creation failed: {error}");
                                        startup_error(&handle, "Could not create the desktop window.");
                                    }
                                }
                            }
                        }
                        CommandEvent::Stderr(bytes) => eprintln!("{}", String::from_utf8_lossy(&bytes)),
                        CommandEvent::Terminated(_) => {
                            startup_error(&handle, "Backend stopped. Check whether Second Brain is already running or its runtime files are missing.");
                            return;
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Could not initialize desktop application");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Some(child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
