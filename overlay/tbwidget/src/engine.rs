//! Win32 エンジン本体。ウィンドウ生成・メッセージ処理・タスクバー追従・ドラッグ・
//! トレイ常駐・メッセージループ。描画は [`crate::render`]、状態は [`crate::APP`]。

use std::iter::once;

use windows::core::PCWSTR;
use windows::Win32::Foundation::{
    COLORREF, ERROR_ALREADY_EXISTS, FALSE, HANDLE, HWND, LPARAM, LRESULT, POINT, RECT, TRUE, WPARAM,
};
use windows::Win32::Foundation::GetLastError;
use windows::Win32::Graphics::Gdi::{
    CreateBitmap, CreateCompatibleDC, CreateDIBSection, CreateFontW, DeleteDC, DeleteObject,
    DrawTextW, GetMonitorInfoW, InvalidateRect, MonitorFromWindow, ScreenToClient, SelectObject,
    SetBkMode, SetTextColor, CreateRoundRectRgn, SetWindowRgn, BITMAPINFO, BITMAPINFOHEADER,
    DIB_RGB_COLORS, DRAW_TEXT_FORMAT, DT_CENTER, DT_SINGLELINE, DT_VCENTER, HBITMAP, HDC, HFONT,
    HGDIOBJ, HRGN, MONITORINFO, MONITOR_DEFAULTTOPRIMARY, TRANSPARENT,
};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Threading::CreateMutexW;
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};
use windows::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NOTIFYICONDATAW,
};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreateIconIndirect, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu,
    DestroyWindow, DispatchMessageW, FindWindowExW, FindWindowW, GetClassNameW,
    GetCursorPos, GetForegroundWindow, GetMessageW, GetWindowRect, KillTimer, LoadCursorW,
    PostQuitMessage, RegisterClassW, SetForegroundWindow, SetLayeredWindowAttributes, SetTimer,
    SetWindowPos, ShowWindow, TrackPopupMenu, TranslateMessage, HICON, HMENU, HTCLIENT,
    HTTRANSPARENT, HWND_TOPMOST, ICONINFO, IDC_ARROW, LWA_ALPHA, LWA_COLORKEY, MF_SEPARATOR,
    MF_STRING, MSG, SWP_NOACTIVATE, SW_HIDE, SW_SHOWNOACTIVATE, TPM_NONOTIFY, TPM_RETURNCMD,
    TPM_RIGHTBUTTON, WM_APP, WM_CONTEXTMENU, WM_CREATE, WM_DESTROY, WM_LBUTTONDOWN, WM_LBUTTONUP,
    WM_MOUSEMOVE, WM_NCHITTEST, WM_PAINT, WM_RBUTTONUP, WM_TIMER, WNDCLASSW, WS_CLIPSIBLINGS,
    WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP, WS_VISIBLE,
};

use crate::render::{self, dpi_scale, KEY};
use crate::schema::{parse_color, Cfg, Pos};
use crate::{cfg_clone, cfg_mtime, cfg_path, load_cfg, log, save_cfg, AppInfo, APP};

const TIMER_ID: usize = 1;
const WM_TRAY: u32 = WM_APP + 1;
const TRAY_UID: u32 = 1;
const ID_REDOCK: usize = 10;
const ID_OPENCFG: usize = 11;
const ID_QUIT: usize = 12;

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(once(0)).collect()
}

// ============================ 幾何 ============================
unsafe fn tray_rect() -> Option<(RECT, i32)> {
    let tray = FindWindowW(windows::core::w!("Shell_TrayWnd"), PCWSTR::null()).unwrap_or_default();
    if tray.0.is_null() {
        return None;
    }
    let mut tr = RECT::default();
    if GetWindowRect(tray, &mut tr).is_err() {
        return None;
    }
    let mut tray_left = tr.right;
    let notify = FindWindowExW(tray, HWND::default(), windows::core::w!("TrayNotifyWnd"), PCWSTR::null())
        .unwrap_or_default();
    if !notify.0.is_null() {
        let mut nr = RECT::default();
        if GetWindowRect(notify, &mut nr).is_ok() {
            tray_left = nr.left;
        }
    }
    Some((tr, tray_left))
}

/// 設定から (x,y,w,h) スクリーン座標。
unsafe fn geometry(hwnd: HWND, cfg: &Cfg) -> (i32, i32, i32, i32) {
    let dpi = dpi_scale(hwnd);
    let sc = |v: i32| v * dpi / 96;
    let w = if cfg.auto_width { render::measure_width(cfg, dpi) } else { sc(cfg.width) };
    if cfg.dock == "free" {
        return (cfg.pos.x, cfg.pos.y, w, render::content_height(hwnd, cfg));
    }
    match tray_rect() {
        Some((tr, tray_left)) => (tray_left - w - sc(cfg.gap), tr.top, w, tr.bottom - tr.top),
        None => (cfg.pos.x, cfg.pos.y, w, render::content_height(hwnd, cfg)),
    }
}

fn grip_hit_width(hwnd: HWND, cfg: &Cfg) -> i32 {
    let dpi = dpi_scale(hwnd);
    (cfg.grip_width + 8) * dpi / 96
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

// ============================ 見た目の適用 ============================
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

// ============================ トレイ ============================
unsafe fn make_font(px: i32, weight: i32, face: &str) -> HFONT {
    let f = wide(face);
    CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, PCWSTR(f.as_ptr()))
}

unsafe fn make_emoji_icon(emoji: &str, color: COLORREF) -> Option<HICON> {
    let size = 32i32;
    let memdc = CreateCompatibleDC(HDC::default());
    if memdc.is_invalid() {
        return None;
    }
    let mut bmi = BITMAPINFO::default();
    bmi.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
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

unsafe fn tray_add(hwnd: HWND, icon: HICON, tip: &str) {
    let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
    nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
    nid.hWnd = hwnd;
    nid.uID = TRAY_UID;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = WM_TRAY;
    nid.hIcon = icon;
    let tipw: Vec<u16> = tip.encode_utf16().collect();
    for (i, c) in tipw.iter().enumerate().take(nid.szTip.len() - 1) {
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
    let _ = AppendMenuW(menu, MF_STRING, ID_REDOCK, windows::core::w!("タスクバーに戻す"));
    let _ = AppendMenuW(menu, MF_STRING, ID_OPENCFG, windows::core::w!("設定ファイルを開く"));
    let _ = AppendMenuW(menu, MF_SEPARATOR, 0, PCWSTR::null());
    let _ = AppendMenuW(menu, MF_STRING, ID_QUIT, windows::core::w!("終了"));
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

                let (on_bar, fx, fy) = match tray_rect() {
                    Some((tr, tray_left)) if pt.y >= tr.top - 4 => {
                        let minx = tr.left + 2;
                        let maxx = (tray_left - w - 2).max(minx);
                        let x = (pt.x - ox).clamp(minx, maxx);
                        (true, x, tr.top)
                    }
                    _ => (false, pt.x - ox, pt.y - oy),
                };

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

            crate::refresh_metrics(); // 値を1回だけ取得してキャッシュ更新

            let (hide_fs, dragging, dock, hidden_state) = {
                let app = APP.get().unwrap().lock().unwrap();
                (app.cfg.hide_on_fullscreen, app.dragging, app.cfg.dock.clone(), app.hidden_state)
            };

            let fs = if hide_fs { is_fullscreen_foreground() } else { false };
            let want_visible = !fs && !hidden_state;
            {
                let mut app = APP.get().unwrap().lock().unwrap();
                app.hidden_fs = fs;
                if want_visible != app.shown {
                    let _ = ShowWindow(hwnd, if want_visible { SW_SHOWNOACTIVATE } else { SW_HIDE });
                    app.shown = want_visible;
                }
            }
            if !want_visible {
                return LRESULT(0);
            }

            if dock == "taskbar" && !dragging {
                let cfg = cfg_clone();
                apply_geometry(hwnd, &cfg);
            }
            let _ = InvalidateRect(hwnd, None, FALSE);
            LRESULT(0)
        }
        WM_PAINT => {
            render::paint(hwnd);
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

/// ウィンドウを生成し、メッセージループに入る。
pub(crate) fn run_window(info: AppInfo) {
    // 二重起動防止。app_id ごとに別ミューテックス。
    let mutex_name = wide(&format!("{}_tbwidget_SingleInstance", info.app_id));
    let _mutex = unsafe {
        let m = CreateMutexW(None, FALSE, PCWSTR(mutex_name.as_ptr())).ok();
        if GetLastError() == ERROR_ALREADY_EXISTS {
            log("already running -> exit");
            return;
        }
        m
    };

    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let hmod = GetModuleHandleW(None).expect("GetModuleHandleW");
        let hinst = windows::Win32::Foundation::HINSTANCE(hmod.0);

        let class_name = wide(&format!("{}_tbwidget", info.app_id));
        let title = wide(&info.window_title);

        let wc = WNDCLASSW {
            lpfnWndProc: Some(wndproc_entry),
            hInstance: hinst,
            lpszClassName: PCWSTR(class_name.as_ptr()),
            hCursor: LoadCursorW(windows::Win32::Foundation::HINSTANCE::default(), IDC_ARROW)
                .unwrap_or_default(),
            ..Default::default()
        };
        RegisterClassW(&wc);

        let hwnd = CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            PCWSTR(class_name.as_ptr()),
            PCWSTR(title.as_ptr()),
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

        let (emoji, tcol, tip) = {
            let app = APP.get().unwrap().lock().unwrap();
            (app.cfg.tray_emoji.clone(), app.cfg.tray_color.clone(), app.cfg.tray_tip.clone())
        };
        let icon = make_emoji_icon(&emoji, parse_color(&tcol, 0x00EC_8D4C)).unwrap_or_default();
        tray_add(hwnd, icon, &tip);
        log("tray added, entering loop");

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, HWND::default(), 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}
