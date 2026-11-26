//! `tbwidget` — 汎用タスクバー追従ウィジェット描画エンジン。
//!
//! Windows のタスクバー上（トレイ左）に、最前面レイヤードウィンドウを重ねて
//! 追従描画する“埋め込み風”オーバーレイ。**何を表示するかは一切解釈しない**。
//! 表示内容は外部プロセスが `state.json`（型付き [`Widget`] 列）に書き、本エンジンは
//! 読んで描くだけ。アプリ固有の値（パス・名前・配色・フォールバック）は [`AppInfo`]
//! として呼び出し側が注入する。
//!
//! ```no_run
//! let app = tbwidget::AppInfo::new("MyApp")
//!     .with_tray(" 自作ウィジェット", "⚡", "#4C8DEC");
//! tbwidget::run(app); // メッセージループに入る（終了までブロック）
//! ```

mod engine;
mod paths;
mod render;
mod schema;

pub use paths::{default_base_dir, Paths};
pub use schema::{color_or, parse_color, Cfg, Pos, StateIn, Widget};

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::SystemTime;

/// state.json が無い/空のときに呼ばれるフォールバック（例: 内蔵 CPU/MEM）。
pub type FallbackFn = fn(&Cfg) -> Vec<Widget>;

/// 呼び出し側が注入するアプリ定義。[`AppInfo::new`] で作り、ビルダで肉付けする。
#[derive(Clone)]
pub struct AppInfo {
    /// ベースディレクトリ名・ウィンドウクラス・単一起動ミューテックスの基になる識別子。
    pub app_id: String,
    /// ウィンドウタイトル（内部用）。
    pub window_title: String,
    /// ベースディレクトリの上書き（省略時 `%APPDATA%\{app_id}`）。
    pub base_dir: Option<PathBuf>,
    pub config_path: Option<PathBuf>,
    pub state_path: Option<PathBuf>,
    pub log_path: Option<PathBuf>,
    /// base_dir 配下に作るときの既定ファイル名。
    pub config_name: String,
    pub state_name: String,
    pub log_name: String,
    /// 既定設定（配色・トレイ・アプリ固有の extra を seed できる）。
    pub defaults: Cfg,
    /// state.json 不在時のフォールバック。
    pub fallback: Option<FallbackFn>,
}

impl AppInfo {
    /// 最小構成。既定パスは `%APPDATA%\{app_id}\{config,state}.json`。
    pub fn new(app_id: impl Into<String>) -> Self {
        let app_id = app_id.into();
        AppInfo {
            window_title: app_id.clone(),
            app_id,
            base_dir: None,
            config_path: None,
            state_path: None,
            log_path: None,
            config_name: "config.json".into(),
            state_name: "state.json".into(),
            log_name: "overlay.log".into(),
            defaults: Cfg::default(),
            fallback: None,
        }
    }

    /// ベースディレクトリと既定ファイル名をまとめて指定。
    pub fn with_base_dir(mut self, dir: impl Into<PathBuf>) -> Self {
        self.base_dir = Some(dir.into());
        self
    }
    pub fn with_file_names(mut self, config: &str, state: &str, log: &str) -> Self {
        self.config_name = config.into();
        self.state_name = state.into();
        self.log_name = log.into();
        self
    }
    pub fn with_config_path(mut self, p: impl Into<PathBuf>) -> Self {
        self.config_path = Some(p.into());
        self
    }
    pub fn with_state_path(mut self, p: impl Into<PathBuf>) -> Self {
        self.state_path = Some(p.into());
        self
    }
    pub fn with_log_path(mut self, p: impl Into<PathBuf>) -> Self {
        self.log_path = Some(p.into());
        self
    }
    pub fn with_title(mut self, t: impl Into<String>) -> Self {
        self.window_title = t.into();
        self
    }
    /// トレイのツールチップ・絵文字・色を既定へ反映。
    pub fn with_tray(mut self, tip: &str, emoji: &str, color: &str) -> Self {
        self.defaults.tray_tip = tip.into();
        self.defaults.tray_emoji = emoji.into();
        self.defaults.tray_color = color.into();
        self
    }
    pub fn with_defaults(mut self, cfg: Cfg) -> Self {
        self.defaults = cfg;
        self
    }
    pub fn with_fallback(mut self, f: FallbackFn) -> Self {
        self.fallback = Some(f);
        self
    }

    fn resolve_paths(&self) -> Paths {
        Paths::resolve(
            &self.app_id,
            self.base_dir.as_ref(),
            self.config_path.as_ref(),
            self.state_path.as_ref(),
            self.log_path.as_ref(),
            &self.config_name,
            &self.state_name,
            &self.log_name,
        )
    }
}

/// エンジンの実行時状態（グローバルに1個）。
pub(crate) struct App {
    pub cfg: Cfg,
    pub defaults: Cfg,
    pub paths: Paths,
    pub fallback: Option<FallbackFn>,
    pub mtime: Option<SystemTime>,
    pub dragging: bool,
    pub drag_off: (i32, i32),
    pub visual_free: bool,
    pub hidden_fs: bool,   // 全画面検出で隠している
    pub hidden_state: bool, // state.visible=false で隠している
    pub shown: bool,        // 実際にウィンドウが可視か（ShowWindow の無駄打ち回避）
    pub timer_ms: u32,
    /// 表示要素のキャッシュ。tick で1回だけ更新。
    pub cached: Vec<Widget>,
    pub last_state_dock: Option<String>, // state 由来の dock 上書き（変化検知用）
}

pub(crate) static APP: OnceLock<Mutex<App>> = OnceLock::new();

/// ログ（デバッグ用）。パス解決前でも落ちないよう best-effort。
pub(crate) fn log(msg: &str) {
    let p = match APP.get() {
        Some(a) => a.lock().unwrap().paths.log.clone(),
        None => return,
    };
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(p) {
        use std::io::Write;
        let _ = writeln!(f, "{}", msg);
    }
}

pub(crate) fn cfg_path() -> PathBuf {
    APP.get().unwrap().lock().unwrap().paths.config.clone()
}

pub(crate) fn cfg_mtime() -> Option<SystemTime> {
    std::fs::metadata(cfg_path()).ok().and_then(|m| m.modified().ok())
}

pub(crate) fn cfg_clone() -> Cfg {
    APP.get().unwrap().lock().unwrap().cfg.clone()
}

/// config.json を読む。無ければ既定を書き出して返す。壊れていれば既定。
pub(crate) fn load_cfg() -> Cfg {
    let (path, defaults) = {
        let a = APP.get().unwrap().lock().unwrap();
        (a.paths.config.clone(), a.defaults.clone())
    };
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str::<Cfg>(&s).unwrap_or_else(|e| {
            log(&format!("config parse error -> defaults: {e}"));
            defaults
        }),
        Err(_) => {
            save_cfg(&defaults);
            defaults
        }
    }
}

pub(crate) fn save_cfg(c: &Cfg) {
    if let Ok(s) = serde_json::to_string_pretty(c) {
        let _ = std::fs::write(cfg_path(), s);
    }
}

/// state.json の visible/dock/opacity を App へ反映する共通処理（file/pipe 共用）。
fn apply_display_overrides(
    a: &mut App,
    visible: bool,
    dock_override: Option<String>,
    opacity_override: Option<u8>,
) {
    a.hidden_state = !visible;
    if let Some(op) = opacity_override {
        a.cfg.opacity = op;
    }
    if let Some(d) = dock_override {
        if a.last_state_dock.as_deref() != Some(d.as_str()) {
            a.cfg.dock = d.clone();
            a.last_state_dock = Some(d);
        }
    } else {
        a.last_state_dock = None;
    }
}

/// state.json を読む（あれば優先）。無ければ fallback、どちらも無ければ空。
/// visible/dock/opacity の上書きも反映する。
pub(crate) fn refresh_metrics() {
    let (path, fallback, cfg) = {
        let a = APP.get().unwrap().lock().unwrap();
        (a.paths.state.clone(), a.fallback, a.cfg.clone())
    };

    let mut widgets: Option<Vec<Widget>> = None;
    let mut visible = true;
    let mut dock_override: Option<String> = None;
    let mut opacity_override: Option<u8> = None;

    if let Ok(s) = std::fs::read_to_string(&path) {
        if let Ok(st) = serde_json::from_str::<StateIn>(&s) {
            visible = st.visible.unwrap_or(true);
            dock_override = st.dock.clone();
            opacity_override =
                st.opacity.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
            let w = st.into_widgets();
            if !w.is_empty() {
                widgets = Some(w);
            }
        }
    }

    let widgets = widgets
        .or_else(|| fallback.map(|f| f(&cfg)))
        .unwrap_or_default();

    let mut a = APP.get().unwrap().lock().unwrap();
    a.cached = widgets;
    apply_display_overrides(&mut a, visible, dock_override, opacity_override);
}

pub(crate) fn cached_widgets() -> Vec<Widget> {
    APP.get().unwrap().lock().unwrap().cached.clone()
}

/// エンジンを起動し、メッセージループに入る（終了までブロック）。
pub fn run(info: AppInfo) {
    let paths = info.resolve_paths();
    let _ = std::fs::remove_file(&paths.log);

    let cfg = {
        // config は load_cfg が APP 経由で読むため、先に APP を初期化する。
        let app = App {
            cfg: info.defaults.clone(),
            defaults: info.defaults.clone(),
            paths,
            fallback: info.fallback,
            mtime: None,
            dragging: false,
            drag_off: (0, 0),
            visual_free: false,
            hidden_fs: false,
            hidden_state: false,
            shown: true,
            timer_ms: info.defaults.update_interval_ms,
            cached: Vec::new(),
            last_state_dock: None,
        };
        let _ = APP.set(Mutex::new(app));
        load_cfg()
    };

    {
        let mut a = APP.get().unwrap().lock().unwrap();
        a.timer_ms = cfg.update_interval_ms;
        a.cfg = cfg;
        a.mtime = std::fs::metadata(&a.paths.config).ok().and_then(|m| m.modified().ok());
    }

    log("=== tbwidget engine start ===");
    refresh_metrics(); // 初回の値をキャッシュ（幅自動計算のため）
    engine::run_window(info);
}
