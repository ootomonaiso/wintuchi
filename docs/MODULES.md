# モジュール別リファレンス（開発者向け）

`envmon/` と `taskwidget/` の各モジュールの責務・主要シンボルの早見表です。全体像・
データフローは [`ARCHITECTURE.md`](ARCHITECTURE.md) を参照してください。

主要シンボルは実ファイルから抽出した実在のクラス/関数名です（`_` 始まりの内部ヘルパは
原則省略）。

---

## `envmon/` — アプリ本体

### 統合・エントリ

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `main.py` | エントリポイント。各コンポーネントの生成・結線、スレッド跨ぎのマーシャリング、ライフサイクル。 | `main()`, `App`（`run` / `quit` / `_apply_update` / `_apply_web_config` / `_req_*`） |

`App` は非表示の `ctk.CTk` root を持ち、`Flyout` / `DesktopWidget` / `SettingsWindow` /
`Poller` / `Tray` / `Notifier` / `AppState` に加え、`OverlayBridge`（Rust オーバーレイ）と
`ConfigServer`（設定用ローカル HTTP）を保持します。tray・poller スレッドからの
呼び出しは `_req_*` / `_on_poll_update` が `root.after(0, …)` でメインスレッドへ渡します。

### オーバーレイ連携・設定ダッシュボード（UI 刷新・移行中）

Tk UI を段階的にヘッドレス化し、表示は Rust 製タスクバーオーバーレイ、設定は
ブラウザで開く HTML ダッシュボードへ移す移行の途中段階です。詳細計画と進捗は
[`PLAN-headless-rust-overlay.md`](PLAN-headless-rust-overlay.md)。

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `validate.py` | config 全項目の型/範囲フォールバック（UI 門番の代替）。`load_config()` と `POST /config` の両方で適用。 | `normalize(data) -> (clean, warnings)` |
| `overlay_bridge.py` | 部屋状態→色解決済みチップを `overlay.state.json` へ原子書き出し。overlay exe の spawn/stop。 | `write_state()`, `build_chips()`, `OverlayBridge`（`start` / `stop` / `apply_enabled`） |
| `httpconfig.py` | 設定用ローカル HTTP（`127.0.0.1` + 起動毎トークン）。tray「設定」からブラウザで開く。 | `ConfigServer`（`start` / `stop` / `url` / `status_payload`） |
| `settings.html` | CodeZeno 的な設定ダッシュボード（全般 / 部屋 / ウィジェットの 3 タブ・接続テスト・プリセット・検証）。生 JSON を触らせない。 | — （単一 HTML・インライン CSS/JS） |

`httpconfig` のエンドポイント：`GET /`（HTML＋token/presets 注入）/ `GET /config` /
`POST /config`（`validate.normalize` で正規化し `Config.replace`→`poll_now`）/
`GET /status`（接続状態・既知の部屋一覧）/ `GET /test`（サーバ側で URL を叩く）。
全エンドポイントはクエリの `t=<token>` を `secrets.compare_digest` で検証し、無ければ 403。

### 設定・データモデル

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `config.py` | 設定ロード/セーブ、保存先決定、`sensors.json` 読込（mtime 監視・自動反映）。 | `load_config()`, `Config`, `app_data_dir()`, `config_path()`, `sensors_path()`, `log_path()`, `DEFAULT_CONFIG`, `DEFAULT_ROOM` |
| `model.py` | 実行時状態のデータモデル。 | `Severity`(IntEnum), `Reading`, `RoomState`, `AppState` |
| `presets.py` | しきい値・状態ラベルのプリセット集。 | `ROOM_PRESETS`, `room_preset()`（＋ラベルプリセット） |

`Config` の主なメソッド：`snapshot()` / `get()` / `room_config()` / `room_for_sensor()` /
`sensors()` / `replace()` / `update()` / `set_sensors()` / `save()` / `reload_sensors()`。

### 監視ロジック

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `poller.py` | `/env1.php` を周期取得・パースし、状態更新と判定ディスパッチを行うワーカ。 | `Poller`（`start` / `stop` / `poll_now`）, `parse_records()`, `latest_per_sensor()` |
| `rules.py` | 部屋ごとの判定（停止検知・閾値・ヒステリシス・照度ゲート）。 | `evaluate_room()`, `AlertEvent` |
| `notifier.py` | 通知の集中管理（クールダウン・静音時間）と各チャネルへの配信。 | `Notifier`（`dispatch` / `test_notify`）, `in_quiet_hours()` |

`Poller` はデータの唯一の「書き手」。`_poll_once()` が取得→パース→`_update_state()`→
`on_update()` を実行し、`_update_state()` 内で `evaluate_room()` を部屋ごとに呼び、
得た `AlertEvent` をロック外で `Notifier.dispatch()` に渡します。

### 通知チャネル

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `toast.py` | Windowsトースト通知ラッパ。ライブラリ無/初期化失敗でも落ちない。 | `available()`, `show_toast()` |
| `teams.py` | Power Automate「HTTP 要求の受信時」向けに Adaptive Card + flat な `data` を POST。 | `build_payload()`, `send()` |

### UI（CustomTkinter）

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `tray.py` | pystray ベースのトレイアイコン・右クリックメニュー。 | `Tray`（`run_detached` / `stop` / `refresh`） |
| `flyout.py` | トレイ直上に出る枠なしポップアップ（部屋カード一覧・概況ピル・ゲージバー）。 | `Flyout`（`toggle` / `show` / `hide` / `refresh`） |
| `widget.py` | 常駐ウィジェット窓（`taskbar` 追従 / `float` 浮遊の 2 モード）。 | `DesktopWidget`（`show` / `hide` / `toggle` / `refresh` / `apply_enabled` / `reset_position`） |
| `settings_ui.py` | 設定画面（全般 / 部屋 / ウィジェットの 3 タブ）。 | `SettingsWindow`（`open`） |
| `theme.py` | 3 画面共通のデザイントークン（色は `(light, dark)` タプル）。 | `resolve()`, `font()`, `make_segbar()`, `label_for()` |
| `icons.py` | 状態色の温度計風トレイアイコンを Pillow で動的生成。 | `make_icon()`, `save_ico()` |

`flyout._gauge_spec()`（ゲージの割合・色の算出）は `widget.py` からも共有されます。

### システム連携

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `startup.py` | ログオン自動起動（`HKCU\…\Run`）の登録/解除、単一起動ミューテックス。 | `is_registered()`, `set_startup()`, `SingleInstance`（`acquire` / `release`） |

---

## `taskwidget/` — タスクバー追従ウィジェット（汎用ライブラリ）

EnvMonitor 非依存のライブラリ。使い方・API 早見は [`../taskwidget/README.md`](../taskwidget/README.md)。

| モジュール | 責務 | 主要シンボル |
|---|---|---|
| `__init__.py` | 公開 API（`TaskbarWidget` / `Chip` / 状態定数）。 | `TaskbarWidget`, `Chip`, `OK` / `WARN` / `CRITICAL` / `STALE` / `INFO` ほか |
| `widget.py` | 本体。`chip`/`gauge`/`renderer`/`every` などで組み立て、taskbar 追従 / float を切替。 | `TaskbarWidget` |
| `chips.py` | 表示部品「チップ」（ラベル + 値 + 任意のセグメントバー）。`update()` で中身差し替え。 | `Chip`（`update`） |
| `geometry.py` | Windows タスクバー座標検出（純 ctypes・依存ゼロ・Windows 専用）。 | `find_taskbar()`, `work_area()`, `system_uses_light_theme()`, `TaskbarInfo` |
| `theme.py` | 配色トークン・状態色・セグメントバー・フォント。 | `status_color()`, `resolve()`, `font()`, `make_segbar()` |
| `examples/` | 実行可能サンプル。 | `clock` / `system_monitor` / `custom_render`（`python -m taskwidget.examples.<name>`） |

---

## `tools/` — 開発補助

GUI 不要のロジック検証とプレビュー用スクリプト。実行例は [`README.md`](../README.md) の
「動作確認」節を参照。

| ファイル | 役割 |
|---|---|
| `mock_server.py` | 検証用モックサーバ（`/env1.php` を模擬。`ENVMON_SCENARIO` で挙動切替）。 |
| `test_logic.py` | ヘッドレスなコアロジック検証（GUI 不要）。 |
| `test_integration.py` | poller → rules → notifier の統合テスト。 |
| `test_sensors_json.py` | `sensors.json` の生成/反映/堅牢性テスト。 |
| `preview_ui.py` / `preview_widget.py` / `preview_settings.py` | フライアウト / ウィジェット / 設定画面のプレビュー（スクショ用）。 |
