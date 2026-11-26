# ビルド & 配布ガイド（別環境向け）

EnvMonitor を別の Windows PC でビルド・配布するための手順をまとめます。

> 機能・使い方は [`README.md`](README.md)、コード内部の構成は
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) / [`docs/MODULES.md`](docs/MODULES.md) を参照。

## 1. 必要なもの
- Windows 10/11
- Python 3.11〜3.13（64bit）
- 依存パッケージ（`requirements.txt`）
  - pystray / pillow / requests / windows-toasts / pywin32 / pyinstaller
  - ※ GUI ツールキット（Tk/customtkinter）には依存しません（ヘッドレス化済み）。
- 表示ウィジェットは Rust 製の別プロセス `envmon-overlay.exe`（`overlay/`）。
  ビルドには Rust ツールチェイン（`cargo`）が必要。ビルド手順は
  [`overlay/README.md`](overlay/README.md) を参照。

## 2. 環境構築（初回のみ）
```powershell
# ※OneDrive 配下に venv を作ると同期ロックで失敗することがある。OneDrive 外に作る。
python -m venv C:\Users\<you>\envmon-venv
C:\Users\<you>\envmon-venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. ソースから起動（開発時）
```powershell
C:\Users\<you>\envmon-venv\Scripts\python.exe run_envmon.py
```

## 4. exe をビルド
ワンコマンド（推奨）:
```powershell
.\build.ps1
```
`build.ps1` は PyInstaller でビルドし、`dist\` に配布用ファイル
（`config.json` / `sensors.json` / `README-配布.txt` / `*.sample.json`）を揃えます。

手動で行う場合:
```powershell
pyinstaller build\envmon.spec --distpath dist --workpath build\_work --noconfirm
copy packaging\config.sample.json  dist\config.json
copy packaging\sensors.sample.json dist\sensors.json
copy packaging\README-deploy.txt   dist\
```
生成物: `dist\EnvMonitor.exe`（単一ファイル・ウィンドウなし・トレイ常駐）。
`build\envmon.spec` の `ONEFILE = False` で onedir ビルド（フォルダ配置）に切替可。

**表示ウィジェット（overlay）の同梱:** `EnvMonitor.exe`（Python 本体）はヘッドレスで、
表示は別プロセスの `envmon-overlay.exe` が担います。`cargo build --release`
（詳細は `overlay/README.md`）で作った `envmon-overlay.exe` を **`dist\` の
`EnvMonitor.exe` と同じ場所**に置くと、本体が起動時に自動で spawn します
（置き場所は `config.json` の `overlay.exe` か環境変数 `ENVMON_OVERLAY_EXE` でも指定可）。
見つからなければ overlay 無しで本体（取得・判定・通知・トレイ）は動きます。

## 5. 配布 & 別PCでの実行（ポータブル）
`dist\` フォルダごと相手の PC へコピーし、`EnvMonitor.exe` を実行するだけ。

**設定の保存先の決まり方（`envmon/config.py` の `app_data_dir`）:**
1. 環境変数 `ENVMON_DATA_DIR` があればそこ
2. **exe と同じフォルダに `config.json` があれば、そのフォルダ**（＝ポータブル動作）
3. どちらも無ければ `%APPDATA%\EnvMonitor`

→ 配布 `dist\` には `config.json` を同梱しているので、コピーしたフォルダで
そのままポータブル動作します（設定・ログもそのフォルダ内）。
`%APPDATA%` に保存したい場合は `dist\config.json` を削除してください。

## 6. 設定ファイル（すべて JSON）
| ファイル | 役割 | 誰が編集 |
|---|---|---|
| `config.json` | アプリ設定全般（URL・しきい値・通知・ウィジェット・状態の呼び方 …） | ユーザー／設定ダッシュボードの両方 |
| `sensors.json` | センサID → 部屋名 の対応表 | **ユーザーのみ**（アプリは読むだけ・書き換えない） |
| `envmon.log` | 動作ログ | 自動 |

- 設定ダッシュボードで変更した内容は `config.json` に保存されます。JSON を直接編集してもOK。
  （トレイ「設定…」→ ローカル HTTP の HTML ダッシュボードがブラウザで開く。`127.0.0.1`
  バインド＋起動毎トークンで保護。入力は保存時に型/範囲を検証・正規化。）
- `sensors.json` は保存すると次の取得周期（既定30秒以内）で自動反映。壊れたJSONは無視。
- テンプレートは `packaging\config.sample.json` / `packaging\sensors.sample.json`。

## 7. 自動起動
設定ダッシュボードの「Windows にログイン時に自動で起動」をONにすると `HKCU\...\Run` に登録します。
ポータブル運用なら、コピー先の `EnvMonitor.exe` のショートカットを
`shell:startup` に置く方法でもOK。

## 8. 常駐の見え方（トレイ）
- タスクバーのボタンは作りません（トレイ常駐アプリ）。
- トレイアイコンは Windows 11 では既定で「隠れているインジケーター（^）」に入ります。
  常時表示したい場合は ^ を開いてアイコンを時計の並びへドラッグしてください。
