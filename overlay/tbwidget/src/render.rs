//! 描画。型付き [`Widget`] 列を、幅測定とペイントが一致するフローレイアウトで描く。
//!
//! - `inline`  … 1 行に左→右。要素間は separator 幅ぶんの間隔。
//! - `stacked` … 要素ごとに等幅の列。Chip/Gauge はラベル(上)＋値(下)の 2 段。

use crate::schema::{color_or, parse_color, Cfg, Widget};
use crate::{cached_widgets, cfg_clone};
use windows::core::PCWSTR;
use windows::Win32::Foundation::{COLORREF, RECT};
use windows::Win32::Graphics::Gdi::{
    BeginPaint, CreateCompatibleDC, CreateFontW, CreateSolidBrush, DeleteDC, DeleteObject,
    DrawTextW, Ellipse, EndPaint, FillRect, GetStockObject, SelectObject, SetBkMode,
    SetTextColor, DRAW_TEXT_FORMAT, DT_BOTTOM, DT_CALCRECT, DT_CENTER, DT_LEFT,
    DT_SINGLELINE, DT_TOP, DT_VCENTER, HDC, HFONT, HGDIOBJ, NULL_PEN, PAINTSTRUCT, TRANSPARENT,
};
use windows::Win32::UI::HiDpi::GetDpiForWindow;
use windows::Win32::UI::WindowsAndMessaging::GetClientRect;
use windows::Win32::Foundation::HWND;

/// taskbar(透過)モードのキー色。
pub const KEY: COLORREF = COLORREF(0x0001_0101);

pub fn dpi_scale(hwnd: HWND) -> i32 {
    let d = unsafe { GetDpiForWindow(hwnd) } as i32;
    if d <= 0 {
        96
    } else {
        d
    }
}

unsafe fn make_font(px: i32, weight: i32, face: &str) -> HFONT {
    let f: Vec<u16> = face.encode_utf16().chain(std::iter::once(0)).collect();
    CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, PCWSTR(f.as_ptr()))
}

/// ラベル用・値用のフォントを束ねる。使用後は [`Fonts::free`]。
struct Fonts {
    label: HFONT,
    value: HFONT,
}
impl Fonts {
    unsafe fn new(cfg: &Cfg, dpi: i32) -> Fonts {
        let sc = |v: i32| v * dpi / 96;
        Fonts {
            label: make_font(sc(cfg.label_font_size), 400, &cfg.font_face),
            value: make_font(sc(cfg.value_font_size), cfg.font_weight, &cfg.font_face),
        }
    }
    unsafe fn free(&self) {
        let _ = DeleteObject(HGDIOBJ(self.label.0));
        let _ = DeleteObject(HGDIOBJ(self.value.0));
    }
}

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

unsafe fn draw_text(hdc: HDC, text: &str, rc: &RECT, fmt: DRAW_TEXT_FORMAT) {
    if text.is_empty() {
        return;
    }
    let mut wt: Vec<u16> = text.encode_utf16().collect();
    let mut r = *rc;
    DrawTextW(hdc, &mut wt, &mut r, fmt);
}

/// 値の桁テンプレ。先頭の数字部分を "0"*digits に、単位は保持（"27.3℃"->"000℃"）。
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

/// 値の実測と桁テンプレ実測の大きい方（桁変化で幅が揺れないように確保）。
unsafe fn val_reserved(memdc: HDC, f: HFONT, cfg: &Cfg, v: &str) -> i32 {
    let a = text_w(memdc, f, v);
    match value_template(v, cfg.value_digits) {
        Some(t) => a.max(text_w(memdc, f, &t)),
        None => a,
    }
}

/// 1 要素の占有幅（content 内）。layout により Chip/Gauge の測り方が変わる。
unsafe fn measure_widget(memdc: HDC, fonts: &Fonts, cfg: &Cfg, dpi: i32, w: &Widget) -> i32 {
    let sc = |v: i32| v * dpi / 96;
    let stacked = cfg.layout == "stacked";
    match w {
        Widget::Text { value, .. } => text_w(memdc, fonts.value, value),
        Widget::Icon { glyph, .. } => text_w(memdc, fonts.value, glyph).max(sc(14)),
        Widget::Dot { .. } => sc(12),
        Widget::Sep => sc(9),
        Widget::Bar { .. } => sc(44),
        Widget::Chip { label, value, .. } => {
            if stacked {
                text_w(memdc, fonts.label, label).max(val_reserved(memdc, fonts.value, cfg, value))
            } else {
                text_w(memdc, fonts.value, &format!("{} ", label))
                    + val_reserved(memdc, fonts.value, cfg, value)
            }
        }
        Widget::Gauge { label, value, .. } => {
            let base = if stacked {
                text_w(memdc, fonts.label, label).max(val_reserved(memdc, fonts.value, cfg, value))
            } else {
                let l = if label.is_empty() { 0 } else { text_w(memdc, fonts.value, &format!("{} ", label)) };
                l + val_reserved(memdc, fonts.value, cfg, value)
            };
            base.max(sc(40))
        }
    }
}

/// inline 要素間の間隔（separator の文字幅を基準に）。
unsafe fn gap_w(memdc: HDC, fonts: &Fonts, cfg: &Cfg) -> i32 {
    text_w(memdc, fonts.value, &cfg.separator)
}

/// 内容に合わせた全体幅（px）。グリップ＋余白込み。
pub unsafe fn measure_width(cfg: &Cfg, dpi: i32) -> i32 {
    let sc = |v: i32| v * dpi / 96;
    let items = cached_widgets();
    let memdc = CreateCompatibleDC(HDC::default());
    let fonts = Fonts::new(cfg, dpi);

    let content = if cfg.layout == "stacked" {
        items
            .iter()
            .map(|w| measure_widget(memdc, &fonts, cfg, dpi, w) + sc(16))
            .sum::<i32>()
    } else {
        let gap = gap_w(memdc, &fonts, cfg);
        let mut total = 0;
        for (i, w) in items.iter().enumerate() {
            if i > 0 {
                total += gap;
            }
            total += measure_widget(memdc, &fonts, cfg, dpi, w);
        }
        total
    };

    fonts.free();
    let _ = DeleteDC(memdc);
    let total = sc(cfg.grip_width) + sc(6) + content + sc(14);
    total.max(sc(60))
}

pub fn content_height(hwnd: HWND, cfg: &Cfg) -> i32 {
    let dpi = dpi_scale(hwnd);
    let sc = |v: i32| v * dpi / 96;
    if cfg.layout == "stacked" {
        sc(cfg.label_font_size) + sc(cfg.value_font_size) + sc(14)
    } else {
        sc(cfg.value_font_size) + sc(16)
    }
}

/// 塗りブラシでドット（丸）を描く（枠なし）。
unsafe fn fill_ellipse(hdc: HDC, l: i32, t: i32, r: i32, b: i32, col: COLORREF) {
    let brush = CreateSolidBrush(col);
    let old_b = SelectObject(hdc, HGDIOBJ(brush.0));
    let old_p = SelectObject(hdc, GetStockObject(NULL_PEN));
    let _ = Ellipse(hdc, l, t, r, b);
    SelectObject(hdc, old_b);
    SelectObject(hdc, old_p);
    let _ = DeleteObject(HGDIOBJ(brush.0));
}

unsafe fn fill_rect(hdc: HDC, r: &RECT, col: COLORREF) {
    let brush = CreateSolidBrush(col);
    FillRect(hdc, r, brush);
    let _ = DeleteObject(HGDIOBJ(brush.0));
}

struct Palette {
    text: COLORREF,
    muted: COLORREF,
    accent: COLORREF,
}

/// 1 要素をセル矩形へ描く。
unsafe fn paint_widget(
    hdc: HDC,
    cell: &RECT,
    fonts: &Fonts,
    cfg: &Cfg,
    dpi: i32,
    pal: &Palette,
    w: &Widget,
) {
    let sc = |v: i32| v * dpi / 96;
    let stacked = cfg.layout == "stacked";
    let mid = cell.top + (cell.bottom - cell.top) * 42 / 100;

    // Chip/Gauge のラベル＋値を描く共通処理。
    let draw_label_value = |label: &str, value: &str, vcol: COLORREF| {
        if stacked {
            let top = RECT { top: cell.top + sc(2), bottom: mid, ..*cell };
            let bot = RECT { top: mid, bottom: cell.bottom - sc(2), ..*cell };
            let old = SelectObject(hdc, HGDIOBJ(fonts.label.0));
            SetTextColor(hdc, pal.muted);
            draw_text(hdc, label, &top, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_BOTTOM.0 | DT_SINGLELINE.0));
            SelectObject(hdc, HGDIOBJ(fonts.value.0));
            SetTextColor(hdc, vcol);
            draw_text(hdc, value, &bot, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_TOP.0 | DT_SINGLELINE.0));
            SelectObject(hdc, old);
        } else {
            let old = SelectObject(hdc, HGDIOBJ(fonts.value.0));
            let line = if label.is_empty() {
                value.to_string()
            } else {
                format!("{} {}", label, value)
            };
            // ラベルは muted、値は vcol。簡便のため一体描画（色は値色）。ラベルのみ別色にしたい
            // 場合は stacked を使う想定。
            SetTextColor(hdc, if label.is_empty() { vcol } else { pal.text });
            if !label.is_empty() {
                // "ラベル " を muted で、続けて値を vcol で。
                let mut r = *cell;
                SetTextColor(hdc, pal.muted);
                let lead = format!("{} ", label);
                draw_text(hdc, &lead, &r, DRAW_TEXT_FORMAT(DT_LEFT.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
                let lw = text_w(hdc, fonts.value, &lead);
                r.left += lw;
                SetTextColor(hdc, vcol);
                draw_text(hdc, value, &r, DRAW_TEXT_FORMAT(DT_LEFT.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
            } else {
                draw_text(hdc, &line, cell, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
            }
            SelectObject(hdc, old);
        }
    };

    match w {
        Widget::Text { value, fg } => {
            let col = color_or(fg, pal.text);
            let old = SelectObject(hdc, HGDIOBJ(fonts.value.0));
            SetTextColor(hdc, col);
            draw_text(hdc, value, cell, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
            SelectObject(hdc, old);
        }
        Widget::Icon { glyph, fg } => {
            let col = color_or(fg, pal.text);
            let old = SelectObject(hdc, HGDIOBJ(fonts.value.0));
            SetTextColor(hdc, col);
            draw_text(hdc, glyph, cell, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
            SelectObject(hdc, old);
        }
        Widget::Chip { label, value, fg } => {
            draw_label_value(label, value, color_or(fg, pal.text));
        }
        Widget::Gauge { label, value, ratio, fg, track } => {
            // 下端に細い充填バー、上に label/value。
            let barh = sc(3);
            let bar_top = cell.bottom - barh - sc(1);
            let pad = sc(2);
            let full = RECT { left: cell.left + pad, top: bar_top, right: cell.right - pad, bottom: bar_top + barh };
            let tcol = color_or(track, pal.muted);
            fill_rect(hdc, &full, tcol);
            let rr = ratio.clamp(0.0, 1.0);
            let fw = ((full.right - full.left) as f32 * rr) as i32;
            if fw > 0 {
                let fill = RECT { right: full.left + fw, ..full };
                fill_rect(hdc, &fill, color_or(fg, pal.accent));
            }
            // テキストはバーの上側に収める。
            let text_cell = RECT { bottom: bar_top - sc(1), ..*cell };
            let saved = cell;
            let _ = saved;
            // draw_label_value は cell を使うので一時差し替え。
            let vcol = color_or(fg, pal.text);
            if stacked {
                let tmid = text_cell.top + (text_cell.bottom - text_cell.top) * 45 / 100;
                let top = RECT { top: text_cell.top + sc(1), bottom: tmid, ..text_cell };
                let bot = RECT { top: tmid, bottom: text_cell.bottom, ..text_cell };
                let old = SelectObject(hdc, HGDIOBJ(fonts.label.0));
                SetTextColor(hdc, pal.muted);
                draw_text(hdc, label, &top, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_BOTTOM.0 | DT_SINGLELINE.0));
                SelectObject(hdc, HGDIOBJ(fonts.value.0));
                SetTextColor(hdc, vcol);
                draw_text(hdc, value, &bot, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_TOP.0 | DT_SINGLELINE.0));
                SelectObject(hdc, old);
            } else {
                let old = SelectObject(hdc, HGDIOBJ(fonts.value.0));
                SetTextColor(hdc, vcol);
                let line = if label.is_empty() { value.clone() } else { format!("{} {}", label, value) };
                draw_text(hdc, &line, &text_cell, DRAW_TEXT_FORMAT(DT_CENTER.0 | DT_VCENTER.0 | DT_SINGLELINE.0));
                SelectObject(hdc, old);
            }
        }
        Widget::Bar { ratio, fg, track } => {
            let barh = sc(6);
            let pad = sc(2);
            let cy = (cell.top + cell.bottom) / 2;
            let full = RECT { left: cell.left + pad, top: cy - barh / 2, right: cell.right - pad, bottom: cy + barh / 2 };
            fill_rect(hdc, &full, color_or(track, pal.muted));
            let rr = ratio.clamp(0.0, 1.0);
            let fw = ((full.right - full.left) as f32 * rr) as i32;
            if fw > 0 {
                let fill = RECT { right: full.left + fw, ..full };
                fill_rect(hdc, &fill, color_or(fg, pal.accent));
            }
        }
        Widget::Dot { fg } => {
            let col = color_or(fg, pal.accent);
            let d = sc(8);
            let cx = (cell.left + cell.right) / 2;
            let cy = (cell.top + cell.bottom) / 2;
            fill_ellipse(hdc, cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2, col);
        }
        Widget::Sep => {
            let cx = (cell.left + cell.right) / 2;
            let h = cell.bottom - cell.top;
            let r = RECT {
                left: cx,
                top: cell.top + h * 22 / 100,
                right: cx + sc(1).max(1),
                bottom: cell.bottom - h * 22 / 100,
            };
            fill_rect(hdc, &r, pal.muted);
        }
    }
}

/// ウィンドウ全体を描く（背景・グリップ・要素列）。
pub unsafe fn paint(hwnd: HWND) {
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
    fill_rect(hdc, &rc, bg);

    SetBkMode(hdc, TRANSPARENT);
    let pal = Palette {
        text: parse_color(&cfg.text_color, 0x00EF_EBE9),
        muted: parse_color(&cfg.muted_color, 0x00A0_938A),
        accent: parse_color(&cfg.accent_color, 0x00EC_8D4C),
    };

    // グリップ（掴む部分）を左に。縦バー "|" を muted 色で。
    let grip_w = sc(cfg.grip_width);
    let h = rc.bottom - rc.top;
    let bar_h = (h * 55 / 100).max(sc(10));
    let bw = sc(2).max(2);
    let cx = grip_w / 2;
    let gr = RECT {
        left: cx - bw / 2,
        top: (h - bar_h) / 2,
        right: cx - bw / 2 + bw,
        bottom: (h + bar_h) / 2,
    };
    fill_rect(hdc, &gr, pal.muted);

    // 内容領域（グリップの右）
    let content = RECT { left: rc.left + grip_w, ..rc };
    let items = cached_widgets();
    let fonts = Fonts::new(&cfg, dpi);
    let memdc = CreateCompatibleDC(HDC::default());

    if cfg.layout == "stacked" {
        let n = items.len().max(1) as i32;
        let cw = (content.right - content.left) / n;
        for (i, w) in items.iter().enumerate() {
            let x0 = content.left + i as i32 * cw;
            let cell = RECT { left: x0, right: x0 + cw, ..content };
            paint_widget(hdc, &cell, &fonts, &cfg, dpi, &pal, w);
        }
    } else {
        let gap = gap_w(memdc, &fonts, &cfg);
        let mut x = content.left + sc(2);
        for (i, w) in items.iter().enumerate() {
            if i > 0 {
                x += gap;
            }
            let ww = measure_widget(memdc, &fonts, &cfg, dpi, w);
            let cell = RECT { left: x, right: x + ww, ..content };
            paint_widget(hdc, &cell, &fonts, &cfg, dpi, &pal, w);
            x += ww;
        }
    }

    let _ = DeleteDC(memdc);
    fonts.free();
    let _ = EndPaint(hwnd, &ps);
}
