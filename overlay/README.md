# tbwidget — 汎用タスクバー追従ウィジェット描画エンジン

Windows のタスクバー上（トレイ左）に、最前面レイヤードウィンドウを重ねて追従描画する
“埋め込み風”オーバーレイ。Rust（`windows` crate）製の **単一 exe・ランタイム DLL 不要**。

このエンジンは「**何を表示するか**」を一切知りません。表示内容は外部プロセスが
**`state.json`（型付き要素列）** に書き、本エンジンは読んで描くだけ、という責任分離です。
アプリ固有の値（パス・名前・配色・フォールバック）は呼び出し側が注入します。

Rust から埋め込む際の公開関数・型（`AppInfo` のビルダメソッド一覧・`Cfg`/`Widget` の
全フィールド等）のシグネチャ単位のリファレンスは
[`../docs/API.md`](../docs/API.md) §2 を参照してください。本READMEはユーザー向けの
操作・設定項目・ファイル配置を中心に説明します。

```
[値を決める人(例: Python)] --(state.json を書く)--> [tbwidget が読んで描画]
```

---

## 0. 構成（cargo workspace）

```
overlay/
  Cargo.toml          … workspace（profile.release を集約）
  tbwidget/           … 再利用エンジン crate（アプリ非依存・sysinfo 非依存）
    src/lib.rs        … 公開 API（AppInfo / run / Cfg / Widget）
    src/schema.rs     … config.json / state.json のスキーマ＋色パース
    src/paths.rs      … ベースディレクトリ・各ファイルパスの解決
    src/render.rs     … 型付き Widget の幅測定＋描画（フローレイアウト）
    src/engine.rs     … Win32 本体（窓・追従・ドラッグ・トレイ・ループ）
  envmon-overlay/     … 薄い EnvMonitor 向けバイナリ
    src/main.rs       … ブランド既定＋内蔵 CPU/MEM フォールバックを注入
```

- **`tbwidget`** … 他プロジェクトから `tbwidget = { path = "..." }` で組み込める汎用エンジン。
- **`envmon-overlay`** … `tbwidget::run(AppInfo{...})` を呼ぶだけの薄いバイナリ。
  CLI/環境変数でパスや app-id を差し替えれば、そのまま**汎用オーバーレイランナー**になる。

### 最小の組み込み例（他アプリ）

```rust
let app = tbwidget::AppInfo::new("MyApp")
    .with_tray(" 自作ウィジェット", "⚡", "#4C8DEC");
tbwidget::run(app); // メッセージループへ（終了までブロック）
// → %APPDATA%\MyApp\{config,state}.json を読み書きして描画
```

---

## 1. ビルド

前提: Rust ツールチェーン（`cargo`）。

```powershell
# 日本語パスだと mingw リンカが失敗するため、target を ASCII パスへ逃がす
$env:CARGO_TARGET_DIR = "C:/Users/ootom/envmon-overlay-target"
cargo build --release --manifest-path overlay/Cargo.toml
```

出力: `%CARGO_TARGET_DIR%/release/envmon-overlay.exe`（約 540KB、単一ファイル）。
テスト: `cargo test -p tbwidget`（スキーマのパース/後方互換/色解決）。

> MSVC ツールチェーンなら日本語パスでも通るので `CARGO_TARGET_DIR` の逃がしは不要。

## 2. 起動・終了

```powershell
Start-Process "C:/Users/ootom/envmon-overlay-target/release/envmon-overlay.exe"
```

- **多重起動しない**（app-id ごとの名前付きミューテックスで単一起動）。
- **終了**: トレイアイコンを右クリック →「終了」。強制停止は `taskkill /IM envmon-overlay.exe /F`。
- トレイメニュー: 「タスクバーに戻す」「設定ファイルを開く」「終了」。

### CLI / 環境変数での上書き（アプリ非依存化）

`envmon-overlay` は既定で EnvMonitor 用だが、指定を上書きすれば任意アプリ用に流用できる。

| CLI | 環境変数 | 意味 |
|---|---|---|
| `--app-id NAME` | `TBWIDGET_APP_ID` | ベースフォルダ名・クラス・単一起動キーの基 |
| `--title T` | `TBWIDGET_TITLE` | ウィンドウタイトル（内部用） |
| `--data-dir DIR` | `TBWIDGET_DATA_DIR` | ベースディレクトリ |
| `--config PATH` | `TBWIDGET_CONFIG` | config.json の絶対パス |
| `--state PATH` | `TBWIDGET_STATE` | state.json の絶対パス |
| `--log PATH` | `TBWIDGET_LOG` | ログの絶対パス |

```powershell
# 例: 別アプリのウィジェットとして使う
envmon-overlay --app-id MyApp --data-dir C:\myapp --state C:\myapp\widget.json
```

（CLI が環境変数より優先。未指定は EnvMonitor 既定＝`%APPDATA%\EnvMonitor\overlay.*`。）

## 3. 操作

| 操作 | 挙動 |
|---|---|
| 左端の **グリップ `|`** を掴んでドラッグ | 移動。当たり判定は見た目より広め |
| タスクバー上でドラッグ | **レール移動**（縦はバー固定・横はバー内クランプ）。トレイ左端からの距離を `gap` に記憶 |
| バーの外（上）へ引き出す | **free モード**＝背景パネル付きで自由配置。位置を `pos` に記憶 |
| トレイ右クリック →「タスクバーに戻す」 | taskbar モードへ復帰（透過・追従） |
| 全画面アプリを開く | **自動で隠れる**（`hide_on_fullscreen`）。戻すと再表示 |

## 4. モードと見た目

- **taskbar モード（既定）**: 背景は透過（colorkey `#010101`）＝文字だけがバーに乗る。トレイ左に追従。
- **free モード**: 背景パネル（`bg_color`＋`opacity`、角丸 `corner_radius`）で自由配置。

## 5. ファイルの場所

`envmon-overlay` 既定（上書きしない場合）:

| ファイル | 役割 | 書き手 |
|---|---|---|
| `%APPDATA%\EnvMonitor\overlay.config.json` | 見た目・配置の設定 | ユーザー（手編集）＋本体（位置保存時） |
| `%APPDATA%\EnvMonitor\overlay.state.json` | 表示内容（要素列） | 外部プロデューサ（例: Python） |
| `%APPDATA%\EnvMonitor\overlay.log` | 起動ログ（デバッグ用） | 本体 |

汎用エンジンの既定ベースは `%APPDATA%\{app_id}\`（§2 の指定で上書き可）。

## 6. 表示内容を流す `state.json`（外部インターフェース）

「何を出すか」を伝える唯一の口。**単一書き手・原子的書き込み**で更新すること
（`*.tmp` に書いて `os.replace` 等）。ファイルが無い/壊れている/空のときは、注入された
フォールバック（`envmon-overlay` では内蔵 CPU/MEM）へ自動フォールバックする。

```json
{
  "visible": true,
  "dock": "taskbar",
  "opacity": 0.95,
  "widgets": [
    {"type": "chip",  "label": "会議室A", "value": "35.2℃", "fg": "#E24C4C"},
    {"type": "sep"},
    {"type": "gauge", "label": "MEM", "value": "62%", "ratio": 0.62, "fg": "#E8A33D"},
    {"type": "dot",   "fg": "#3BA55D"},
    {"type": "bar",   "ratio": 0.8, "fg": "#4C8DEC"},
    {"type": "icon",  "glyph": "⚡", "fg": "#E8A33D"},
    {"type": "text",  "value": "OK"}
  ]
}
```

### トップレベル（任意）

| フィールド | 既定 | 意味 |
|---|---|---|
| `visible` | `true` | `false` でウィンドウを隠す（プロセスは常駐のまま） |
| `dock` | config に従う | `"taskbar"` / `"free"` を state から上書き |
| `opacity` | config に従う | free 背景の不透明度 `0.0..1.0`（state 上書き） |

### `widgets`（型付き要素。`type` でディスパッチ）

| type | フィールド | 描画 |
|---|---|---|
| `text` | `value`, `fg?` | 文字 |
| `chip` | `label`, `value`, `fg?` | ラベル＋値（inline は "ラベル 値"、stacked は上下2段） |
| `gauge` | `label?`, `value?`, `ratio`, `fg?`, `track?` | 値＋下端の充填バー（`ratio` 0..1） |
| `bar` | `ratio`, `fg?`, `track?` | 単独の水平バー |
| `dot` | `fg?` | 状態ドット（丸） |
| `icon` | `glyph`, `fg?` | 絵文字/記号1文字 |
| `sep` | — | 縦の区切り線 |

- `fg`/`track` は色解決済みの `#RRGGBB`。**色の判断は書き手の責任**（省略で既定色）。
- `fg` 省略時: text/chip/icon は `text_color`、gauge/bar/dot は `accent_color`、track は `muted_color`。
- 旧スキーマ `{"chips":[{label,value,fg}]}` も受理（`chip` ウィジェットへ変換）＝**後方互換**。
  `widgets` が非空ならそちらを優先。

### 最小の書き手（Python 例）

```python
import json, os
STATE = os.path.join(os.environ["APPDATA"], "EnvMonitor", "overlay.state.json")
def write(widgets):
    tmp = f"{STATE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"widgets": widgets}, f, ensure_ascii=False)
    os.replace(tmp, STATE)  # 原子的に差し替え
write([{"type": "chip", "label": "CPU", "value": "12%", "fg": "#3BA55D"}])
```

## 7. 設定 `config.json`（全項目）

編集して保存すると **再起動なしで反映**（ホットリロード、最大1秒）。

```jsonc
{
  "dock": "taskbar",        // "taskbar"=透過・トレイ左追従 / "free"=背景付き自由配置
  "pos": { "x": 1462, "y": 943 }, // free時/ドラッグ後の位置（本体が自動更新）
  "gap": 31,                // taskbar時: トレイ左端からの間隔(px)（ドラッグで更新）

  "auto_width": true,       // 内容に合わせて幅自動。falseなら width を使用
  "width": 190,             // auto_width=false のときの固定幅
  "value_digits": 3,        // 値の桁数ぶん幅を常に確保（桁変化でガタつかない）。0で無効

  "layout": "inline",       // "inline"=1行 / "stacked"=ラベル+値の2段組み

  "opacity": 235,           // free背景の不透明度 0..255
  "bg_color": "#1E222A",    // free背景色
  "text_color": "#E9EBEF",  // text/chip/icon の既定色
  "muted_color": "#8A93A0", // グリップ・ラベル・バーのトラック色
  "accent_color": "#4C8DEC",// gauge/bar/dot のフィル既定色
  "corner_radius": 8,       // free背景の角丸(px)。0で四角

  "font_face": "Segoe UI",
  "value_font_size": 13,    // 値の文字サイズ
  "label_font_size": 9,     // stackedのラベル文字サイズ
  "font_weight": 600,       // 400=標準 600=太め 700=太字
  "grip_width": 12,         // グリップの見た目幅(px)。当たり判定は+8pxで広め
  "separator": "   ",       // inline 要素間の間隔を決める基準文字列

  "update_interval_ms": 1000, // 値取得・再描画の間隔
  "hide_on_fullscreen": true, // 全画面アプリ検出時に自動で隠す

  "tray_emoji": "📊",       // トレイアイコンに使う絵文字（単色シルエットで描画）
  "tray_color": "#4C8DEC",  // トレイアイコンの色
  "tray_tip": "EnvMonitor"  // トレイのツールチップ

  // アプリ固有キーは素通しで保持（前方互換）。
  // envmon-overlay は内蔵フォールバック用に show_cpu/show_mem/cpu_label/mem_label を使う。
}
```

## 8. 同梱のプロデューサ（EnvMonitor 連携）

| スクリプト | 内容 |
|---|---|
| `overlay/produce_state.py` | デモ: psutil の CPU/RAM を閾値で色分けして書く |
| `overlay/produce_state_envmon.py` | 本線: EnvMonitor の config/poller で温度/湿度を取得し色解決して書く |

EnvMonitor 本体との連携は `envmon/overlay_bridge.py` が担う（部屋状態→チップ色解決→
`overlay.state.json` 原子書き出し＋ exe の spawn/stop）。state は従来の `chips` 形式で
書くが、本エンジンは後方互換で受理するため**無改修で連携できる**。

## 9. 仕組み（概要）

- **タスクバー検出**: `FindWindow("Shell_TrayWnd")` でバー、`FindWindowEx(.. "TrayNotifyWnd")`
  で通知領域。通知領域の左に `gap` だけ空けて配置し、1秒ごとに再計算して追従。
- **配置方式**: 最前面レイヤードウィンドウを重ねる「オーバーレイ追従」方式
  （`SetParent` 埋め込みは Win11 で描画されず不採用）。
- **透過**: taskbar=カラーキー(`#010101`)、free=α合成（`opacity`）。
- **当たり判定**: グリップ領域だけ掴める（`HTCLIENT`）、他は貫通（`HTTRANSPARENT`）で
  タスクバー操作を邪魔しない。
- **描画**: 型付き Widget を measure（幅測定）と paint（描画）で一致させたフローレイアウト。

## 10. 既知の制限

- **プライマリの横（上/下）タスクバー向け**。縦置き/副モニタのタスクバーは未対応。
- カラー絵文字ではなく**単色シルエット**アイコン（GDI 描画のため）。
- 透過は per-pixel α ではなくカラーキー方式（`#010101` は表示に使えない）。
