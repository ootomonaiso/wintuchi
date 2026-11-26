//! envmon-overlay — 汎用エンジン [`tbwidget`] の薄い EnvMonitor 向けバイナリ。
//!
//! ここがやるのは「ブランド（パス・トレイ・配色）の既定を与える」ことと、
//! 「state.json が無いときのフォールバック（内蔵 CPU/MEM）を注入する」ことだけ。
//! 描画・追従・トレイ・ドラッグ等の実体はすべて tbwidget 側にある。
//!
//! 他アプリから使うときは、CLI/環境変数でパスや app-id を差し替えれば
//! そのまま汎用オーバーレイランナーとして使える:
//!   envmon-overlay --app-id MyApp --data-dir C:\path --state C:\path\state.json
//!   （環境変数 TBWIDGET_APP_ID / TBWIDGET_DATA_DIR / TBWIDGET_CONFIG /
//!     TBWIDGET_STATE / TBWIDGET_LOG / TBWIDGET_TITLE でも可）
#![windows_subsystem = "windows"]

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use sysinfo::System;
use tbwidget::{default_base_dir, AppInfo, Cfg, Widget};

static SYS: OnceLock<Mutex<System>> = OnceLock::new();

/// 内蔵の CPU/MEM 表示（state.json が無い/空のときのフォールバック）。
/// 表示可否・ラベルは config.json の extra（show_cpu/show_mem/cpu_label/mem_label）で制御。
fn sysinfo_fallback(cfg: &Cfg) -> Vec<Widget> {
    let sys_cell = SYS.get_or_init(|| Mutex::new(System::new_all()));
    let mut sys = sys_cell.lock().unwrap();
    sys.refresh_cpu_usage();
    sys.refresh_memory();
    let cpu = sys.global_cpu_usage();
    let total = sys.total_memory() as f64;
    let used = sys.used_memory() as f64;
    let mem = if total > 0.0 { used / total * 100.0 } else { 0.0 };

    let mut v = Vec::new();
    if cfg.extra_bool("show_cpu", true) {
        v.push(Widget::Chip {
            label: cfg.extra_str("cpu_label", "CPU"),
            value: format!("{:.0}%", cpu),
            fg: String::new(),
        });
    }
    if cfg.extra_bool("show_mem", true) {
        v.push(Widget::Chip {
            label: cfg.extra_str("mem_label", "MEM"),
            value: format!("{:.0}%", mem),
            fg: String::new(),
        });
    }
    v
}

/// EnvMonitor 既定の設定（配色・トレイ・内蔵フォールバック用 extra）。
fn envmon_defaults() -> Cfg {
    let mut cfg = Cfg::default();
    cfg.layout = "stacked".into();
    cfg.tray_tip = "EnvMonitor".into();
    cfg.tray_emoji = "📊".into();
    cfg.tray_color = "#4C8DEC".into();
    // 内蔵フォールバック用のアプリ固有キー（config.json に素通しで出る）。
    for (k, v) in [("show_cpu", true), ("show_mem", true)] {
        cfg.extra.insert(k.into(), serde_json::Value::Bool(v));
    }
    for (k, v) in [("cpu_label", "CPU"), ("mem_label", "MEM")] {
        cfg.extra.insert(k.into(), serde_json::Value::String(v.into()));
    }
    cfg
}

/// 環境変数 → CLI の順で上書きを適用する（CLI が最優先）。
fn apply_overrides(mut app: AppInfo) -> AppInfo {
    // 環境変数
    if let Ok(v) = std::env::var("TBWIDGET_APP_ID") {
        app.app_id = v;
    }
    if let Ok(v) = std::env::var("TBWIDGET_TITLE") {
        app.window_title = v;
    }
    if let Ok(v) = std::env::var("TBWIDGET_DATA_DIR") {
        app.base_dir = Some(PathBuf::from(v));
    }
    if let Ok(v) = std::env::var("TBWIDGET_CONFIG") {
        app.config_path = Some(PathBuf::from(v));
    }
    if let Ok(v) = std::env::var("TBWIDGET_STATE") {
        app.state_path = Some(PathBuf::from(v));
    }
    if let Ok(v) = std::env::var("TBWIDGET_LOG") {
        app.log_path = Some(PathBuf::from(v));
    }

    // CLI 引数（--key value）
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        let key = args[i].as_str();
        let val = args.get(i + 1).cloned();
        let mut took = false;
        match key {
            "--app-id" => {
                if let Some(v) = val.clone() {
                    app.app_id = v;
                    took = true;
                }
            }
            "--title" => {
                if let Some(v) = val.clone() {
                    app.window_title = v;
                    took = true;
                }
            }
            "--data-dir" => {
                if let Some(v) = val.clone() {
                    app.base_dir = Some(PathBuf::from(v));
                    took = true;
                }
            }
            "--config" => {
                if let Some(v) = val.clone() {
                    app.config_path = Some(PathBuf::from(v));
                    took = true;
                }
            }
            "--state" => {
                if let Some(v) = val.clone() {
                    app.state_path = Some(PathBuf::from(v));
                    took = true;
                }
            }
            "--log" => {
                if let Some(v) = val.clone() {
                    app.log_path = Some(PathBuf::from(v));
                    took = true;
                }
            }
            _ => {}
        }
        i += if took { 2 } else { 1 };
    }
    app
}

fn main() {
    // 既定は EnvMonitor: %APPDATA%\EnvMonitor\overlay.{config,state,log}。
    // これにより EnvMonitor(Python) 側は無改修で overlay.state.json を書けば連携できる。
    let app = AppInfo::new("EnvMonitor")
        .with_title("envmon-overlay")
        .with_base_dir(default_base_dir("EnvMonitor"))
        .with_file_names("overlay.config.json", "overlay.state.json", "overlay.log")
        .with_defaults(envmon_defaults())
        .with_fallback(sysinfo_fallback);

    let app = apply_overrides(app);
    tbwidget::run(app);
}
