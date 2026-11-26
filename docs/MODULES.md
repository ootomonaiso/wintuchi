# モジュール別リファレンス（開発者向け）

`envmon/` の各モジュールの責務・主要シンボルの早見表です。全体像・データフローは
[`ARCHITECTURE.md`](ARCHITECTURE.md) を参照してください。

主要シンボルは実ファイルから抽出した実在のクラス/関数名です（`_` 始まりの内部ヘルパは
原則省略）。

---

## `envmon/` — アプリ本体（ヘッドレス）

### 統合・エントリ

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `main.py` | エントリポイント。各コンポーネントの生成・結線、ライフサイクル。GUI ツールキット非依存。 | `main()`, `App`（`run` / `_cleanup` / `_toggle_overlay` / `_open_web_settings` / `_apply_web_config`） |

`App` は `Poller` / `Tray` / `Notifier` / `AppState` に加え、`OverlayBridge`（Rust
オーバーレイの spawn/stop）と `ConfigServer`（設定用ローカル HTTP）を保持します。GUI
メインループを持たないため、`threading.Event` の待機だけで終了トリガを受け取ります。

### オーバーレイ連携・設定ダッシュボード

旧 Tk UI（`flyout.py` / `widget.py` / `settings_ui.py`、いずれも削除済み）の後継。
表示は Rust 製タスクバーオーバーレイ（`overlay/`）、設定はブラウザで開く HTML
ダッシュボードが担います。経緯・計画は
[`PLAN-headless-rust-overlay.md`](PLAN-headless-rust-overlay.md)。

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `validate.py` | config 全項目の型/範囲フォールバック（UI 門番の代替）。`load_config()` と `POST /config` の両方で適用。 | `normalize(data) -> (clean, warnings)` |
| `overlay_bridge.py` | 部屋状態→色解決済みチップ＋`visible` を `overlay.state.json` へ原子書き出し。overlay exe の spawn/stop。 | `write_state()`, `build_chips()`, `OverlayBridge`（`start` / `stop` / `apply_enabled`） |
| `httpconfig.py` | 設定用ローカル HTTP（`127.0.0.1` + 起動毎トークン）。tray「設定」からブラウザで開く。 | `ConfigServer`（`start` / `stop` / `url` / `status_payload`） |
| `settings.html` | CodeZeno 的な設定ダッシュボード（全般 / 部屋 / ウィジェットの 3 タブ・接続テスト・プリセット・検証）。生 JSON を触らせない。 | — （単一 HTML・インライン CSS/JS） |

`httpconfig` のエンドポイント：`GET /`（HTML＋token/presets 注入）/ `GET /config` /
`POST /config`（`validate.normalize` で正規化し `Config.replace`→`poll_now`→
`overlay.apply_enabled`）/ `GET /status`（接続状態・既知の部屋一覧）/ `GET /test`
（サーバ側で URL を叩く）。全エンドポイントはクエリの `t=<token>` を
`secrets.compare_digest` で検証し、無ければ 403。各エンドポイントの
リクエスト/レスポンスJSONの詳細は [`API.md`](API.md) §1。

### 設定・データモデル

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `config.py` | 設定ロード/セーブ、保存先決定、`sensors.json` 読込（mtime 監視・自動反映）。読み書き時に `validate.normalize` を適用。 | `load_config()`, `Config`, `app_data_dir()`, `config_path()`, `sensors_path()`, `log_path()`, `DEFAULT_CONFIG`, `DEFAULT_ROOM` |
| `model.py` | 実行時状態のデータモデル。 | `Severity`(IntEnum), `Reading`, `RoomState`, `AppState` |
| `presets.py` | しきい値・状態ラベルのプリセット集。 | `ROOM_PRESETS`, `room_preset()`（＋ラベルプリセット） |

`Config` の主なメソッド：`snapshot()` / `get()` / `room_config()` / `room_for_sensor()` /
`sensors()` / `replace()` / `update()` / `save()` / `reload_sensors()`。

### 監視ロジック

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `poller.py` | `/env1.php` を周期取得・パースし、状態更新と判定ディスパッチを行うワーカ。 | `Poller`（`start` / `stop` / `poll_now`）, `parse_records()`, `latest_per_sensor()` |
| `rules.py` | 部屋ごとの判定（停止検知・閾値・ヒステリシス・照度ゲート）。 | `evaluate_room()`, `AlertEvent` |
| `notifier.py` | 通知の集中管理（クールダウン・静音時間）と各チャネルへの配信。 | `Notifier`（`dispatch` / `test_notify`）, `in_quiet_hours()` |

`Poller` はデータの唯一の「書き手」。`_poll_once()` が取得→パース→`_update_state()`→
`on_update()` を実行し、`_update_state()` 内で `evaluate_room()` を部屋ごとに呼び、
得た `AlertEvent` をロック外で `Notifier.dispatch()` に渡します。`on_update` は
`overlay_bridge.write_state()`（表示更新）と `tray.refresh()`（アイコン/ツールチップ更新）
を呼びます。

### 通知チャネル

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `toast.py` | Windowsトースト通知ラッパ。ライブラリ無/初期化失敗でも落ちない。 | `available()`, `show_toast()` |
| `teams.py` | Power Automate「HTTP 要求の受信時」向けに Adaptive Card + flat な `data` を POST。 | `build_payload()`, `send()` |

### トレイ・配色・アイコン

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `tray.py` | pystray ベースのトレイアイコン・右クリックメニュー（オーバーレイ表示/非表示・設定…・今すぐ更新・終了）。 | `Tray`（`run_detached` / `stop` / `refresh`） |
| `theme.py` | 色トークンの単一情報源（`(light, dark)` タプル）。GUI ツールキット非依存。 | `resolve()`, `system_uses_light_theme()`, `label_for()`, `SEV_COLOR` / `SEV_SOFT` / `SEV_TEXT` |
| `icons.py` | 状態色の温度計風トレイアイコンを Pillow で動的生成。 | `make_icon()`, `save_ico()` |

`theme.py` は `envmon` の他モジュールからは直接 import されていません（色解決は
`overlay_bridge._color()` が独自に行う）。将来 Python 側で配色を使う描画が増えた場合の
単一情報源として保持しています。

### システム連携

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `startup.py` | ログオン自動起動（`HKCU\…\Run`）の登録/解除、単一起動ミューテックス。 | `is_registered()`, `set_startup()`, `SingleInstance`（`acquire` / `release`） |

---

## `overlay/` — 表示ウィジェット（Rust、別プロセス）

Python 本体とは別にビルド・起動される独立バイナリ群。Cargo workspace で
汎用エンジン `tbwidget` と薄いバイナリ `envmon-overlay` に分かれています。
設定スキーマ・ビルド手順の詳細は [`../overlay/README.md`](../overlay/README.md)、
`tbwidget` の公開関数・型（`AppInfo`/`Cfg`/`Widget`等）のシグネチャは
[`API.md`](API.md) §2 を参照してください（本ドキュメントでは Python との境界のみ扱います）。

| クレート | 責務 |
|---|---|
| `tbwidget` | 汎用のタスクバー追従ウィジェット描画エンジン。`state.json` を読んで描くだけで内容を解釈しない。 |
| `envmon-overlay` | `tbwidget` の薄いバイナリ。EnvMonitor 向けの既定（パス・トレイ色・内蔵 CPU/MEM フォールバック）を注入する。 |

Python 側との境界（`envmon/overlay_bridge.py` が書く）：`%APPDATA%\EnvMonitor\overlay.state.json`
に `{"visible": bool, "chips": [{"label","value","fg"}, ...]}` を原子書き出し。
`visible=false` で overlay はウィンドウを隠す（プロセスは常駐のまま）。

---

## `tools/` — 開発補助

GUI 不要のロジック検証とモックサーバ。実行例は [`README.md`](../README.md) の
「動作確認」節を参照。

| ファイル | 役割 |
|---|---|
| `mock_server.py` | 検証用モックサーバ（`/env1.php` を模擬。`ENVMON_SCENARIO` で挙動切替）。 |
| `test_logic.py` | ヘッドレスなコアロジック検証（GUI 不要）。 |
| `test_integration.py` | poller → rules → notifier の統合テスト（`mock_server.py` 起動が前提）。 |
| `test_sensors_json.py` | `sensors.json` の生成/反映/堅牢性テスト（隔離 APPDATA で実行）。 |
| `_smoke_phase4.py` | `validate.normalize` と `httpconfig.ConfigServer` のスモークテスト。 |
