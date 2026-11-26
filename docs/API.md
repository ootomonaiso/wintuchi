# API リファレンス（開発者向け）

このドキュメントは EnvMonitor が外部に公開する2つの API を正確に記述します。

1. **ローカル設定 HTTP API**（`envmon/httpconfig.py`）— 設定ダッシュボード(`settings.html`)が話す相手。
2. **`tbwidget` Rust 公開API**（`overlay/tbwidget/src/lib.rs`）— 他アプリが埋め込む際に呼ぶ相手。

全体像・データフローは [`ARCHITECTURE.md`](ARCHITECTURE.md)、モジュール単位の責務は
[`MODULES.md`](MODULES.md)、overlay のユーザー向け操作・`state.json`/`config.json` の
全項目は [`../overlay/README.md`](../overlay/README.md) を参照してください。本ドキュメントは
両者の**呼び出しインターフェース**（エンドポイント・関数シグネチャ・入出力の形）に特化します。

---

## 1. ローカル設定 HTTP API（`envmon/httpconfig.py`）

### 1.1 概要

- **ベースURL**: `http://127.0.0.1:<ephemeral port>/`（`ThreadingHTTPServer` が起動時にポート
  `0` でバインドし、OS が空きポートを割り当てる。固定ポートではない）。
- **起動**: `App` 起動時に `ConfigServer.start()` が別スレッドで `serve_forever()`。トレイ
  「設定…」は `webbrowser.open(ConfigServer.url)` でこの URL をブラウザに渡すだけ。
- **認証**: 全エンドポイント共通でクエリパラメータ `t=<token>` が必須。`token` はプロセス
  起動毎に `secrets.token_urlsafe(16)` で生成され、`secrets.compare_digest` でタイミング
  攻撃耐性のある比較を行う。欠落・不一致は **常に `403`**（プレーンテキスト `forbidden`、
  `Content-Type` ヘッダ無し）。
- **共通レスポンスヘッダ**: JSON/HTML レスポンスはいずれも `Cache-Control: no-store`。
- **未知のパス**: `404`（本文無し）。

### 1.2 エンドポイント一覧

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `GET` | `/` | 必須 | `settings.html` を配信（token/プリセットを注入） |
| `GET` | `/config` | 必須 | 現在の `config.json` のスナップショットを返す |
| `POST` | `/config` | 必須 | 検証・正規化して保存し、即時反映 |
| `GET` | `/status` | 必須 | 接続状態・既知の部屋一覧（ダッシュボードのバナー用） |
| `GET` | `/test` | 必須 | サーバ側で指定 URL を叩いて疎通確認 |
| その他 | — | — | `404` |

### 1.3 `GET /`

**クエリ**: `t` (必須)

設定ダッシュボード本体。`settings.html` を読み、プレースホルダ `/*__BOOTSTRAP__*/` を
以下の JSON で置換してから返す:

```json
{
  "token": "<起動毎トークン>",
  "roomPresets": [
    {"name": "快適な居室（人がいる部屋）", "temp": [18.0, 28.0], "humid": [30.0, 70.0], "hint": "..."},
    {"name": "サーバー室・機器まわり", "temp": [10.0, 30.0], "humid": [20.0, 70.0], "hint": "..."}
  ],
  "labelPresets": {
    "やわらかめ": {"ok": "正常", "warn": "気になる", "critical": "要チェック", "stale": "応答なし"},
    "ふつう":   {"ok": "正常", "warn": "注意",     "critical": "要確認",   "stale": "応答なし"},
    "きっちり": {"ok": "正常", "warn": "警告",     "critical": "異常",     "stale": "停止"},
    "英語":     {"ok": "OK",   "warn": "Warn",     "critical": "Alert",   "stale": "No data"}
  }
}
```

- `roomPresets` は `envmon/presets.py` の `ROOM_PRESETS`（`[(name, {...}), ...]` を
  `[{"name": n, **d}]` へ展開したもの）。
- `labelPresets` は `presets.LABEL_PRESETS` そのもの。
- HTML は `window.__BOOT__ = <上記JSON>;` という形でページ内に埋め込まれる（ブラウザ側の
  JS がこれを読んで初期描画する）。

**失敗時**: `settings.html` が読めない場合 → `500` `{"error": "settings.html not found"}`。

### 1.4 `GET /config`

**クエリ**: `t` (必須)

**レスポンス** `200`: `config.json` の完全なスナップショット（`Config.snapshot()` の
deep copy）。`DEFAULT_CONFIG` と同形で、全キーが常に存在する:

```json
{
  "url": "http://localhost/env1.php",
  "poll_interval_sec": 30,
  "request_timeout_sec": 10,
  "teams_webhook_url": "",
  "cooldown_minutes": 15,
  "quiet_hours": {"enabled": false, "start": "22:00", "end": "07:00"},
  "stale_minutes": 10,
  "run_at_startup": false,
  "labels": {"ok": "正常", "warn": "注意", "critical": "要確認", "stale": "応答なし"},
  "colors": {"ok": "#3BA55D", "warn": "#E8A33D", "critical": "#E24C4C", "stale": "#8A8A8A", "lux": "#4A90D9"},
  "hysteresis": {"temp": 0.5, "humid": 2.0},
  "sensors": {},
  "rooms": {
    "会議室A": {
      "temp": {"min": 10.0, "max": 30.0},
      "humid": {"min": 30.0, "max": 70.0},
      "lux_gate": {"mode": "off", "value": 50.0},
      "channels": {"toast": true, "teams": true},
      "stale_enabled": true
    }
  },
  "widget": {"enabled": false, "items": [], "dock": "taskbar", "pos": null, "taskbar_gap": 8, "opacity": 0.96},
  "overlay": {"enabled": true, "exe": ""}
}
```

`sensors` はここでは常に `{}` 相当の読取キャッシュ扱い（権威は `sensors.json`、このAPIは
書き換えない）。

### 1.5 `POST /config`

**クエリ**: `t` (必須)
**リクエストボディ**: `Content-Type` 任意（本文のみ UTF-8 JSON として解釈）。上記
`GET /config` と同形の JSON（部分指定も可 — `envmon/validate.normalize()` が
`DEFAULT_CONFIG` に deep-merge するため欠損キーは既定で補われる）。

**処理順**: `json.loads` → `validate.normalize(data)` → `(clean, warnings)` →
`on_apply(clean)`（= `App._apply_web_config`: `Config.replace()` → `poll_now()` →
`overlay.apply_enabled()`）。

**レスポンス**:

| 状況 | コード | ボディ |
|---|---|---|
| 正常 | `200` | `{"ok": true, "warnings": ["<補正の説明文>", ...]}`（`warnings` は型/範囲補正があった項目の日本語説明。無ければ空配列） |
| ボディが不正な JSON | `400` | `{"ok": false, "error": "不正なJSON: <例外メッセージ>"}` |
| `on_apply` 内で例外 | `500` | `{"ok": false, "error": "適用に失敗しました"}` |

`warnings` に入る代表的な文言の例: `部屋「<name>」のtemp: 下限>上限のため入れ替えました`、
`部屋「<name>」の照度ゲート mode が不正(<v>)→off`、`状態色「<k>」が不正な値(<v>)のため既定に戻しました`。

### 1.6 `GET /status`

**クエリ**: `t` (必須)

**レスポンス** `200`:

```json
{
  "last_ok": "12:56:00",
  "error": null,
  "rooms": ["会議室A", "倉庫", "応接室"]
}
```

- `last_ok` / `error`: 直近のポーリング成功時刻(`HH:MM:SS`)／直近エラーの文字列表現。
  いずれもポーリング未実行なら `null`。
- `rooms`: `config.rooms` のキー ∪ `config.sensors` の値 ∪ 実行時に観測済みの部屋名
  （ソート済み・重複無し）。

### 1.7 `GET /test`

**クエリ**: `t` (必須), `url` (必須・空文字は下記参照), `timeout`（任意・秒、既定 `5`、
下限 `1`。`int(float(...))` でパースし不正値は既定にフォールバック）

サーバ側（Python プロセス）が `requests.get(url, timeout=timeout)` を実行し、
`poller.parse_records` → `poller.latest_per_sensor` で実データとして解釈できるか確認する
（ブラウザから直接 fetch すると CORS/混在コンテンツで失敗するため、サーバ経由で代行する）。

**レスポンス**（常に `200`。成否は `ok` フィールドで表現）:

| 状況 | ボディ |
|---|---|
| `url` が空 | `{"ok": false, "msg": "URL を入力してください"}` |
| 接続成功・データ有り | `{"ok": true, "n": <センサ台数>, "msg": "接続OK — <n> 台のセンサを受信しました"}` |
| 接続成功・データ空 | `{"ok": false, "n": 0, "msg": "つながりましたが、データが空でした"}` |
| 例外（接続失敗・タイムアウト・パース失敗等） | `{"ok": false, "msg": "つながりません（<例外先頭60文字>）"}` |

---

## 2. `tbwidget` Rust 公開API（`overlay/tbwidget/src/lib.rs`）

他プロセス（`envmon-overlay` も含む）がこのエンジンを埋め込む際に使う、crate の公開面
（`pub` シンボル）をすべて列挙する。**値を決める責任は呼び出し側**で、このエンジンは
`AppInfo` で渡された設定・パス・フォールバックに従って `state.json` を描くだけ。

### 2.1 公開シンボル一覧

```rust
pub use paths::{default_base_dir, Paths};
pub use schema::{color_or, parse_color, Cfg, Pos, StateIn, Widget};

pub type FallbackFn = fn(&Cfg) -> Vec<Widget>;
pub struct AppInfo { /* §2.2 */ }
pub fn run(info: AppInfo);
```

### 2.2 `AppInfo` — アプリ定義（ビルダ）

`AppInfo::new(app_id)` で作り、以下のビルダメソッドをチェーンして肉付けする
（いずれも `self` を消費して返す）。

| メソッド | シグネチャ | 既定値 | 効果 |
|---|---|---|---|
| `new` | `fn new(app_id: impl Into<String>) -> Self` | — | 必須。`app_id` が `window_title` の既定にもなる |
| `with_base_dir` | `fn with_base_dir(self, dir: impl Into<PathBuf>) -> Self` | `%APPDATA%\{app_id}` | `config`/`state`/`log` の格納先ディレクトリ |
| `with_file_names` | `fn with_file_names(self, config: &str, state: &str, log: &str) -> Self` | `"config.json"`/`"state.json"`/`"overlay.log"` | `base_dir` 配下のファイル名 |
| `with_config_path` | `fn with_config_path(self, p: impl Into<PathBuf>) -> Self` | なし | `config.json` の絶対パスを個別指定（`base_dir`/`config_name` を上書き） |
| `with_state_path` | `fn with_state_path(self, p: impl Into<PathBuf>) -> Self` | なし | `state.json` の絶対パスを個別指定 |
| `with_log_path` | `fn with_log_path(self, p: impl Into<PathBuf>) -> Self` | なし | ログの絶対パスを個別指定 |
| `with_title` | `fn with_title(self, t: impl Into<String>) -> Self` | `app_id` | ウィンドウタイトル（内部用。画面には出ない） |
| `with_tray` | `fn with_tray(self, tip: &str, emoji: &str, color: &str) -> Self` | `Cfg::default()` の値 | `defaults.tray_tip`/`tray_emoji`/`tray_color` を上書き |
| `with_defaults` | `fn with_defaults(self, cfg: Cfg) -> Self` | `Cfg::default()` | `config.json` 初回生成時の既定値一式を丸ごと差し替え |
| `with_fallback` | `fn with_fallback(self, f: FallbackFn) -> Self` | `None` | `state.json` が無い/空/壊れている時に呼ぶ関数を登録 |

個別パス指定（`with_*_path`）は `with_base_dir`/`with_file_names` より**優先**される
（`Paths::resolve` が個別指定→base_dir+ファイル名の順で解決）。

**パス解決の優先順位**（`Paths::resolve`、ファイルごとに独立）:
1. `with_config_path`/`with_state_path`/`with_log_path` で個別指定したパス
2. `with_base_dir` で指定したディレクトリ ＋ `with_file_names` のファイル名（既定
   `config.json`/`state.json`/`overlay.log`）
3. いずれも無指定なら `%APPDATA%\{app_id}\{既定ファイル名}`（`default_base_dir`）

### 2.3 `FallbackFn`

```rust
pub type FallbackFn = fn(&Cfg) -> Vec<Widget>;
```

`state.json` が存在しない・空・パース失敗のときに1回呼ばれ、戻り値の `Widget` 列を
代わりに描画する（`envmon-overlay` では内蔵 CPU/MEM 表示に使う）。普通の `fn` ポインタ
なのでキャプチャ付きクロージャは渡せない — 必要な値は `Cfg`（`extra` 経由のアプリ固有
キーを含む）から読む。

### 2.4 `run(info: AppInfo)`

```rust
pub fn run(info: AppInfo);
```

- パス解決 → 旧ログ削除 → グローバル状態 `App`（`OnceLock<Mutex<App>>`）を初期化
  → `config.json` を読込（無ければ `defaults` を書き出して使用）→ 初回 `state.json` 読込
  → `engine::run_window(info)` で Win32 メッセージループに入る。
- **戻らない**（プロセス終了まで内部でブロックする）。呼び出し側は別プロセスとして
  spawn するか、このバイナリ自体をアプリの `main()` とする想定。
- **多重起動不可**: app-id ごとの名前付きミューテックスで単一起動に制限される
  （`overlay/README.md` §2）。
- `run` を同一プロセス内で複数回・多重に呼ぶことは想定されていない（`APP` は
  `OnceLock` で1個のみ）。

### 2.5 `Cfg` — 設定（`config.json` の Rust 側表現）

`#[serde(default)]` 付き構造体。JSON との対応・既定値・意味は
[`../overlay/README.md`](../overlay/README.md) §7 の表が正（本APIリファレンスでは
型のみ要約）。

| フィールド | 型 | 既定値 |
|---|---|---|
| `dock` | `String`(`"taskbar"`\|`"free"`) | `"taskbar"` |
| `pos` | `Pos { x: i32, y: i32 }` | `{1500, 1020}` |
| `gap` | `i32` | `8` |
| `auto_width` | `bool` | `true` |
| `width` | `i32` | `200` |
| `value_digits` | `i32` | `3` |
| `layout` | `String`(`"inline"`\|`"stacked"`) | `"inline"` |
| `opacity` | `u8`(0..255) | `235` |
| `bg_color`/`text_color`/`muted_color`/`accent_color` | `String`(`"#RRGGBB"`) | `overlay/README.md` §7 参照 |
| `font_face`/`value_font_size`/`label_font_size`/`font_weight` | `String`/`i32` | `"Segoe UI"`/`13`/`9`/`600` |
| `corner_radius` | `i32` | `8` |
| `align` | `String`(`"left"`\|`"center"`\|`"right"`) | `"center"` |
| `grip_width` | `i32` | `12` |
| `update_interval_ms` | `u32` | `1000` |
| `separator` | `String` | `"   "` |
| `hide_on_fullscreen` | `bool` | `true` |
| `tray_emoji`/`tray_color`/`tray_tip` | `String` | `"📊"`/`"#4C8DEC"`/`"tbwidget"` |
| `extra` | `serde_json::Map<String, Value>`（`#[serde(flatten)]`） | `{}` |

`extra` はアプリ固有キー（例: `envmon-overlay` の `show_cpu`/`cpu_label`）を未知キーの
まま保持する前方互換フィールド。`Cfg::extra_bool(key, default)` / `Cfg::extra_str(key, default)`
で読む（他に `pub` ヘルパは無い — 型変換は呼び出し側で `serde_json::Value` を直接見る）。

### 2.6 `Widget` — 表示要素（`state.json` の型付き列）

`#[serde(tag = "type", rename_all = "lowercase")]` の enum。フィールドはすべて
`#[serde(default)]`（省略可）。

| variant | `type` 値 | フィールド |
|---|---|---|
| `Text` | `"text"` | `value: String`, `fg: String` |
| `Chip` | `"chip"` | `label: String`, `value: String`, `fg: String` |
| `Gauge` | `"gauge"` | `label: String`, `value: String`, `ratio: f32`, `fg: String`, `track: String` |
| `Bar` | `"bar"` | `ratio: f32`, `fg: String`, `track: String` |
| `Dot` | `"dot"` | `fg: String` |
| `Icon` | `"icon"` | `glyph: String`, `fg: String` |
| `Sep` | `"sep"` | （無し） |

`Widget` は `Deserialize` のみ（エンジン内部での消費専用。呼び出し側がこの型を直接構築
して返すのは `FallbackFn` の戻り値としてのみ — その場合は `Serialize` が無いため `state.json`
へ書き出すプロデューサ側〔例: Python〕は独自に同じ JSON 形を素で組み立てる）。

### 2.7 `StateIn` — `state.json` 全体

```rust
pub struct StateIn {
    pub visible: Option<bool>,
    pub dock: Option<String>,
    pub opacity: Option<f32>,   // 0.0..1.0
    pub widgets: Vec<Widget>,
    pub chips: Vec<ChipIn>,     // 旧スキーマ（後方互換）
}
impl StateIn {
    pub fn into_widgets(self) -> Vec<Widget>;
}
```

`into_widgets()` は `widgets` が非空ならそれを返し、空なら `chips`
（`{label,value,fg}` の旧形式）を `Widget::Chip` へ変換して返す。`ChipIn` 自体は
`pub` エクスポートされていない（`StateIn`/`Widget` 経由でのみ外部から扱う）。

### 2.8 `Paths` / `default_base_dir`

```rust
pub struct Paths { pub config: PathBuf, pub state: PathBuf, pub log: PathBuf }
pub fn default_base_dir(app_id: &str) -> PathBuf; // %APPDATA%\{app_id}（取得不可ならカレント）
```

`Paths::resolve(...)` 自体は非公開（`AppInfo` 経由でのみ呼ばれる内部実装）。外部から
直接パス解決ロジックを再利用したい場合は `default_base_dir` のみが使える。

### 2.9 色ヘルパ

```rust
pub fn parse_color(s: &str, default: u32) -> windows::Win32::Foundation::COLORREF;
pub fn color_or(fg: &str, fallback: COLORREF) -> COLORREF;
```

- `parse_color`: `"#RRGGBB"` を GDI の `COLORREF`（`0x00BBGGRR` 順）へ変換。`#` 無し6桁
  hexも受理。パース失敗時は `default` をそのまま `COLORREF` として返す。
- `color_or`: `fg` が空文字（トリム後）なら `fallback`、そうでなければ `parse_color(fg, fallback.0)`。
  `Widget` の `fg`/`track` が省略時にどの既定色へフォールバックするかはエンジン内部
  （`render.rs`）が `Cfg` の `text_color`/`accent_color`/`muted_color` を使って決める
  （`overlay/README.md` §6 の「`fg` 省略時」表を参照）。

### 2.10 最小の組み込み例

```rust
// Cargo.toml: tbwidget = { path = "../tbwidget" }

fn my_fallback(cfg: &tbwidget::Cfg) -> Vec<tbwidget::Widget> {
    vec![tbwidget::Widget::Chip {
        label: cfg.extra_str("label", "VAL"),
        value: "--".into(),
        fg: String::new(),
    }]
}

fn main() {
    let app = tbwidget::AppInfo::new("MyApp")
        .with_tray("自作ウィジェット", "⚡", "#4C8DEC")
        .with_fallback(my_fallback);
    tbwidget::run(app); // ブロックする
}
```

外部プロセス（Rust 以外でもよい）は `%APPDATA%\MyApp\state.json` に
`{"widgets": [...]}` を原子的に書けば、このバイナリが読んで描画する。
