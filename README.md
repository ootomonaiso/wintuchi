# 環境モニタ常駐ソフト (EnvMonitor)

`/env1.php` が配信する環境モニタ（気温・湿度・照度・電圧）を定期取得し、部屋ごとの
条件を満たしたら **Windowsトースト / Teams(Power Automate) / トレイアイコンの色** で
通知する、タスクトレイ常駐アプリです。Windows ログオン時に自動起動できます。

本体（取得・判定・通知・トレイ）は **GUI ツールキットに依存しないヘッドレス Python**。
タスクバーに追従する**表示ウィジェットは Rust 製の別プロセス `envmon-overlay.exe`**
（`overlay/`）が担い、本体が状態を `overlay.state.json` に書き出して連携します。
**設定は HTML ダッシュボード**（トレイ「設定…」→ ローカル HTTP をブラウザで開く）で行います。

![tray](envmon/assets/app.ico)

## 主な機能
- **タスクトレイ常駐**：トレイアイコンの色で最悪状態を一目表示（正常/注意/要確認）。
  右クリックメニューから「オーバーレイ表示/非表示」「設定…」「今すぐ更新」「終了」。
  ツールチップに「N部屋 / M件のアラート」の概況。
- **常駐ウィジェット（タスクバー追従・Rust 製 overlay）**：選んだ「部屋 × 指標」を
  `部屋名` と `値`（例 `35.2℃`）のチップで常時表示。タスクバー矩形(Shell_TrayWnd)と
  システムトレイ(TrayNotifyWnd)を検出してトレイ左隣へ重ね、追従します。異常は**値の
  文字色（橙/赤）**で表現。本体とは別プロセスで、本体が色解決済みチップを
  `overlay.state.json` に書き、overlay は描くだけ（表示内容を解釈しない）。
  配置・透過・ドラッグ等の詳細は [`overlay/README.md`](overlay/README.md)。
  ※Win11 はウィジェット埋め込み API が無いため、公式ツール同様オーバーレイ方式。
- **設定は HTML ダッシュボード**：トレイ「設定…」でローカル HTTP の設定画面が
  ブラウザで開く（`127.0.0.1`＋起動毎トークンで保護）。保存時に全項目の型/範囲を
  検証・正規化してから `config.json` に書き込みます。接続テスト・プリセットも同梱。
- **状態の呼び方は自由**：「異常」のような強い言葉がしっくりこなければ、設定の
  「状態の呼び方」で好きな名前へ（既定は 正常 / 注意 / 要確認 / 応答なし）。
  トーン違いの**プリセット**（やわらかめ / ふつう / きっちり / 英語）をワンクリックで適用でき、
  決めた名前は表示と Teams 通知の両方に反映されます。
- **しきい値プリセット**：「快適な居室」「サーバー室」「冷蔵・保冷」「温室・植物」
  「ゆるめ」「きっちり監視」などを選ぶと、上下限を一発で流し込めます（後から微調整可）。
- **部屋ごとの詳細設定**：気温・湿度の上下限、通知チャネルON/OFF（電圧は監視対象外）。
- **照度ゲート**：「照度≧指定時のみ通知」「照度≦指定時のみ通知」を部屋ごとに選択。
  例）消灯中の無人部屋は通知を抑制／照明つけっぱなし検知に利用。
- **通知スパム対策**：同一アラートのクールダウン、夜間などの静音時間(Do Not Disturb)、
  閾値付近のヒステリシス。
- **センサ停止検知**：一定時間データが更新されないセンサを「停止」として通知。
- **通知チャネル**：Windowsトースト / Teams Webhook(Power Automate)。状態はトレイ
  アイコンの色とウィジェットの値の色でも常時わかります。
- **自動起動**：設定トグルで HKCU...\Run に登録/解除。

## データ形式（/env1.php）
JSON の「配列の配列」を返す前提。1レコード：
```
[null, "2022/02/17 12:55:55.21793", <センサID 1-99>, <気温>, <湿度>, <照度lux>, <電圧>]
```
同一センサIDの複数行が来た場合は、**タイムスタンプ最大の1件**を現在値として採用します。
対応表(`sensors.json`)に無いセンサIDは `センサ<ID>` の仮名で表示されます（アプリは
対応表を書き換えないので、名前を付けたい場合は `sensors.json` を編集してください）。

## セットアップ（ソース実行）
```powershell
python -m venv .venv          # ※OneDrive配下だと同期ロックで失敗することがある。
                              #   その場合は OneDrive 外（例 C:\Users\<you>\envmon-venv）に作る。
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_envmon.py
```

## .exe のビルド
```powershell
pyinstaller build\envmon.spec --distpath dist --workpath build\_work --noconfirm
# 生成物: dist\EnvMonitor.exe （単一ファイル・ウィンドウなし・トレイ常駐）
```
- 既定は onefile。起動の初動速度を優先するなら `build\envmon.spec` の `ONEFILE = False`
  にして onedir ビルド（フォルダ配置）に切替可能。
- 表示ウィジェット `envmon-overlay.exe`（Rust）は別途 `cargo build --release` で作り、
  `EnvMonitor.exe` と同じ場所に置く（本体が起動時に自動 spawn）。詳細は
  [`overlay/README.md`](overlay/README.md)、配布手順は [`BUILD.md`](BUILD.md)。

## 自動起動（スタートアップ）
設定ダッシュボードの「Windows ログオン時に自動起動」をON（＝`HKCU\...\Run` に登録）。
手動で置きたい場合は `Win+R` → `shell:startup` に `dist\EnvMonitor.exe` のショートカットを置く。

## 設定ファイル
`%APPDATA%\EnvMonitor\config.json`（初回起動で自動生成）。メモ帳で編集可（BOM付きでも可）。
ログは `%APPDATA%\EnvMonitor\envmon.log`。

### センサ対応表 (`sensors.json`)
センサID→部屋名の対応表は専用ファイル `%APPDATA%\EnvMonitor\sensors.json` に保存されます
（99台など大量のセンサを一括管理しやすいように独立ファイル化）。
```json
{
  "1": "会議室A",
  "2": "サーバ室",
  "3": "応接室"
}
```
- この対応表は **ユーザー専用の権威ファイル**です。アプリは**読むだけで書き換えません**
  （自動登録もしません）。内容はあなたが用意・編集します。
- **外部で直接編集**して保存すると、次のポーリング周期（既定30秒以内）で**自動反映**されます
  （アプリ再起動不要。壊れたJSONは無視して直前の対応表を維持）。
- 設定ダッシュボードの「センサと部屋の対応」では、現在読み込まれている対応表を
  **読み取り専用で確認**でき、`sensors.json` のフォルダを開いて編集に進めます。

## Power Automate 連携（Teams カスタム通知）
1. Power Automate で「**自動化したクラウド フロー**」を作成し、トリガに
   「**HTTP 要求の受信時 (When a HTTP request is received)**」を選択。
2. 保存すると発行される **HTTP POST URL** を、設定画面の「Teams Webhook URL」に貼り付け。
3. 本アプリは以下の JSON を POST します（Teams の Workflows チャネル投稿テンプレートが
   そのまま解釈できる Adaptive Card 形式 ＋ カスタムフロー用の素データ `data` を同梱）:
```json
{
  "type": "message",
  "attachments": [
    { "contentType": "application/vnd.microsoft.card.adaptive", "content": { "...AdaptiveCard..." } }
  ],
  "data": {
    "room": "会議室A", "metric": "temp", "severity": "警告",
    "severity_level": 1, "value": 35.2,
    "message": "会議室A 気温: 35.2℃（超過 / 閾値30℃）",
    "timestamp": "2026/11/24 22:10:00"
  }
}
```
4. フロー側では `triggerBody()?['data']?['room']` などで値を取り出し、Teams 投稿や
   モバイル通知など任意のアクションに繋げます。
   - Teams の「Workflows」アプリの既製テンプレート（Webhook→チャネル投稿）を使う場合は
     `attachments` がそのまま使われます。

## 動作確認（開発者向け）
```powershell
# ロジックのユニット的検証（GUI不要）
.\<venv>\Scripts\python.exe tools\test_logic.py
# モックサーバを立てて実データ経路を検証
$env:ENVMON_SCENARIO="hot"   # normal/hot/lowbatt/mixed
.\<venv>\Scripts\python.exe tools\mock_server.py 8099
.\<venv>\Scripts\python.exe tools\test_integration.py
```

## 構成
```
envmon/      ヘッドレス本体
  config/model/poller/rules/notifier/toast/teams  … 取得・判定・通知
  tray                                            … pystray トレイ
  httpconfig/settings.html/validate               … 設定ダッシュボード(HTTP+HTML)＋検証
  overlay_bridge                                  … 状態→state.json＋overlay.exe spawn/stop
  theme/startup/icons                             … 配色トークン・自動起動・トレイ画像
overlay/     表示ウィジェット（Rust。tbwidget エンジン＋envmon-overlay バイナリ）
tools/       モックサーバ・テスト
build/       PyInstaller spec
run_envmon.py  ソース実行用ランチャ
```

> 旧 Tk(customtkinter) 版の flyout / widget / settings_ui は撤去済み。表示は `overlay/`、
> 設定は `httpconfig`＋`settings.html` が置き換えています。`taskwidget/`（Python 製の
> タスクバー追従ライブラリ）は overlay へ役目を移したため現在アプリからは未使用です。

## 開発者向けドキュメント
コードを読む・手を入れる場合は `docs/` を参照してください。

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 全体像・起動シーケンス・データフロー
  （`/env1.php`→poller→rules→notifier）・スレッドモデル・状態管理。
- [`docs/MODULES.md`](docs/MODULES.md) — `envmon/`・`taskwidget/`・`tools/` の
  モジュール別リファレンス（責務・主要クラス/関数の早見表）。

## 既知の制約
- Windows 11 は旧式の「タスクバー内埋め込みウィジェット(deskband)」API を廃止しているため、
  厳密な意味での“タスクバー内蔵”はできません。本アプリは公式の類似ツールと同じく、
  **タスクバー矩形を検出してその上に最前面オーバーレイを重ね、追従させる**方式で
  見た目上のタスクバー常駐を実現しています（タスクバー追従ウィジェット）。
- タスクバーが縦置き（左右配置）や自動的に隠れる設定の場合は、追従配置が使えないため
  自動的に「任意位置（浮遊）」として右下に表示します。
