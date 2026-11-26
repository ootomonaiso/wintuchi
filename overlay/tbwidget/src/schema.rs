//! 設定(`config.json`)と表示状態(`state.json`)のスキーマ。
//!
//! エンジンは「何を表示するか」を解釈しない。表示要素は型付きの [`Widget`] 列として
//! 外部プロセスが `state.json` に書く。旧 `{"chips":[...]}` 形式も読めるので後方互換。

use serde::{Deserialize, Serialize};
use windows::Win32::Foundation::COLORREF;

/// free モードの自由配置座標。
#[derive(Serialize, Deserialize, Clone)]
pub struct Pos {
    pub x: i32,
    pub y: i32,
}

/// 見た目・配置の設定。アプリ固有の値は [`Cfg::extra`] に素通しで保持する
/// （前方互換＝未知キーを捨てない）。フォールバック関数はここから読む。
#[derive(Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Cfg {
    pub dock: String, // "taskbar"=透過・トレイ左追従 / "free"=背景付き自由配置
    pub pos: Pos,     // free 位置
    pub gap: i32,     // taskbar: トレイ左端からの間隔(px)
    /// 内容に合わせて幅を自動調整する（true のとき width は無視）
    pub auto_width: bool,
    pub width: i32,
    /// 値の桁数を見込んで幅を固定（桁変化でガタつかないように）。0 で無効。
    pub value_digits: i32,
    pub layout: String, // "inline"=1行 / "stacked"=ラベル+値の2段組み
    pub opacity: u8,    // free モード背景の不透明度 0..255
    pub bg_color: String,
    pub text_color: String,
    pub muted_color: String, // グリップ・ラベル・トラックの色
    pub accent_color: String, // ゲージ/バーの既定フィル色
    pub font_face: String,
    pub value_font_size: i32,
    pub label_font_size: i32,
    pub font_weight: i32,
    pub corner_radius: i32, // free モードの角丸
    pub align: String,      // inline: left|center|right
    pub grip_width: i32,
    pub update_interval_ms: u32,
    pub separator: String, // inline 要素間の間隔を決める基準文字列
    pub hide_on_fullscreen: bool,
    pub tray_emoji: String,
    pub tray_color: String,
    pub tray_tip: String, // トレイアイコンのツールチップ
    /// アプリ固有の追加設定（例: EnvMonitor の show_cpu / cpu_label 等）。
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
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
            accent_color: "#4C8DEC".into(),
            font_face: "Segoe UI".into(),
            value_font_size: 13,
            label_font_size: 9,
            font_weight: 600,
            corner_radius: 8,
            align: "center".into(),
            grip_width: 12,
            update_interval_ms: 1000,
            separator: "   ".into(),
            hide_on_fullscreen: true,
            tray_emoji: "📊".into(),
            tray_color: "#4C8DEC".into(),
            tray_tip: "tbwidget".into(),
            extra: serde_json::Map::new(),
        }
    }
}

impl Cfg {
    /// extra から bool を読む（未指定は default）。
    pub fn extra_bool(&self, key: &str, default: bool) -> bool {
        self.extra.get(key).and_then(|v| v.as_bool()).unwrap_or(default)
    }
    /// extra から文字列を読む（未指定は default）。
    pub fn extra_str(&self, key: &str, default: &str) -> String {
        self.extra
            .get(key)
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| default.to_string())
    }
}

/// 表示要素（型付き）。`state.json` の `widgets` 配列に並ぶ。
///
/// `fg`/`track` は色解決済みの `#RRGGBB`。色の判断は書き手の責任。
#[derive(Clone, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Widget {
    /// 任意テキスト。
    Text {
        #[serde(default)]
        value: String,
        #[serde(default)]
        fg: String,
    },
    /// ラベル＋値（従来のチップ）。inline は "ラベル 値"、stacked は上下2段。
    Chip {
        #[serde(default)]
        label: String,
        #[serde(default)]
        value: String,
        #[serde(default)]
        fg: String,
    },
    /// 値＋充填バー（割合 0.0..1.0）。
    Gauge {
        #[serde(default)]
        label: String,
        #[serde(default)]
        value: String,
        #[serde(default)]
        ratio: f32,
        #[serde(default)]
        fg: String,
        #[serde(default)]
        track: String,
    },
    /// 単独の水平バー（割合 0.0..1.0）。
    Bar {
        #[serde(default)]
        ratio: f32,
        #[serde(default)]
        fg: String,
        #[serde(default)]
        track: String,
    },
    /// 状態ドット（小さな丸）。
    Dot {
        #[serde(default)]
        fg: String,
    },
    /// 絵文字/記号1文字。
    Icon {
        #[serde(default)]
        glyph: String,
        #[serde(default)]
        fg: String,
    },
    /// 縦の区切り線。
    Sep,
}

/// 旧スキーマ `{"chips":[{label,value,fg}]}` の要素。
#[derive(Deserialize)]
pub struct ChipIn {
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub value: String,
    #[serde(default)]
    pub fg: String,
}

/// `state.json` 全体。`widgets`（新）と `chips`（旧・後方互換）の両対応。
#[derive(Deserialize)]
pub struct StateIn {
    /// 表示/非表示。省略時は表示。
    #[serde(default)]
    pub visible: Option<bool>,
    /// 配置の上書き（"taskbar"/"free"）。省略時は config に従う。
    #[serde(default)]
    pub dock: Option<String>,
    /// free 背景の不透明度上書き 0.0..1.0。省略時は config。
    #[serde(default)]
    pub opacity: Option<f32>,
    #[serde(default)]
    pub widgets: Vec<Widget>,
    /// 旧形式。`widgets` が空のときだけ採用する。
    #[serde(default)]
    pub chips: Vec<ChipIn>,
}

impl StateIn {
    /// `widgets` を正規化して返す（旧 `chips` は Chip ウィジェットへ変換）。
    pub fn into_widgets(self) -> Vec<Widget> {
        if !self.widgets.is_empty() {
            return self.widgets;
        }
        self.chips
            .into_iter()
            .map(|c| Widget::Chip { label: c.label, value: c.value, fg: c.fg })
            .collect()
    }
}

/// "#RRGGBB" を GDI の COLORREF(0x00BBGGRR) へ。失敗時は default をそのまま返す。
pub fn parse_color(s: &str, default: u32) -> COLORREF {
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

/// fg が空なら fallback 色、そうでなければ fg をパース。
pub fn color_or(fg: &str, fallback: COLORREF) -> COLORREF {
    if fg.trim().is_empty() {
        fallback
    } else {
        parse_color(fg, fallback.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_typed_widgets() {
        let s = r##"{"visible":true,"widgets":[
            {"type":"chip","label":"A","value":"35.2℃","fg":"#E24C4C"},
            {"type":"gauge","value":"62%","ratio":0.62},
            {"type":"bar","ratio":0.8},
            {"type":"dot","fg":"#3BA55D"},
            {"type":"icon","glyph":"⚡"},
            {"type":"text","value":"OK"},
            {"type":"sep"}
        ]}"##;
        let st: StateIn = serde_json::from_str(s).unwrap();
        assert_eq!(st.visible, Some(true));
        let w = st.into_widgets();
        assert_eq!(w.len(), 7);
        assert!(matches!(w[0], Widget::Chip { .. }));
        assert!(matches!(w[6], Widget::Sep));
    }

    #[test]
    fn legacy_chips_still_parse() {
        let s = r##"{"chips":[{"label":"CPU","value":"12%","fg":"#3BA55D"}]}"##;
        let st: StateIn = serde_json::from_str(s).unwrap();
        let w = st.into_widgets();
        assert_eq!(w.len(), 1);
        match &w[0] {
            Widget::Chip { label, value, fg } => {
                assert_eq!(label, "CPU");
                assert_eq!(value, "12%");
                assert_eq!(fg, "#3BA55D");
            }
            _ => panic!("expected chip"),
        }
    }

    #[test]
    fn widgets_take_precedence_over_chips() {
        let s = r##"{"widgets":[{"type":"text","value":"x"}],"chips":[{"value":"y"}]}"##;
        let w: Vec<Widget> = serde_json::from_str::<StateIn>(s).unwrap().into_widgets();
        assert_eq!(w.len(), 1);
        assert!(matches!(w[0], Widget::Text { .. }));
    }

    #[test]
    fn config_extra_round_trips() {
        let mut cfg = Cfg::default();
        cfg.extra.insert("show_cpu".into(), serde_json::Value::Bool(false));
        cfg.extra.insert("cpu_label".into(), serde_json::Value::String("プロセッサ".into()));
        let s = serde_json::to_string(&cfg).unwrap();
        let back: Cfg = serde_json::from_str(&s).unwrap();
        assert!(!back.extra_bool("show_cpu", true));
        assert_eq!(back.extra_str("cpu_label", "CPU"), "プロセッサ");
        assert_eq!(back.extra_str("missing", "dflt"), "dflt");
    }

    #[test]
    fn color_parse_and_fallback() {
        assert_eq!(parse_color("#FF0000", 0).0, 0x0000_00FF); // BGR
        assert_eq!(parse_color("bad", 0x123).0, 0x123);
        assert_eq!(color_or("", COLORREF(0x42)).0, 0x42);
        assert_eq!(color_or("#000000", COLORREF(0x42)).0, 0x0);
    }
}
