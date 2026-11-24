# taskwidget

Windows のタスクバーに追従する小さなウィジェットを **お手軽に** 作る Python ライブラリ。

Win11 はタスクバー内へウィジェットを埋め込む公式 API を廃止しているため、本ライブラリは
「タスクバー矩形を検出して、その上へ最前面オーバーレイを重ねて追従させる」方式
（公式系ツールと同じ作法）で“タスクバー常駐風”を実現します。CPU/メモリ、時計、株価、
ビルド状況…など、**定期的に値が変わる小さな情報**を常時チラ見せするのに向いています。

> このライブラリは常駐アプリ **EnvMonitor**（同リポジトリの `envmon/`）のウィジェット部を
> 汎用化して切り出したものです。`envmon` 側もこのライブラリの `geometry` を共有しています。

## インストール

依存は CustomTkinter だけ（タスクバー検出は純 ctypes・Windows 専用）。

```powershell
pip install customtkinter
```

## 最小の例

```python
import time
import taskwidget as tw

app = tw.TaskbarWidget(title="Clock")
clock = app.chip("TIME", "--:--:--")

@app.every(500)                      # 500ms ごとに呼ばれる
def tick():
    clock.update(value=time.strftime("%H:%M:%S"))

app.run()
```

同梱の例をそのまま実行できます:

```powershell
python -m taskwidget.examples.clock           # 時計
python -m taskwidget.examples.system_monitor  # CPU/MEM（psutil があれば実測）
python -m taskwidget.examples.custom_render   # renderer で自由描画
```

## 使い方

### ウィジェットを作る

```python
app = tw.TaskbarWidget(
    title="Monitor",        # float モードのヘッダ名
    dock="taskbar",         # "taskbar"(追従・既定) / "float"(任意位置)
    opacity=0.97,
    taskbar_bg="transparent",   # 既定。地を透明化し文字だけ乗せる（"auto"/色指定も可）
    state_file="~/.myapp/widget.json",  # float 位置・間隔を記憶（任意）
)
```

### 値を出す（チップ）

`chip()` / `gauge()` は **ハンドル** を返します。あとは `update()` で中身を差し替えるだけ
（ウィジェットを毎回作り直さないのでチラつきません）。

```python
cpu = app.chip("CPU", "--")
mem = app.gauge("MEM", "--", frac=0.0)   # セグメントバー付き

cpu.update(value="42%", status="ok")                 # 状態色で強調
mem.update(value="88%", status="warn", frac=0.88)    # バーも連動
```

`status` は `"ok" / "warn" / "critical" / "stale" / "info"`（定数 `tw.OK` なども可）。
任意の色は `color="#ff5577"` で直接指定できます。

### 自由に描く（renderer）

チップで足りない時は、本体フレームを受け取って好きに組み立てられます。

```python
@app.renderer
def draw(body):
    import customtkinter as ctk
    ctk.CTkLabel(body, text="Hello").pack()

@app.every(1000)
def tick():
    app.refresh()     # renderer を描き直す
```

### 表示制御

```python
app.show() / app.hide() / app.toggle()
app.set_dock("float")        # 配置モード切替
app.reset_position()         # 記憶した座標を既定へ戻す
```

### 座標を調整する

ドラッグでも動かせます（taskbar は横＝トレイからの間隔、縦＝ずらし量を記憶／
float は自由位置を記憶。`state_file` 指定時はファイルへ保存）。プログラムからも:

```python
app.set_gap(120)        # taskbar: トレイ左端からの横間隔(px)
app.set_offset_y(-6)    # taskbar: バー中央からの縦ずらし(px, 上がマイナス)
app.move_to(1700, 20)   # float: 左上の絶対座標
app.nudge(dx=4, dy=0)   # 現在モードで微調整（taskbar は dx>0 でトレイへ寄る）
```

初期値は生成時にも渡せます: `TaskbarWidget(gap=16, offset_y=0, ...)`。

### 既存アプリへ組み込む

すでに CustomTkinter の root を持っているアプリに載せる場合は `master=` を渡し、
`run()` の代わりに `show()` を使います（メインループは既存アプリ側のまま）。

```python
app = tw.TaskbarWidget(master=my_root, dock="taskbar")
app.show()
```

## 挙動メモ

- **タスクバー追従**: トレイ(通知領域)の左隣へ出し、`follow_ms`(既定1.2秒)ごとに
  移動/サイズ変化へ追従。**タスクバー高さを超えないよう縦サイズを自動クランプ**します。
- **ドラッグ**: taskbar モードは横だけ動かせて「トレイからの間隔」を記憶（追従は維持）。
  float モードは自由位置を記憶。`state_file` 指定時はファイルへ永続化。
- **フォールバック**: 縦置き/自動非表示などで追従できないタスクバーは、自動的に
  float（右下）表示へ切り替わります。
- **非 Windows**: `find_taskbar()` が `None` を返すため float 表示になります
  （タスクバー検出は Windows 専用）。

## API 早見

| 対象 | 主なもの |
|------|----------|
| `TaskbarWidget` | `chip` / `gauge` / `clear` / `renderer` / `empty_hint` / `every` / `after` / `show` / `hide` / `toggle` / `set_dock` / `set_gap` / `set_offset_y` / `move_to` / `nudge` / `reset_position` / `refresh` / `run` |
| `Chip` | `update(label=, value=, status=, color=, frac=)` |
| `taskwidget.geometry` | `find_taskbar()` → `TaskbarInfo` / `work_area()` / `system_uses_light_theme()` |
| `taskwidget.theme` | 配色トークン・`status_color()`・`make_segbar()`・`font()` |
