# envmon-overlay — タスクバー常駐ウィジェットエンジン（取説）

Windows のタスクバー上に、好きな値を色付きで表示する最前面オーバーレイ。
Rust（`windows` crate）製の **単一 exe・ランタイム DLL 不要**。

このエンジンは「**何を表示するか**」を一切知りません。表示内容は
**`state.json`（外部プロセスが書く）** で与えます。EnvMonitor では Python が
温度/湿度を色解決して書き込み、本エンジンは読んで描くだけ、という責任分離です。

```
[値を決める人(例: Python)] --(state.json を書く)--> [envmon-overlay が読んで描画]
```

---

## 1. ビルド

前提: Rust ツールチェーン（`cargo`）。

```powershell
# 日本語パスだと mingw リンカが失敗するため、target を ASCII パスへ逃がす
$env:CARGO_TARGET_DIR = "C:/Users/ootom/envmon-overlay-target"
cargo build --release --manifest-path overlay/Cargo.toml
```

出力: `%CARGO_TARGET_DIR%/release/envmon-overlay.exe`（約 300KB、単一ファイル）。

> MSVC ツールチェーンなら日本語パスでも通るので、その場合 `CARGO_TARGET_DIR` の
> 逃がしは不要。

## 2. 起動・終了

```powershell
Start-Process "C:/Users/ootom/envmon-overlay-target/release/envmon-overlay.exe"
```

- **多重起動しない**（名前付きミューテックスで単一起動）。
- **終了**: トレイアイコンを右クリック →「終了」。
- トレイメニュー: 「タスクバーに戻す」「設定ファイルを開く」「終了」。
- 強制停止: `taskkill /IM envmon-overlay.exe /F`

## 3. 操作

| 操作 | 挙動 |
|---|---|
| 左端の **グリップ `|`** を掴んでドラッグ | 移動。当たり判定は見た目より広め |
| タスクバー上でドラッグ | **レール移動**（縦はバーに固定・横はバー内にクランプ）。トレイ左端からの距離を `gap` に記憶 |
| バーの外（上）へ引き出す | **free モード**に切替＝背景パネル付きで自由配置。位置を `pos` に記憶 |
| トレイ右クリック →「タスクバーに戻す」 | taskbar モードへ復帰（透過・追従） |
| 全画面アプリ（動画など）を開く | **自動で隠れる**（`hide_on_fullscreen`）。戻すと再表示 |

## 4. モードと見た目

- **taskbar モード（既定）**: 背景は透過（colorkey）＝文字だけがバーに乗る。トレイ左に追従。
- **free モード**: 背景パネル（`bg_color`＋`opacity`、角丸 `corner_radius`）で自由配置。

## 5. レイアウト

- `layout: "inline"` … `CPU 12%   MEM 45%` の1行。
- `layout: "stacked"` … ラベル（上・小）＋値（下・大）の**2段組み**を横に並べる。

## 6. ファイルの場所

| ファイル | 役割 | 書き手 |
|---|---|---|
| `C:/Users/ootom/envmon-overlay.config.json` | 見た目・配置の設定 | ユーザー（手編集）＋本体（位置保存時） |
| `C:/Users/ootom/envmon-overlay.state.json` | 表示内容（チップ列） | 外部プロデューサ（例: Python） |
| `C:/Users/ootom/envmon-overlay.log` | 起動ログ（デバッグ用） | 本体 |

> いずれも現状ソース内の定数で固定パス（`CFG_PATH`/`STATE_PATH`/`LOG_PATH`）。
> 将来 `%APPDATA%` 等へ移す場合はここを変更。

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

  "layout": "stacked",      // "inline"=1行 / "stacked"=ラベル+値の2段組み
  "align": "center",        // inlineの寄せ: left|center|right

  "opacity": 235,           // free背景の不透明度 0..255
  "bg_color": "#1E222A",    // free背景色
  "text_color": "#E9EBEF",  // 値の既定色（state.jsonのfgが無いとき）
  "muted_color": "#8A93A0", // グリップ・ラベルの色
  "corner_radius": 8,       // free背景の角丸(px)。0で四角

  "font_face": "Segoe UI",
  "value_font_size": 18,    // 値の文字サイズ（inline/stacked共通）
  "label_font_size": 12,    // stackedのラベル文字サイズ
  "font_weight": 600,       // 400=標準 600=太め 700=太字
  "grip_width": 12,         // グリップの見た目幅(px)。当たり判定は+8pxで広め

  "update_interval_ms": 1000, // 値取得・再描画の間隔

  "hide_on_fullscreen": true, // 全画面アプリ検出時に自動で隠す

  "tray_emoji": "📊",       // トレイアイコンに使う絵文字（単色シルエットで描画）
  "tray_color": "#4C8DEC",  // トレイアイコンの色

  // 内蔵フォールバック（state.jsonが無いとき表示するCPU/MEM）用
  "show_cpu": true,
  "show_mem": true,
  "cpu_label": "CPU",
  "mem_label": "MEM",
  "separator": "   "        // inlineのチップ区切り
}
```

## 8. 表示内容を流す `state.json`（外部インターフェース）

本エンジンに「何を出すか」を伝える唯一の口。**単一書き手・原子的書き込み**で更新すること
（`*.tmp` に書いて `os.replace` 等）。ファイルが無い/壊れている/空のときは、内蔵の
CPU/MEM 表示へ自動フォールバックする。

```json
{
  "chips": [
    { "label": "会議室A", "value": "35.2℃", "fg": "#E24C4C" },
    { "label": "サーバ室", "value": "22.0℃", "fg": "#3BA55D" }
  ]
}
```

| フィールド | 必須 | 意味 |
|---|---|---|
| `label` | 任意 | 上段（stacked）/先頭（inline）に出すラベル |
| `value` | 必須 | 強調表示する値（単位込みの文字列。例 `"35.2℃"` `"45%"`） |
| `fg` | 任意 | 値の色 `#RRGGBB`。**色の判断は書き手の責任**。省略で `text_color` |

ポイント:
- エンジンは値の意味を解釈しない。しきい値判定・色分けは**書き手側**で行う。
- `value_digits` により桁が変わっても幅は一定（短い値は中央寄せのまま）。

### 最小の書き手（Python 例）

```python
import json, os, time
STATE = r"C:/Users/ootom/envmon-overlay.state.json"
def write(chips):
    tmp = f"{STATE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"chips": chips}, f, ensure_ascii=False)
    os.replace(tmp, STATE)           # 原子的に差し替え
while True:
    write([{"label": "CPU", "value": "12%", "fg": "#3BA55D"}])
    time.sleep(1)
```

## 9. 同梱のプロデューサ

| スクリプト | 内容 |
|---|---|
| `overlay/produce_state.py` | デモ: psutil の CPU/RAM を閾値で色分けして書く |
| `overlay/produce_state_envmon.py` | 本線: EnvMonitor の config/poller で温度/湿度を取得し色解決して書く |

EnvMonitor 連携の実行例（モックサーバで試す）:

```powershell
# 1) モックサーバ（3部屋・mixed シナリオ）
$env:ENVMON_SCENARIO = "mixed"
C:\Users\ootom\envmon-venv\Scripts\python.exe tools/mock_server.py 8099
# 2) プロデューサ（接続先を上書き。省略時は EnvMonitor の config.json の url）
$env:ENVMON_URL = "http://127.0.0.1:8099/env1.php"
C:\Users\ootom\envmon-venv\Scripts\python.exe overlay/produce_state_envmon.py
# 3) overlay を起動 → タスクバーに部屋ごとの温度/湿度が色付きで出る
```

- 表示する部屋×指標は EnvMonitor の `config.json` の `widget.items`（無ければ全部屋の気温）。
- 色は部屋のしきい値（`rooms[].temp/humid` の min/max）から算出（緑=正常/橙=接近/赤=範囲外/灰=不明）。

## 10. 仕組み（概要）

- **タスクバー検出**: `FindWindow("Shell_TrayWnd")` でバー、`FindWindowEx(.. "TrayNotifyWnd")`
  で通知領域を取得。通知領域の左に `gap` だけ空けて配置し、1秒ごとに再計算して追従。
- **配置方式**: 最前面レイヤードウィンドウを重ねる「オーバーレイ追従」方式
  （`SetParent` でバーに埋め込む方式は Win11 で描画されず不採用）。
- **透過**: taskbar=カラーキー(`#010101`)、free=α合成（`opacity`）。
- **当たり判定**: グリップ領域だけ掴める（`HTCLIENT`）、他は貫通（`HTTRANSPARENT`）で
  タスクバー操作を邪魔しない。

## 11. 既知の制限

- **プライマリの横（上/下）タスクバー向け**。縦置き/副モニタのタスクバーは未対応。
- カラー絵文字ではなく**単色シルエット**アイコン（GDI 描画のため）。
- 固定パス運用（§6）。配布時は `%APPDATA%` 等へ寄せる想定。
