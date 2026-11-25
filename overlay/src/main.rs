//! Phase1 PoC（インタラクション作り替え版）
//!
//! モデル（ユーザー要望）:
//!   - 基本は「透過＝文字だけ」(taskbar モード, colorkey)。トレイ左に追従。
//!   - 掴む用の「グリップ」を左に表示。そこを掴んでドラッグ操作する（他は貫通）。
//!   - タスクバー上にいる間はバー内で横移動（トレイ左端からの間隔を記憶）。
//!   - タスクバーから外す動作をしたら free モードへ＝背景付きパネルになり自由配置。
//!   - ラベルと値の「2段組み(stacked)」レイアウトも設定で選べる。
//!   - トレイ常駐＋右クリック「終了」。アイコンは絵文字の単色シルエット（雑）。
//!   - 全画面検出で自動非表示。設定(JSON)はホットリロード。
//!   - CPU/MEM は PoC では Rust 側(sysinfo)で直接取得（計画の state.json 連携は Phase2）。
#![windows_subsystem = "windows"]

use std::io::Write;
use std::sync::{Mutex, OnceLock};
use std::time::SystemTime;

use serde::{Deserialize, Serialize};
use sysinfo::System;
use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::{
    COLORREF, FALSE, HANDLE, HWND, LPARAM, LRESULT, POINT, RECT, TRUE, WPARAM,
};
use windows::Win32::Graphics::Gdi::{
    BeginPaint, CreateBitmap, CreateCompatibleDC, CreateDIBSection, CreateFontW, CreateRoundRectRgn,
    CreateSolidBrush, DeleteDC, DeleteObject, DrawTextW, EndPaint, FillRect, GetMonitorInfoW,
    InvalidateRect, MonitorFromWindow, ScreenToClient, SelectObject, SetBkMode, SetTextColor,
    SetWindowRgn, BITMAPINFO, DIB_RGB_COLORS, DRAW_TEXT_FORMAT, DT_BOTTOM, DT_CALCRECT, DT_CENTER,
    DT_LEFT,
    DT_RIGHT, DT_SINGLELINE, DT_TOP, DT_VCENTER, HBITMAP, HDC, HFONT, HGDIOBJ, HRGN, MONITORINFO,
    MONITOR_DEFAULTTOPRIMARY, PAINTSTRUCT, TRANSPARENT,
};
use windows::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Threading::CreateMutexW;
use windows::Win32::UI::HiDpi::{
    GetDpiForWindow, SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};
use windows::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NOTIFYICONDATAW,
};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreateIconIndirect, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu,
    DestroyWindow, DispatchMessageW, FindWindowExW, FindWindowW, GetClassNameW, GetClientRect,
    GetCursorPos, GetForegroundWindow, GetMessageW, GetWindowRect, KillTimer, LoadCursorW,
    PostQuitMessage, RegisterClassW, SetForegroundWindow, SetLayeredWindowAttributes, SetTimer,
    SetWindowPos, ShowWindow, TrackPopupMenu, TranslateMessage, HICON, HMENU, HTCLIENT,
    HTTRANSPARENT, HWND_TOPMOST, ICONINFO, IDC_ARROW, LWA_ALPHA, LWA_COLORKEY, MF_SEPARATOR,
    MF_STRING, MSG, SWP_NOACTIVATE, SW_HIDE, SW_SHOWNOACTIVATE, TPM_NONOTIFY, TPM_RETURNCMD,
    TPM_RIGHTBUTTON, WM_APP, WM_CONTEXTMENU, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
    WM_NCHITTEST, WM_RBUTTONUP, WNDCLASSW, WS_CLIPSIBLINGS, WS_EX_LAYERED, WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP, WS_VISIBLE,
};

const KEY: COLORREF = COLORREF(0x0001_0101); // taskbar(透過)モードのキー色
const TIMER_ID: usize = 1;
// 設定/状態/ログは %APPDATA%\EnvMonitor\ 配下（EnvMonitor 本体と共有）。
fn base_dir() -> std::path::PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_else(|_| ".".into());
    let d = std::path::Path::new(&appdata).join("EnvMonitor");
    let _ = std::fs::create_dir_all(&d);
    d
}
fn cfg_path() -> std::path::PathBuf {
    base_dir().join("overlay.config.json")
}
fn log_path() -> std::path::PathBuf {
    base_dir().join("overlay.log")
}
/// Python(EnvMonitor)が書く表示状態。あれば優先、無ければ内蔵 CPU/MEM を表示。
fn state_path() -> std::path::PathBuf {
    base_dir().join("overlay.state.json")
}

const WM_TRAY: u32 = WM_APP + 1;
const TRAY_UID: u32 = 1;
const ID_REDOCK: usize = 10;
const ID_OPENCFG: usize = 11;
const ID_QUIT: usize = 12;

// ============================ 設定 ============================
#[derive(Serialize, Deserialize, Clone)]
struct Pos {
    x: i32,
    y: i32,
}

#[derive(Serialize, Deserialize, Clone)]
#[serde(default)]
struct Cfg {
    dock: String,  // "taskbar"=透過・トレイ左追従 / "free"=背景付き自由配置
    pos: Pos,      // free 位置
    gap: i32,      // taskbar: トレイ左端からの間隔(px)
    /// 内容に合わせて幅を自動調整する（true のとき width は無視）
    auto_width: bool,
    width: i32,
    /// 値の桁数を見込んで幅を固定（桁変化でガタつかないように）。0 で無効。
    value_digits: i32,
    layout: String, // "inline"=1行 / "stacked"=ラベル+値の2段組み
    opacity: u8,    // free モード背景の不透明度 0..255
    bg_color: String,
    text_color: String,
    muted_color: String, // グリップ・ラベルの色
    font_face: String,
    value_font_size: i32,
    label_font_size: i32,
    font_weight: i32,
    corner_radius: i32, // free モードの角丸
    align: String,      // inline: left|center|right
    grip_width: i32,
    update_interval_ms: u32,
    show_cpu: bool,
    show_mem: bool,
    cpu_label: String,
    mem_label: String,
    separator: String, // inline の区切り
    hide_on_fullscreen: bool,
    tray_emoji: String,
    tray_color: String,
}

impl Default for Cfg {
    fn default() -> Self {
        Cfg {
            dock: "taskbar".into(),
            pos: Pos { x: 1500, y: 1020 },
            gap: 8,
            auto_width: true,
            width: 200,
            value_digits: 3,
            layout: "inline".into(),
            opacity: 235,
            bg_color: "#1E222A".into(),
            text_color: "#E9EBEF".into(),
            muted_color: "#8A93A0".into(),
            font_face: "Segoe UI".into(),
            value_font_size: 13,
            label_font_size: 9,
            font_weight: 600,
            corner_radius: 8,
            align: "center".into(),
            grip_width: 12,
            update_interval_ms: 1000,
            show_cpu: true,
            show_mem: true,
            cpu_label: "CPU".into(),
            mem_label: "MEM".into(),
            separator: "   ".into(),
            hide_on_fullscreen: true,
            tray_emoji: "📊".into(),
            tray_color: "#4C8DEC".into(),
        }
    }
}

/// 表示チップ（ラベル・値・値の色hex。fg 空なら text_color）。
#[derive(Clone)]
struct Chip {
    label: String,
    value: String,
    fg: String,
}

/// Python が書く state.json のスキーマ。
#[derive(Deserialize)]
struct StateIn {
    #[serde(default)]
    chips: Vec<ChipIn>,
}
#[derive(Deserialize)]
struct ChipIn {
    #[serde(default)]
    label: String,
    #[serde(default)]
    value: String,
    #[serde(default)]
    fg: String,
}

struct App {
    cfg: Cfg,
    mtime: Option<SystemTime>,
    dragging: bool,
    drag_off: (i32, i32), // カーソル - ウィンドウ左上
    visual_free: bool,    // 現在の見た目が free(背景) か（再設定の抑止用）
    hidden_fs: bool,
    timer_ms: u32,
    /// 表示チップのキャッシュ。tick で1回だけ更新（CPU の二重取得＆state.json 連打を避ける）。
    cached: Vec<Chip>,
}

static APP: OnceLock<Mutex<App>> = OnceLock::new();
static SYS: OnceLock<Mutex<System>> = OnceLock::new();

fn log(msg: &str) {
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(log_path()) {
        let _ = writeln!(f, "{}", msg);
    }
}

fn cfg_mtime() -> Option<SystemTime> {
    std::fs::metadata(cfg_path()).ok().and_then(|m| m.modified().ok())
}

fn load_cfg() -> Cfg {
    match std::fs::read_to_string(cfg_path()) {
        Ok(s) => serde_json::from_str::<Cfg>(&s).unwrap_or_else(|e| {
            log(&format!("config parse error -> defaults: {e}"));
            Cfg::default()
        }),
        Err(_) => {
            let c = Cfg::default();
            save_cfg(&c);
            c
        }
    }
}

fn save_cfg(c: &Cfg) {
    if let Ok(s) = serde_json::to_string_pretty(c) {
        let _ = std::fs::write(cfg_path(), s);
    }
}

fn parse_color(s: &str, default: u32) -> COLORREF {
    let h = s.trim().trim_start_matches('#');
    if h.len() == 6 {
        if let Ok(v) = u32::from_str_radix(h, 16) {
            let r = (v >> 16) & 0xff;
            let g = (v >> 8) & 0xff;
            let b = v & 0xff;
            return COLORREF(r | (g << 8) | (b << 16));
        }
    }
    COLORREF(default)
}

fn sys_mutex() -> &'static Mutex<System> {
    SYS.get_or_init(|| Mutex::new(System::new_all()))
}

/// 内蔵の CPU/MEM チップ（state.json が無いときのフォールバック）。
fn sysinfo_chips(cfg: &Cfg) -> Vec<Chip> {
    let mut sys = sys_mutex().lock().unwrap();
    sys.refresh_cpu_usage();
    sys.refresh_memory();
    let cpu = sys.global_cpu_usage();
    let total = sys.total_memory() as f64;
    let used = sys.used_memory() as f64;
    let mem = if total > 0.0 { used / total * 100.0 } else { 0.0 };
    let mut v = Vec::new();
    if cfg.show_cpu {
        v.push(Chip { label: cfg.cpu_label.clone(), value: format!("{:.0}%", cpu), fg: String::new() });
    }
    if cfg.show_mem {
        v.push(Chip { label: cfg.mem_label.clone(), value: format!("{:.0}%", mem), fg: String::new() });
    }
    v
}

/// Python が書いた state.json を読む（あれば優先）。
fn read_state() -> Option<Vec<Chip>> {
    let s = std::fs::read_to_string(state_path()).ok()?;
    let st: StateIn = serde_json::from_str(&s).ok()?;
    if st.chips.is_empty() {
        return None;
    }
    Some(
        st.chips
            .into_iter()
            .map(|c| Chip { label: c.label, value: c.value, fg: c.fg })
            .collect(),
    )
}

fn cfg_clone() -> Cfg {
    APP.get().unwrap().lock().unwrap().cfg.clone()
}

/// tick ごとに1回だけ内容を更新してキャッシュ（state.json 優先・無ければ内蔵）。
fn refresh_metrics() {
    let chips = read_state().unwrap_or_else(|| sysinfo_chips(&cfg_clone()));
    APP.get().unwrap().lock().unwrap().cached = chips;
}

fn cached_items() -> Vec<Chip> {
    APP.get().unwrap().lock().unwrap().cached.clone()
}

/// 単一行テキストの幅を測る（メモリDCにフォントを選択して DT_CALCRECT）。
unsafe fn text_w(memdc: HDC, font: HFONT, s: &str) -> i32 {
    if s.is_empty() {
        return 0;
    }
    let old = SelectObject(memdc, HGDIOBJ(font.0));
    let mut r = RECT::default();
    let mut wt: Vec<u16> = s.encode_utf16().collect();
    DrawTextW(memdc, &mut wt, &mut r, DRAW_TEXT_FORMAT(DT_CALCRECT.0 | DT_SINGLELINE.0));
    SelectObject(memdc, old);
    r.right - r.left
}

/// 値の桁テンプレ。数字先頭部分を "0"*digits に置換し単位は保持（"27.3℃"->"000℃"）。
/// 桁変化で幅が変わらないよう、この幅を最小として確保する。
fn value_template(value: &str, digits: i32) -> Option<String> {
    if digits <= 0 || !value.chars().any(|c| c.is_ascii_digit()) {
        return None;
    }
    let unit: String = value
        .chars()
        .skip_while(|c| c.is_ascii_digit() || *c == '.' || *c == '-')
        .collect();
    Some(format!("{}{}", "0".repeat(digits as usize), unit))
}

/// 内容に合わせた幅（px）を測る。グリップ＋余白込み。桁テンプレで最小幅を確保。
unsafe fn measure_width(cfg: &Cfg, dpi: i32) -> i32 {
    let sc = |v: i32| v * dpi / 96;
    let items = cached_items();
    let memdc = CreateCompatibleDC(HDC::default());

    // 値の実測と桁テンプレ実測の大きい方を使う。
    let val_reserved = |f: HFONT, v: &str| -> i32 {
        let a = text_w(memdc, f, v);
        match value_template(v, cfg.value_digits) {
            Some(t) => a.max(text_w(memdc, f, &t)),
            None => a,
        }
    };

    let content = if cfg.layout == "stacked" {
        let labf = make_font(sc(cfg.label_font_size), 400, &cfg.font_face);
        let valf = make_font(sc(cfg.value_font_size), cfg.font_weight, &cfg.font_face);
        let mut total = 0;
        for c in &items {
            let cw = text_w(memdc, labf, &c.label).max(val_reserved(valf, &c.value));
            total += cw + sc(16);
        }
        let _ = DeleteObject(HGDIOBJ(labf.0));
        let _ = DeleteObject(HGDIOBJ(valf.0));
        total
    } else {
        let f = make_font(sc(cfg.value_font_size), cfg.font_weight, &cfg.font_face);
        let sep_w = text_w(memdc, f, &cfg.separator);
        let mut total = 0;
        for (i, c) in items.iter().enumerate() {
            if i > 0 {
                total += sep_w;
            }
            total += text_w(memdc, f, &format!("{} ", c.label)) + val_reserved(f, &c.value);
        }
        let _ = DeleteObject(HGDIOBJ(f.0));
        total
    };

    let _ = DeleteDC(memdc);
    let total = sc(cfg.grip_width) + sc(6) + content + sc(14);
    total.max(sc(60))
}

/// グリップの当たり判定幅（見た目より広めにして掴みやすく）。
fn grip_hit_width(hwnd: HWND, cfg: &Cfg) -> i32 {
    let dpi = dpi_scale(hwnd);
    (cfg.grip_width + 8) * dpi / 96
}

// ============================ 幾何 ============================
fn dpi_scale(hwnd: HWND) -> i32 {
    let d = unsafe { GetDpiForWindow(hwnd) } as i32;
    if d <= 0 {
        96
    } else {
        d
    }
}

unsafe fn tray_rect() -> Option<(RECT, i32)> {
    let tray = FindWindowW(w!("Shell_TrayWnd"), PCWSTR::null()).unwrap_or_default();
    if tray.0.is_null() {
        return None;
    }
    let mut tr = RECT::default();
    if GetWindowRect(tray, &mut tr).is_err() {
        return None;
    }
    let mut tray_left = tr.right;
    let notify = FindWindowExW(tray, HWND::default(), w!("TrayNotifyWnd"), PCWSTR::null())
        .unwrap_or_default();
    if !notify.0.is_null() {
        let mut nr = RECT::default();
        if GetWindowRect(notify, &mut nr).is_ok() {
            tray_left = nr.left;
        }
    }
    Some((tr, tray_left))
}

fn content_height(hwnd: HWND, cfg: &Cfg) -> i32 {
    let dpi = dpi_scale(hwnd);
    let sc = |v: i32| v * dpi / 96;
    if cfg.layout == "stacked" {
        sc(cfg.label_font_size) + sc(cfg.value_font_size) + sc(14)
    } else {
        sc(cfg.value_font_size) + sc(16)
    }
}

/// 設定から (x,y,w,h) スクリーン座標。
unsafe fn geometry(hwnd: HWND, cfg: &Cfg) -> (i32, i32, i32, i32) {
    let dpi = dpi_scale(hwnd);
    let sc = |v: i32| v * dpi / 96;
    let w = if cfg.auto_width { measure_width(cfg, dpi) } else { sc(cfg.width) };
    if cfg.dock == "free" {
        return (cfg.pos.x, cfg.pos.y, w, content_height(hwnd, cfg));
    }
    match tray_rect() {
        Some((tr, tray_left)) => (tray_left - w - sc(cfg.gap), tr.top, w, tr.bottom - tr.top),
        None => (cfg.pos.x, cfg.pos.y, w, content_height(hwnd, cfg)),
    }
}

unsafe fn apply_visuals(hwnd: HWND, cfg: &Cfg) {
    let free = cfg.dock == "free";
    if free {
        let _ = SetLayeredWindowAttributes(hwnd, COLORREF(0), cfg.opacity, LWA_ALPHA);
    } else {
        let _ = SetLayeredWindowAttributes(hwnd, KEY, 0, LWA_COLORKEY);
    }
    APP.get().unwrap().lock().unwrap().visual_free = free;
}

unsafe fn apply_region(hwnd: HWND, cfg: &Cfg, w: i32, h: i32) {
    let dpi = dpi_scale(hwnd);
    if cfg.dock == "free" && cfg.corner_radius > 0 {
        let r = cfg.corner_radius * dpi / 96 * 2;
        let rgn = CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r);
        let _ = SetWindowRgn(hwnd, rgn, TRUE);
    } else {
        let _ = SetWindowRgn(hwnd, HRGN::default(), TRUE);
    }
}

unsafe fn apply_geometry(hwnd: HWND, cfg: &Cfg) {
    let (x, y, w, h) = geometry(hwnd, cfg);
    let _ = SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE);
    apply_region(hwnd, cfg, w, h);
}

unsafe fn apply_all(hwnd: HWND) {
    let cfg = cfg_clone();
    apply_visuals(hwnd, &cfg);
    apply_geometry(hwnd, &cfg);
    let mut app = APP.get().unwrap().lock().unwrap();
    if app.cfg.update_interval_ms != app.timer_ms {
        let _ = KillTimer(hwnd, TIMER_ID);
        SetTimer(hwnd, TIMER_ID, app.cfg.update_interval_ms.max(100), None);
        app.timer_ms = app.cfg.update_interval_ms;
    }
}

/// 前面ウィンドウがモニタ全面を覆う＝全画面。
unsafe fn is_fullscreen_foreground() -> bool {
    let fg = GetForegroundWindow();
    if fg.0.is_null() {
        return false;
    }
    let mut buf = [0u16; 256];
    let n = GetClassNameW(fg, &mut buf);
    let cls = String::from_utf16_lossy(&buf[..n.max(0) as usize]);
    if cls == "WorkerW" || cls == "Progman" || cls == "Shell_TrayWnd" {
        return false;
    }
    let mut wr = RECT::default();
    if GetWindowRect(fg, &mut wr).is_err() {
        return false;
    }
    let hmon = MonitorFromWindow(fg, MONITOR_DEFAULTTOPRIMARY);
    let mut mi = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    if !GetMonitorInfoW(hmon, &mut mi).as_bool() {
        return false;
    }
    let m = mi.rcMonitor;
    wr.left <= m.left && wr.top <= m.top && wr.right >= m.right && wr.bottom >= m.bottom
}

// ============================ 描画 ============================
unsafe fn make_font(px: i32, weight: i32, face: &str) -> HFONT {
    let f: Vec<u16> = face.encode_utf16().chain(std::iter::once(0)).collect();
    CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, PCWSTR(f.as_ptr()))
}

unsafe fn draw_text(hdc: HDC, text: &str, rc: &RECT, fmt: DRAW_TEXT_FORMAT) {
    let mut wt: Vec<u16> = text.encode_utf16().collect();
    let mut r = *rc;
    if wt.is_empty() {
        return;
    }
    DrawTextW(hdc, &mut wt, &mut r, fmt);
}

unsafe fn paint(hwnd: HWND) {
    let cfg = cfg_clone();
    let dpi = dpi_scale(hwnd);
    let sc = |v: i32| v * dpi / 96;

    let mut ps = PAINTSTRUCT::default();
    let hdc = BeginPaint(hwnd, &mut ps);
    let mut rc = RECT::default();
    let _ = GetClientRect(hwnd, &mut rc);

    // 背景: free は bg_color、taskbar はキー色(透過)。
    let bg = if cfg.dock == "free" {
        parse_color(&cfg.bg_color, 0x002A_221E)
    } else {
        KEY
    };
    let bbrush = CreateSolidBrush(bg);
    FillRect(hdc, &rc, bbrush);
    let _ = DeleteObject(HGDIOBJ(bbrush.0));

    SetBkMode(hdc, TRANSPARENT);
    let muted = parse_color(&cfg.muted_color, 0x00A0_938A);
    let text_col = parse_color(&cfg.text_color, 0x00EF_EBE9);

    // グリップ（掴む部分）を左に。縦バー "|" を muted 色で。
    let grip_w = sc(cfg.grip_width);
    let h = rc.bottom - rc.top;
    let bar_h = (h * 55 / 100).max(sc(10));
    let bw = sc(2).max(2);
    let cx = grip_w / 2;
    let gb = CreateSolidBrush(muted);
    let r = RECT {
        left: cx - bw / 2,
        top: (h - bar_h) / 2,
        right: cx - bw / 2 + bw,
        bottom: (h + bar_h) / 2,
    };
    FillRect(hdc, &r, gb);
    let _ = DeleteObject(HGDIOBJ(gb.0));

    // 内容領域（グリップの右）
    let content = RECT { left: rc.left + grip_w, ..rc };
    let items = cached_items();

    if cfg.layout == "stacked" {
        // 各指標を「ラベル(上) / 値(下)」の縦2段で、横に等分して並べる。
        let lab_font = make_font(sc(cfg.label_font_size), 400, &cfg.font_face);
        let val_font = make_font(sc(cfg.value_font_size), cfg.font_weight, &cfg.font_face);
        let n = items.len().max(1) as i32;
        let cw = (content.right - content.left) / n;
        let mid = content.top + (content.bottom - content.top) * 42 / 100;
        for (i, chip) in items.iter().enumerate() {
            let x0 = content.left + i as i32 * cw;
            let col_top = RECT { left: x0, top: content.top + sc(2), right: x0 + cw, bottom: mid };
            let col_bot = RECT { left: x0, top: mid, right: x0 + cw, bottom: content.bottom - sc(2) };
            let vcol = if chip.fg.is_empty() { text_col } else { parse_color(&chip.fg, 0x00EF_EBE9) };
            let old = SelectObject(hdc, HGDIOBJ(lab_font.0));
            SetTextColor(hdc, muted);
            draw_text(hdc, &chip.label, &col_top, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_BOTTOM.0 | DT_SINGLELINE.0));
            SelectObject(hdc, HGDIOBJ(val_font.0));
            SetTextColor(hdc, vcol);
            draw_text(hdc, &chip.value, &col_bot, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_TOP.0 | DT_SINGLELINE.0));
            SelectObject(hdc, old);
        }
        let _ = DeleteObject(HGDIOBJ(lab_font.0));
        let _ = DeleteObject(HGDIOBJ(val_font.0));
    } else {
        // inline: "CPU 12%   MEM 45%" を1行で（色は先頭チップの fg を代表色に）。
        let line = items
            .iter()
            .map(|c| format!("{} {}", c.label, c.value))
            .collect::<Vec<_>>()
            .join(&cfg.separator);
        let vcol = items
            .iter()
            .find(|c| !c.fg.is_empty())
            .map(|c| parse_color(&c.fg, 0x00EF_EBE9))
            .unwrap_or(text_col);
        let font = make_font(sc(cfg.value_font_size), cfg.font_weight, &cfg.font_face);
        let old = SelectObject(hdc, HGDIOBJ(font.0));
        SetTextColor(hdc, vcol);
        let align = match cfg.align.as_str() {
            "left" => DT_LEFT,
            "right" => DT_RIGHT,
            _ => DT_CENTER,
        };
        let mut cr = content;
        if align == DT_LEFT {
            cr.left += sc(6);
        } else if align == DT_RIGHT {
            cr.right -= sc(6);
        }
        draw_text(hdc, &line, &cr, DRAW_TEXT_FORMAT(align.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
        SelectObject(hdc, old);
        let _ = DeleteObject(HGDIOBJ(font.0));
    }

    let _ = EndPaint(hwnd, &ps);
}

// ============================ トレイ ============================
unsafe fn make_emoji_icon(emoji: &str, color: COLORREF) -> Option<HICON> {
    let size = 32i32;
    let memdc = CreateCompatibleDC(HDC::default());
    if memdc.is_invalid() {
        return None;
    }
    let mut bmi = BITMAPINFO::default();
    bmi.bmiHeader.biSize =
        std::mem::size_of::<windows::Win32::Graphics::Gdi::BITMAPINFOHEADER>() as u32;
    bmi.bmiHeader.biWidth = size;
    bmi.bmiHeader.biHeight = -size;
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = 0;

    let mut bits: *mut core::ffi::c_void = std::ptr::null_mut();
    let dib = CreateDIBSection(memdc, &bmi, DIB_RGB_COLORS, &mut bits, HANDLE::default(), 0).ok()?;
    let old_bmp = SelectObject(memdc, HGDIOBJ(dib.0));
    let font = make_font(26, 400, "Segoe UI Emoji");
    let old_font = SelectObject(memdc, HGDIOBJ(font.0));
    SetBkMode(memdc, TRANSPARENT);
    SetTextColor(memdc, color);
    let mut r = RECT { left: 0, top: 0, right: size, bottom: size };
    let mut wt: Vec<u16> = emoji.encode_utf16().collect();
    DrawTextW(memdc, &mut wt, &mut r, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
    if !bits.is_null() {
        let px = bits as *mut u32;
        for i in 0..(size * size) as isize {
            let p = *px.offset(i);
            if p & 0x00FF_FFFF != 0 {
                *px.offset(i) = p | 0xFF00_0000;
            }
        }
    }
    SelectObject(memdc, old_font);
    let _ = DeleteObject(HGDIOBJ(font.0));
    SelectObject(memdc, old_bmp);

    let mask: HBITMAP = CreateBitmap(size, size, 1, 1, None);
    let ii = ICONINFO {
        fIcon: TRUE,
        xHotspot: 0,
        yHotspot: 0,
        hbmMask: mask,
        hbmColor: dib,
    };
    let icon = CreateIconIndirect(&ii).ok();
    let _ = DeleteObject(HGDIOBJ(mask.0));
    let _ = DeleteObject(HGDIOBJ(dib.0));
    let _ = DeleteDC(memdc);
    icon
}

unsafe fn tray_add(hwnd: HWND, icon: HICON) {
    let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
    nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
    nid.hWnd = hwnd;
    nid.uID = TRAY_UID;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = WM_TRAY;
    nid.hIcon = icon;
    let tip: Vec<u16> = "envmon-overlay".encode_utf16().collect();
    for (i, c) in tip.iter().enumerate().take(nid.szTip.len() - 1) {
        nid.szTip[i] = *c;
    }
    let _ = Shell_NotifyIconW(NIM_ADD, &nid);
}

unsafe fn tray_del(hwnd: HWND) {
    let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
    nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
    nid.hWnd = hwnd;
    nid.uID = TRAY_UID;
    let _ = Shell_NotifyIconW(NIM_DELETE, &nid);
}

unsafe fn show_tray_menu(hwnd: HWND) {
    let menu = match CreatePopupMenu() {
        Ok(m) => m,
        Err(_) => return,
    };
    let _ = AppendMenuW(menu, MF_STRING, ID_REDOCK, w!("タスクバーに戻す"));
    let _ = AppendMenuW(menu, MF_STRING, ID_OPENCFG, w!("設定ファイルを開く"));
    let _ = AppendMenuW(menu, MF_SEPARATOR, 0, PCWSTR::null());
    let _ = AppendMenuW(menu, MF_STRING, ID_QUIT, w!("終了"));
    let mut pt = POINT::default();
    let _ = GetCursorPos(&mut pt);
    let _ = SetForegroundWindow(hwnd);
    let cmd = TrackPopupMenu(
        menu,
        TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
        pt.x,
        pt.y,
        0,
        hwnd,
        None,
    );
    let _ = DestroyMenu(menu);
    match cmd.0 as usize {
        ID_QUIT => {
            tray_del(hwnd);
            let _ = DestroyWindow(hwnd);
        }
        ID_OPENCFG => {
            let _ = std::process::Command::new("notepad.exe").arg(cfg_path()).spawn();
        }
        ID_REDOCK => {
            {
                let mut app = APP.get().unwrap().lock().unwrap();
                app.cfg.dock = "taskbar".into();
                save_cfg(&app.cfg);
            }
            apply_all(hwnd);
            let _ = InvalidateRect(hwnd, None, FALSE);
        }
        _ => {}
    }
}

// ============================ ウィンドウ手続き ============================
unsafe fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    use windows::Win32::UI::WindowsAndMessaging::{WM_CREATE, WM_DESTROY, WM_PAINT, WM_TIMER};
    match msg {
        WM_CREATE => {
            let ms = cfg_clone().update_interval_ms.max(100);
            SetTimer(hwnd, TIMER_ID, ms, None);
            LRESULT(0)
        }
        // グリップの上だけ掴める。その他は貫通（タスクバーを邪魔しない）。
        WM_NCHITTEST => {
            let sx = (lp.0 & 0xffff) as i16 as i32;
            let sy = ((lp.0 >> 16) & 0xffff) as i16 as i32;
            let mut p = POINT { x: sx, y: sy };
            let _ = ScreenToClient(hwnd, &mut p);
            // 当たり判定は見た目より広め（掴みやすさ優先）。
            let hit = grip_hit_width(hwnd, &cfg_clone());
            if p.x >= -4 && p.x <= hit {
                LRESULT(HTCLIENT as isize)
            } else {
                LRESULT(HTTRANSPARENT as isize)
            }
        }
        WM_LBUTTONDOWN => {
            let mut pt = POINT::default();
            let _ = GetCursorPos(&mut pt);
            let mut wr = RECT::default();
            let _ = GetWindowRect(hwnd, &mut wr);
            {
                let mut app = APP.get().unwrap().lock().unwrap();
                app.dragging = true;
                app.drag_off = (pt.x - wr.left, pt.y - wr.top);
            }
            SetCapture(hwnd);
            LRESULT(0)
        }
        WM_MOUSEMOVE => {
            let dragging = APP.get().unwrap().lock().unwrap().dragging;
            if dragging {
                let mut pt = POINT::default();
                let _ = GetCursorPos(&mut pt);
                let (ox, oy) = APP.get().unwrap().lock().unwrap().drag_off;
                let mut wr = RECT::default();
                let _ = GetWindowRect(hwnd, &mut wr);
                let w = wr.right - wr.left;
                let h = wr.bottom - wr.top;

                // バー判定はカーソルの縦位置で（窓中心だとブレる）。
                // 下辺タスクバー: カーソルがバー上端より下＝バー上（レール）。
                let (on_bar, fx, fy) = match tray_rect() {
                    Some((tr, tray_left)) if pt.y >= tr.top - 4 => {
                        // レール: 縦はバー上端に固定、横はバー内にクランプ。
                        let minx = tr.left + 2;
                        let maxx = (tray_left - w - 2).max(minx);
                        let x = (pt.x - ox).clamp(minx, maxx);
                        (true, x, tr.top)
                    }
                    _ => (false, pt.x - ox, pt.y - oy),
                };

                // バー内外で見た目(透過/背景)を切替（変化時のみ）。
                let want_free = !on_bar;
                let cur_free = APP.get().unwrap().lock().unwrap().visual_free;
                if want_free != cur_free {
                    let mut c = cfg_clone();
                    c.dock = if want_free { "free".into() } else { "taskbar".into() };
                    apply_visuals(hwnd, &c);
                    apply_region(hwnd, &c, w, h);
                }

                let _ = SetWindowPos(hwnd, HWND_TOPMOST, fx, fy, w, h, SWP_NOACTIVATE);
            }
            LRESULT(0)
        }
        WM_LBUTTONUP => {
            let was = APP.get().unwrap().lock().unwrap().dragging;
            if was {
                let _ = ReleaseCapture();
                let mut pt = POINT::default();
                let _ = GetCursorPos(&mut pt);
                let mut wr = RECT::default();
                let _ = GetWindowRect(hwnd, &mut wr);
                let w = wr.right - wr.left;
                let on_bar = tray_rect().map(|(tr, _)| pt.y >= tr.top - 4).unwrap_or(false);
                {
                    let mut app = APP.get().unwrap().lock().unwrap();
                    app.dragging = false;
                    if on_bar {
                        app.cfg.dock = "taskbar".into();
                        if let Some((_, tray_left)) = tray_rect() {
                            app.cfg.gap = (tray_left - (wr.left + w)).max(0);
                        }
                    } else {
                        app.cfg.dock = "free".into();
                        app.cfg.pos = Pos { x: wr.left, y: wr.top };
                    }
                    save_cfg(&app.cfg);
                }
                let cfg = cfg_clone();
                apply_visuals(hwnd, &cfg);
                apply_geometry(hwnd, &cfg);
                let _ = InvalidateRect(hwnd, None, FALSE);
            }
            LRESULT(0)
        }
        WM_TIMER => {
            let changed = {
                let app = APP.get().unwrap().lock().unwrap();
                cfg_mtime() != app.mtime
            };
            if changed {
                let c = load_cfg();
                {
                    let mut app = APP.get().unwrap().lock().unwrap();
                    app.cfg = c;
                    app.mtime = cfg_mtime();
                }
                apply_all(hwnd);
            }

            refresh_metrics(); // 値を1回だけ取得してキャッシュ更新

            let (hide_fs, dragging, dock) = {
                let app = APP.get().unwrap().lock().unwrap();
                (app.cfg.hide_on_fullscreen, app.dragging, app.cfg.dock.clone())
            };

            if hide_fs {
                let fs = is_fullscreen_foreground();
                let mut app = APP.get().unwrap().lock().unwrap();
                if fs && !app.hidden_fs {
                    let _ = ShowWindow(hwnd, SW_HIDE);
                    app.hidden_fs = true;
                    return LRESULT(0);
                } else if !fs && app.hidden_fs {
                    let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                    app.hidden_fs = false;
                }
                if app.hidden_fs {
                    return LRESULT(0);
                }
            }

            // taskbar モードはドラッグ中以外は追従。
            if dock == "taskbar" && !dragging {
                let cfg = cfg_clone();
                apply_geometry(hwnd, &cfg);
            }
            let _ = InvalidateRect(hwnd, None, FALSE);
            LRESULT(0)
        }
        WM_PAINT => {
            paint(hwnd);
            LRESULT(0)
        }
        m if m == WM_TRAY => {
            let ev = (lp.0 as u32) & 0xffff;
            if ev == WM_RBUTTONUP || ev == WM_CONTEXTMENU {
                show_tray_menu(hwnd);
            }
            LRESULT(0)
        }
        WM_DESTROY => {
            let _ = KillTimer(hwnd, TIMER_ID);
            tray_del(hwnd);
            PostQuitMessage(0);
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, msg, wp, lp),
    }
}

extern "system" fn wndproc_entry(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe { wndproc(hwnd, msg, wp, lp) }
}

fn main() {
    let _ = std::fs::remove_file(log_path());
    log("=== envmon-overlay PoC (grip-drag/dock/stacked/tray) ===");

    // 二重起動防止（分裂対策）。既に起動していれば何もせず終了。
    let _mutex = unsafe {
        let m = CreateMutexW(None, FALSE, w!("EnvmonOverlayPoC_SingleInstance")).ok();
        if GetLastError() == ERROR_ALREADY_EXISTS {
            log("already running -> exit");
            return;
        }
        m
    };

    let cfg = load_cfg();
    let _ = APP.set(Mutex::new(App {
        timer_ms: cfg.update_interval_ms,
        cfg,
        mtime: cfg_mtime(),
        dragging: false,
        drag_off: (0, 0),
        visual_free: false,
        hidden_fs: false,
        cached: Vec::new(),
    }));
    refresh_metrics(); // 初回の値をキャッシュ（幅自動計算のため）

    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let hmod = GetModuleHandleW(None).expect("GetModuleHandleW");
        let hinst = windows::Win32::Foundation::HINSTANCE(hmod.0);
        let class = w!("EnvmonOverlayPoC");

        let wc = WNDCLASSW {
            lpfnWndProc: Some(wndproc_entry),
            hInstance: hinst,
            lpszClassName: class,
            hCursor: LoadCursorW(windows::Win32::Foundation::HINSTANCE::default(), IDC_ARROW)
                .unwrap_or_default(),
            ..Default::default()
        };
        RegisterClassW(&wc);

        let hwnd = CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            class,
            w!("envmon-overlay"),
            WS_POPUP | WS_VISIBLE | WS_CLIPSIBLINGS,
            0,
            0,
            200,
            34,
            HWND::default(),
            HMENU::default(),
            hinst,
            None,
        )
        .expect("CreateWindowExW");

        apply_all(hwnd);
        let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);

        let (emoji, tcol) = {
            let app = APP.get().unwrap().lock().unwrap();
            (app.cfg.tray_emoji.clone(), app.cfg.tray_color.clone())
        };
        let icon =
            make_emoji_icon(&emoji, parse_color(&tcol, 0x00EC_8D4C)).unwrap_or_default();
        tray_add(hwnd, icon);
        log("tray added, entering loop");

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, HWND::default(), 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}
