# 計画書: ヘッドレス Python + Rust タスクバーオーバーレイ・エンジン + JSON全振り

作成: 2026-11-25 / 更新: 2026-11-26 / ステータス: **Phase 0〜5 完了・Phase 6 一部完了**（§7 参照）。
以下は合意形成時の原文（経緯の記録として維持）。現在の実装の正とする場合は
[`ARCHITECTURE.md`](ARCHITECTURE.md) / [`MODULES.md`](MODULES.md) を参照。

## 0. 目的と大方針
現行の Tk(customtkinter) ベース UI を全廃し、**責任を言語で分離**する。

- **Rust = 描画エンジン（how / 仕組み）**: 速く・綺麗なタスクバー追従オーバーレイ。内容を一切解釈しない“バカな”レンダラ。
- **Python = 内容決定（what / 方針）＝誰でも触れる**: poll→判定→色/ラベル解決し「何をどう見せるか」を JSON に書き出すだけ。
- **設定は JSON 全振り**。編集体験は「単一の雑な HTML」をローカルで開いて行う（Tk ゼロ）。

> 注意（事実確認）: Win11 にタスクバー**埋め込み**の公式 API は無い。本エンジンは Shell_TrayWnd / TrayNotifyWnd を検出し、最前面レイヤードウィンドウを重ねて**追従**する“埋め込み風”方式。縦置き/自動非表示タスクバーは float へフォールバック。

## 1. 最終アーキテクチャ

```
┌─ envmon (Python, ヘッドレス) ────────────┐   state.json   ┌─ envmon-overlay.exe (Rust) ─┐
│ poller / rules / notifier / teams        │ ───(Python書)─▶ │ レイヤードウィンドウ(per-px α)│
│ tray(pystray) / config(単一書き手)        │                │ タスクバー検出・追従・DPI     │
│ state.json 書き出し                       │ ◀─(commands)─── │ ドラッグ / ✕ / ⚙ クリック     │
│ 設定用ローカル HTTP + settings.html       │   commands/     └──────────────────────────────┘
└──────────────────────────────────────────┘
```

### プロセス
1. **envmon（Python・GUIツールキット非依存）**: バックグラウンド群 + tray。Tk/customtkinter 依存ゼロ。
2. **envmon-overlay.exe（Rust）**: 常駐1プロセス。`state.json` を読んで描くだけ。

### データ契約（すべて `config.app_data_dir()` 配下）
| ファイル | 唯一の書き手 | 読み手 | 中身 |
|---|---|---|---|
| `config.json` | Python のみ | Python（＋HTML経由編集） | 設定（URL/間隔/しきい値/ラベル/静音/widget項目 等） |
| `state.json` | Python poller のみ | overlay のみ | 描画状態（下記スキーマ） |
| `commands/*.json` | overlay のみ | Python が消費して削除 | 逆方向イベント |
| `sensors.json` | ユーザーのみ（従来通り） | Python | センサID→部屋 |

**原則「1ファイル1書き手」**でレース回避（`os.replace` の原子性＝読み手は常に完全な JSON を見る。Phase0 で tmp 原子書き込みは修正済み）。

#### state.json スキーマ（overlay が理解する唯一の形）
overlay は温度/湿度/severity を**知らない**。色解決済みの見た目だけ受け取る。
```json
{
  "visible": true,
  "dock": "taskbar",
  "opacity": 0.96,
  "chips": [
    {"room": "会議室A", "text": "35.2℃", "fg": "#E24C4C", "dot": "#E24C4C"},
    {"room": "倉庫",    "text": "48%",   "fg": "#FFFFFF", "dot": null}
  ],
  "status": {"last_ok": "12:56:00", "error": null}
}
```
- `visible`: 表示/非表示（tray トグルは Python がこのフラグを書き換えるだけ）。
- `fg`/`dot`: Python が `_gauge_spec`＋`theme.resolve`（light/dark 解決）で算出した**最終hex**。
- `pos`/`taskbar_gap` の権威は config.json（再起動で復元）。overlay へは state.json に畳んで渡す（echo）。

#### commands（overlay → Python、投函箱方式）
```json
{"type": "toggle"}                                  // ✕ など
{"type": "open_settings"}                           // ⚙ → Python が settings.html をブラウザで開く
{"type": "pos", "dock": "float",   "x": 1700, "y": 980}
{"type": "pos", "dock": "taskbar", "taskbar_gap": 120}
{"type": "reset_position"}
```
Python は commands/ を監視→適用→**ファイル削除**。位置系は config.json に保存（単一書き手維持）。

## 2. 設定手段: 単一の雑な HTML
- Python が `127.0.0.1` に小さな HTTP サーバを立て、**1枚の HTML**（フォーム）を配信。tray「設定」→ `webbrowser.open(url)`。
- エンドポイント:
  - `GET /`            … settings.html（プリセット選択・接続テストボタン・各入力を同梱）
  - `GET /config`      … 現在の config.json を返す
  - `POST /config`     … **検証・正規化**して config.json を書き、poller に即時反映（poll_now）
  - `GET /test`        … サーバ側で URL を叩き結果を返す（ブラウザの CORS/混在コンテンツ回避）
- プリセット（`presets.py`）は JSON として HTML に注入 → ワンクリック流し込みを維持。
- セキュリティ: `127.0.0.1` バインド＋起動毎のランダムトークンを URL に付与（ローカル他プロセスからの POST を軽く防ぐ）。
- 「雑」の範囲: 1ファイル・インラインCSS/JS・最小限の見た目。やさしさの核（プリセット・接続テスト・入力検証）だけ押さえる。

## 2.5 UX方針（参照: CodeZeno/Claude-Code-Usage-Monitor）
ユーザーが「この使いやすさが欲しい」と指定。CodeZeno(Rust 製・トレイ常駐ウィジェット)の UX を基準にする。実装調査で分かった要点と本プロジェクトへの対応:

| CodeZeno の作法 | 本プロジェクトの対応 |
|---|---|
| **設定は GUI ダッシュボードで編集／保存は `%APPDATA%\...\settings.json`** | **「JSON全振り」はあくまで裏の保管庫。ユーザーが触るのは“雑なHTML＝ダッシュボード”**。生JSON編集は上級者の抜け道として残すだけ |
| 左クリック=ウィジェット表示トグル / 右クリック=コンテキストメニュー | tray: 左=visible トグル（state.json 書換）/ 右=メニュー。現 tray.py を踏襲 |
| 一目で現状（使用量・残り）／表示項目を切替可 | チップで部屋×指標を一目表示。表示項目はダッシュボードで選択（config.widget.items） |
| ホバーのツールチップにエラー/状態 | tray ツールチップにエラー要約＋N部屋/M件（現 tray.py を強化） |
| ゼロ設定オンボーディング（資格情報の自動検出） | URL は自動検出不可。代替＝**接続テスト＋しきい値/ラベルのプリセット＋接続状態の明示**で“すぐ使える”を担保 |
| Theme Studio（配色カスタム） | 任意。theme トークンは JSON 化すれば将来対応可。初期は不要 |
| ゼロテレメトリ | 既に外部送信は Teams webhook のみ。方針一致 |

**結論（矛盾解消）**: 先に懸念した「設定UI廃止＝非技術者置き去り」は、**HTML を“生JSONエディタ”でなく“CodeZeno 的な親切ダッシュボード”として作る**ことで回避する。JSON は人が読む対象でなく保存形式。これが CodeZeno と同じ勝ち筋。

## 3. 検証・正規化レイヤ（UI門番の代替・最重要）
UI が消えるぶん、**不正 JSON が唯一にして最大の故障点**。全設定項目に型/範囲のフォールバックと log を持たせる（Phase0 の `poll_interval_sec` 即死修正の一般化）。
- `envmon/validate.py`: `normalize(data) -> (clean_data, [warnings])`。
- 適用点: `config.load_config()` 読み込み時 ＋ `POST /config` 時。
- 例: `poll_interval_sec` 非数→30、`lux_gate.mode` が許可外→"off"、時刻書式不正→既定、未知キー→保持（前方互換）。

## 4. Rust エンジン（再利用可能な `tbwidget` クレート + `envmon-overlay` バイナリ）
Python `taskwidget` の Rust 後継。エンジンは汎用（state.json を描く）、envmon-overlay はその薄いバイナリ。
技術: `windows` crate のみ。**単一ポータブル exe・ランタイム DLL 無し**（trafficbar に倣う。Deskband11Lib のようなネイティブ DLL+UIAutomation 依存は避ける）。

### 4.1 配置方式の決定: 「子ウィンドウ埋め込み(SetParent)」を主、「追従オーバーレイ」を副
先駆者調査（§4.4）の結果、トレイ左隣（`^` オーバーフローの外）に出す用途の**主流かつ Rust 実証済み(trafficbar)は SetParent 埋め込み**。z-order 埋没・追従がほぼ自動で解決するため、当初案のオーバーレイより堅い。縦置き/未検出時のみオーバーレイ/float へフォールバック。

**埋め込み手順（Win11 下辺タスクバー）**:
1. `FindWindowW("Shell_TrayWnd", null)`（プライマリ）/ `Shell_SecondaryTrayWnd`（副モニタ）でタスクバー HWND。
2. Win11 判定は**バージョン番号でなく子クラス `Windows.UI.Composition.DesktopWindowContentBridge` の存在**で行う。
3. `FindWindowExW(tray, 0, "TrayNotifyWnd", 0)` でトレイ矩形取得 → 自分の右端 = `tray_left - gap`。
4. 自窓を生成後 `GWL_STYLE` を `WS_CHILD | WS_CLIPSIBLINGS | WS_VISIBLE` に変更し `SetParent(hwnd, tray)`。必要なら `SetWindowRgn` でクリップ。
5. `SetWindowPos`（親クライアント座標。`MapWindowPoints`/`ScreenToClient` で変換）でトレイ左・縦中央・高さはバー高にクランプ。
- **透過**: `WS_EX_LAYERED` + `UpdateLayeredWindow`（premultiplied alpha DIB）で**真の per-pixel α**＝Tk のカラーキー `#010101` ハック卒業。子ウィンドウでも layered は Win8+ 可。代替としてカラーキーもフォールバック用に実装（trafficbar も両対応）。
- **描画**: GDI/GDI+（必要なら DirectWrite）でチップ（部屋名小+値大bold+色ドット）。横並び＋細い区切り線（現 Tk 版の見た目を踏襲）。

### 4.2 堅牢性（先駆者が実際に踏んだ地雷への対処）
- **explorer.exe 再起動で子窓が破棄される** → `RegisterWindowMessageW("TaskbarCreated")` を購読し、受信したらタスクバー再探索→窓を再生成・再 SetParent（Deskband11Lib の `TaskbarWindowRecreated` 相当）。
- **DPI 変化でタスクバーと自窓の DPI がズレて位置崩れ** → `WM_DPICHANGED` 処理＋`GetDpiForWindow(tray)` と自窓 DPI をポーリング比較。不一致なら**一旦 hide+detach して新 DPI で再構築**（Deskband11Lib の実証パターン）。manifest は Per-Monitor V2。
- **z-order 埋没** → WS_CHILD 化で親(taskbar)の管理下に入り原則自動解決。保険としてトレイ幅変化時（アイコン増減）に位置再計算。
- **マルチモニタ/副タスクバー** → 主は primary(bottom)のみ対応し、それ以外はオーバーレイ/float へフォールバック（UIAutomation 依存を避け軽量に保つ）。VirtualScreen 原点が負(-1920)になる件に注意（メモ既知）。
- **自動非表示タスクバー** → 検出してオーバーレイ/float フォールバック（埋め込みは相性不良）。

### 4.3 入力・ドラッグ
- 埋め込み方式ではユーザーのドラッグ移動は**廃止**し、トレイ左端からの間隔は `config.json`（HTML で編集）で指定（trafficbar と同じく自動配置）。これで現 Tk 版のドラッグ/間隔記憶ロジックが不要になり簡素化。
- `✕`/`⚙` 相当はクリック領域の `WM_LBUTTONUP` ヒットテスト（α>0 の塗り領域）→ command 出力。レイヤード窓のヒットテストは要検証点。

### 4.4 先駆者調査（2026-11-25, 実装方式の典拠）
2系統ある:
- **A. 子ウィンドウ埋め込み（SetParent → Shell_TrayWnd, WS_CHILD）**: TrafficMonitor, **trafficbar(Rust/GDI/UpdateLayeredWindow・単一exe)**, TempTray, winstats, Deskband11Lib。トレイ左・オーバーフロー外に出せる。z-order/追従が自動。弱点=explorer 再起動・DPI・Win11内部変更に脆く、対策コード必須。
- **B. 最前面レイヤードオーバーレイ＋WinEventHook 追従**: NetSpeedTray（埋没/explorer 再起動からの復帰 PR あり）。reparent しない分 Win11 変更に強いが、埋没対策と追従を自前で持つ。
→ **本プロジェクトは A を主・B を副**に採用。A の対策（TaskbarCreated 再構築／DPI 再構築）は Deskband11Lib が定型化済みで、それを踏襲。Rust での前例は trafficbar がほぼ同一要件（トレイ左・単一exe・GDI・per-pixel α）。

### 4.5 データ監視
- `state.json` の mtime を ~300–500ms ポーリング（監視ウィジェットなので十分）。FS 監視は過剰。

## 5. Python ヘッドレス化の具体
- **削除**: `envmon/flyout.py`, `envmon/widget.py`, `envmon/settings_ui.py`, `tools/preview_ui.py`, `tools/preview_widget.py`, `tools/preview_settings.py`。`taskwidget/`(Python) は役目終了→退役 or 参考保管。
- **追加**: `overlay/`(Rust crate), `envmon/statefile.py`(state.json 書き出し+commands 消費), `envmon/httpconfig.py`(設定HTTP), `envmon/settings.html`, `envmon/validate.py`。
- **変更**:
  - `theme.py`: ctk 依存を外す。`resolve()` は `geometry.system_uses_light_theme()`（既存・レジストリ読取）で light/dark 判定。`SEV_COLOR/SEV_SOFT/SEV_TEXT/LUX` と `_gauge_spec/_display_range`（flyout から移設）を保持。`font()/make_segbar()`(Tk Canvas) は削除。
  - `main.py`: `ctk.CTk()`/`mainloop()`/`root.after` 撤廃。新メインループ＝ poller 起動 + tray(pystray) + HTTP サーバ + overlay 子プロセス spawn + commands ウォッチャ。`on_update` は `statefile.write_state()` を呼ぶ。終了で全停止＋overlay kill。
  - `tray.py`: メニュー実装を差替（開く→visible トグル、設定→HTML を開く、位置リセット→command、更新→poll_now、終了）。
  - `poller.py`: `on_update` が state.json を書く（間隔フォールバックは済）。ロジック不変。
  - 不変: `config.py`(normalize 呼出を追加)/`model.py`/`rules.py`/`notifier.py`/`teams.py`/`icons.py`/`toast.py`。
- **依存**: `customtkinter` を requirements から除去。`tkinter` も不使用に。`pystray`/`Pillow`/`requests`/`windows-toasts`/`pywin32` は残る。

## 6. ビルド・配布
- 2系統: `cargo build --release`（overlay）＋ 既存 PyInstaller。
- `build.ps1`(ASCII限定・メモ既述) に cargo ビルドと overlay.exe の dist 配置を追加。`build/envmon.spec` に overlay.exe を同梱 or dist へコピー。
- ポータブル配布（app_data_dir 方針）は維持。dist に EnvMonitor.exe と envmon-overlay.exe が並ぶ。
- `BUILD.md` 更新。overlay は数百KB〜1MB台想定（WebView系を避けた理由）。

## 7. 段階移行（各フェーズ独立検証・Phase5 までロールバック可）
- **Phase 0（完了）**: 高優先バグ修正（poller 間隔フォールバック / config 保存レース / 静音時の復旧通知 / 設定窓 after ガード / opacity 既定統一）。
- **Phase 1 — Rust PoC（完了）**: `overlay/` 新設。採用方式は当初案の SetParent 埋め込みではなく**最前面レイヤードオーバーレイ追従（camp B）**＝Win11 で SetParent 埋め込みは描画されず不採用（§9 原文と相違。実装進捗の詳細は memory `envmon-ui-direction` を参照）。
- **Phase 2 — 契約確定（完了）**: `overlay.state.json` スキーマ（`{"visible": bool, "chips":[{"label","value","fg"}]}`）を凍結。`overlay_bridge.write_state()` が poller の `on_update` から実データで書き出し。commands/ ディレクトリ方式は不採用（トレイ操作は overlay 自前トレイ＋tray の visible トグルで足りた）。
- **Phase 3 — overlay 本結線（完了）**: `OverlayBridge.start/stop/apply_enabled` で overlay.exe の spawn/stop を `config.overlay.enabled` に追従。state.json の mtime ポーリングで overlay 側が反映。
- **Phase 4 — 設定HTML（完了 2026-11-26, commit e19bdad）**: `httpconfig.py`＋`settings.html`＋`validate.py` を新設。tray「設定」→ `webbrowser.open(ConfigServer.url)` でダッシュボードを開く。`127.0.0.1`＋起動毎トークン（無トークンは 403）。`GET /`(HTML＋token/presets 注入)／`GET /config`／`POST /config`(normalize→replace→poll_now→overlay.apply_enabled)／`GET /status`(接続状態・既知の部屋)／`GET /test`(サーバ側で URL を叩く)。`config.load_config` も同じ `validate.normalize` を通し、手編集 config.json を安全化。接続テスト/プリセット/検証を復活。検証: `tools/_smoke_phase4.py`（validate 補正＋HTTP エンドポイント）。
- **Phase 5 — Tk 撤去（完了 2026-11-26, commit e415fd4・不可逆）**: flyout.py/widget.py/settings_ui.py/tools/preview_* を削除、theme.py は customtkinter 除去＝`resolve()` をレジストリ(`AppsUseLightTheme`)判定へ、main.py は `threading.Event` 待機のヘッドレスループへ、tray.py はメニューを表示トグル/設定/更新/終了に差替、requirements から customtkinter 除去。検証: ヘッドレス起動smoke・`test_logic` 20 PASS・`_smoke_phase4` PASS・import時 tkinter/customtkinter 非ロード確認。
- **Phase 6 — 配布・文書（一部完了 2026-11-26, commit e9e82d2）**: `build/envmon.spec`（customtkinter 同梱除去・`settings.html` を datas に追加・tkinter/customtkinter を excludes へ）、README/BUILD.md/docs(ARCHITECTURE・MODULES) 更新は完了。**残**: `build.ps1` への cargo ビルド＋`envmon-overlay.exe` の dist 配置の自動化、`taskwidget/`(Python) の退役判断、envmon(pystray) と overlay 自前トレイの**トレイ二重化**解消（overlay 側に `TBWIDGET_NO_TRAY` 相当のトレイ無効化オプションを追加し envmon のトレイへ一元化する方針だが、`overlay/` が別セッションでライブ編集中のため着手を見送り中）。

## 8. リスク・残課題（埋め込み主採用で再評価）
- **explorer.exe 再起動で子窓破棄**（最大の実地課題）: `TaskbarCreated` 購読→再構築で対処。PoC の次に実装・検証必須。
- **DPI 変化で位置崩れ**: hide+detach→新DPIで再構築（Deskband11Lib 実証パターン）。Per-Monitor V2。
- **Win11 タスクバー内部変更への脆さ**: 22H2+ で埋め込みが壊れた前例（TrafficMonitor）。子クラス `DesktopWindowContentBridge` 検出で版依存を避け、壊れたらオーバーレイ/float へフォールバック。
- **レイヤード窓のヒットテスト**: `✕`/`⚙` クリック判定（α>0 領域）。ドラッグは埋め込み方式では廃止したので難度は下がる。PoC で確認。
- **z-order 埋没**: WS_CHILD 化で原則自動解決（オーバーレイ副系統を使う時のみ再浮上処理が要る）。
- **overlay プロセスのライフサイクル**: 子クラッシュ検知→Python 再起動 or float フォールバック。孤児プロセス防止。
- **2トールキット・2ビルド・配布肥大**: ただし単一 exe・ランタイム DLL 無し（trafficbar 流）で肥大は限定的。設定もウィジェットも非Tkになり“UI品質の割れ”は解消。
- **非技術者の設定体験**: §2.5 の通り HTML を CodeZeno 的ダッシュボードにして担保（生JSON編集を強制しない）。
- **ローカル HTTP の安全性**: 127.0.0.1 バインド＋起動毎トークン。
- **toast を poller スレッドから呼ぶ既存懸念**（本移行と無関係だが残存。必要なら別途）。

## 9. 決定事項（このセッションでの合意）
- Tk(customtkinter) を全廃し Python をヘッドレス化する。
- ウィジェットは Rust 製の独自タスクバー・ウィジェットエンジン（`taskwidget` の Rust 後継）。**配置は SetParent 子ウィンドウ埋め込みを主**（trafficbar/TrafficMonitor 流）、**追従オーバーレイ/float を副**（フォールバック）。
- Python↔Rust の境界は JSON ファイル（state.json / commands / config.json）、1ファイル1書き手。
- 設定UIは単一の HTML を**CodeZeno 的な親切ダッシュボード**として作る（ローカル HTTP 配信）。JSON は裏の保管庫で、ユーザーに生JSON編集を強制しない。書き手は Python のみ。
- UX 基準は CodeZeno/Claude-Code-Usage-Monitor（トレイ左クリック=トグル / 右クリック=メニュー / ツールチップに状態・エラー / プリセット・接続テストでオンボーディング）。
- 進め方は PoC 先行（Phase1 の透過品質＋埋め込み成立で Go/No-Go）。
- 実装典拠: trafficbar(Rust), TrafficMonitor, Deskband11Lib, NetSpeedTray（§4.4）。
