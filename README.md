# 環境モニタ常駐ソフト (EnvMonitor)

`/env1.php` が配信する環境モニタ（気温・湿度・照度・電圧）を定期取得し、部屋ごとの
条件を満たしたら **Windowsトースト / Teams(Power Automate) / トレイ＆フライアウトの
バッジ** で通知する、タスクトレイ常駐アプリです。Windows ログオン時に自動起動できます。

![tray](envmon/assets/app.ico)

## 主な機能
- **タスクトレイ常駐**：トレイアイコンをクリックすると、トレイ付近に部屋カードの
  フライアウトが開く。先頭に概況ピル（「すべて正常」「2件 要確認」など）を表示し、
  各カードは左の状態アクセントバー＋淡色の状態バッジ＋セグメント（ブロック）バーで
  値を見せる、Claude-Code-Usage-Monitor 風のコンパクトなUI。アイコン色も状態を表す。
- **状態の呼び方は自由**：「異常」のような強い言葉がしっくりこなければ、設定の
  「状態の呼び方」で好きな名前へ（既定は 正常 / 注意 / 要確認 / 応答なし）。
  トーン違いの**プリセット**（やわらかめ / ふつう / きっちり / 英語）をワンクリックで適用でき、
  決めた名前は画面と Teams 通知の両方に反映されます。
- **しきい値プリセット**：部屋タブで「快適な居室」「サーバー室」「冷蔵・保冷」「温室・植物」
  「ゆるめ」「きっちり監視」などを選ぶと、上下限を一発で流し込めます（後から微調整可）。
- **常駐ウィジェット（タスクバー追従）**：選んだ「部屋 × 指標」を、`部屋名` と `値`（例 `35.2℃`）の
  **縦2行チップ**で常時表示するミニ窓。指標名は単位（℃/%/lx）で分かるので省略し、異常は
  **値の文字色（橙/赤）だけ**で表します。2 モード:
  - **タスクバーの上に出す（追従・既定）**：タスクバー矩形(Shell_TrayWnd)とシステムトレイ
    (TrayNotifyWnd)を検出し、トレイの左隣へオーバーレイ。**背景は透明**でタスクバーに溶け込み、
    **タスクバー高さ内に必ず収まるよう縦サイズを自動クランプ**（はみ出し防止）、1.2 秒間隔で
    移動/サイズ変化に追従。文字をドラッグすると**タスクバー内で横移動**でき、位置（トレイ左端
    からの間隔 `widget.taskbar_gap`）を記憶します。
    ※Win11 はウィジェット埋め込み API が無いため、公式ツール同様オーバーレイ方式。
  - **好きな位置に置く（浮遊）**：常に最前面・ドラッグ移動可・位置記憶。
  設定の「ウィジェット」タブで表示項目と配置モードを選び、トレイメニュー
  「ウィジェット表示/非表示」でON/OFF。
- **部屋ごとの詳細設定**：気温・湿度の上下限、通知チャネルON/OFF（電圧は監視対象外）。
- **照度ゲート**：「照度≧指定時のみ通知」「照度≦指定時のみ通知」を部屋ごとに選択。
  例）消灯中の無人部屋は通知を抑制／照明つけっぱなし検知に利用。
- **通知スパム対策**：同一アラートのクールダウン、夜間などの静音時間(Do Not Disturb)、
  閾値付近のヒステリシス。
- **センサ停止検知**：一定時間データが更新されないセンサを「停止」として通知。
- **3チャネル通知**：Windowsトースト / Teams Webhook(Power Automate) / フライアウトバッジ。
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
# 生成物: dist\EnvMonitor.exe （単一ファイル・ウィンドウなし）
```
- 既定は onefile。起動の初動速度を優先するなら `build\envmon.spec` の `ONEFILE = False`
  にして onedir ビルド（フォルダ配置）に切替可能。

## 自動起動（スタートアップ）
設定画面の「Windows ログオン時に自動起動」をON（＝`HKCU\...\Run` に登録）。
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
- 設定画面の「センサと部屋の対応」では、現在読み込まれている対応表を**読み取り専用で確認**でき、
  「sensors.json のフォルダを開く」ボタンから編集に進めます。

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
envmon/      アプリ本体（config/model/poller/rules/notifier/toast/teams/tray/flyout/settings_ui/startup/icons）
taskwidget/  タスクバー追従ウィジェットの汎用ライブラリ（envmon のウィジェット部を切り出し）
tools/       モックサーバ・テスト
build/       PyInstaller spec
run_envmon.py  ソース実行用ランチャ
```

### 汎用ライブラリ `taskwidget/`
タスクバーに追従する小さなウィジェットを数行で作れる、アプリ非依存のライブラリ。
EnvMonitor のウィジェット機構（タスクバー検出・追従・クランプ・ドラッグ・透過）を
汎用化したもので、`envmon/widget.py` もこのライブラリの `geometry` を共有している。
詳細とサンプルは [`taskwidget/README.md`](taskwidget/README.md)。

```powershell
python -m taskwidget.examples.clock           # 時計
python -m taskwidget.examples.system_monitor  # CPU/MEM
```

## 既知の制約
- Windows 11 は旧式の「タスクバー内埋め込みウィジェット(deskband)」API を廃止しているため、
  厳密な意味での“タスクバー内蔵”はできません。本アプリは公式の類似ツールと同じく、
  **タスクバー矩形を検出してその上に最前面オーバーレイを重ね、追従させる**方式で
  見た目上のタスクバー常駐を実現しています（タスクバー追従ウィジェット）。
- タスクバーが縦置き（左右配置）や自動的に隠れる設定の場合は、追従配置が使えないため
  自動的に「任意位置（浮遊）」として右下に表示します。
