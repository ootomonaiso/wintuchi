"""設定ファイルのロード/セーブと既定値生成.

%APPDATA%\\EnvMonitor\\config.json に保存する。
GUI スレッドと poller スレッドの双方から読まれるため、アクセスは Config.lock で保護する。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_DIR_NAME = "EnvMonitor"


def _exe_dir() -> Path:
    """実行ファイル（配布 exe）が置かれているフォルダ。ソース実行時はプロジェクト直下。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # ソース実行: run_envmon.py のある場所（= パッケージの1つ上）
    return Path(__file__).resolve().parent.parent


def app_data_dir() -> Path:
    """設定・ログの保存先を決める。

    優先順位:
      1. 環境変数 ENVMON_DATA_DIR（明示指定）
      2. **ポータブル**: exe と同じフォルダに config.json があればそこを使う
         （フォルダごとコピーして別PCへ持ち運べる）
      3. 既定: %APPDATA%\\EnvMonitor
    """
    override = os.environ.get("ENVMON_DATA_DIR")
    if override:
        d = Path(override)
    elif (_exe_dir() / "config.json").exists():
        d = _exe_dir()  # ポータブル運用
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_data_dir() / "config.json"


def sensors_path() -> Path:
    """センサID→部屋 対応表の専用ファイル（外部で一括編集可）。"""
    return app_data_dir() / "sensors.json"


def log_path() -> Path:
    return app_data_dir() / "envmon.log"


DEFAULT_ROOM: dict[str, Any] = {
    # 各指標の上下限。min/max が null の項目は判定しない。
    # ※電圧は監視対象外のためしきい値を持たない。
    "temp": {"min": 10.0, "max": 30.0},
    "humid": {"min": 30.0, "max": 70.0},
    # 照度ゲート: mode = "off" | "above" | "below"
    #   above: 照度 >= value のときのみ通知（照明ON=在室中のみ通知など）
    #   below: 照度 <= value のときのみ通知（消灯中のみ通知など）
    "lux_gate": {"mode": "off", "value": 50.0},
    # この部屋で有効にする通知チャネル
    "channels": {"toast": True, "teams": True},
    # 停止検知もこの部屋で有効にするか
    "stale_enabled": True,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "url": "http://localhost/env1.php",
    "poll_interval_sec": 30,
    "request_timeout_sec": 10,
    "teams_webhook_url": "",
    "cooldown_minutes": 15,
    "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
    "stale_minutes": 10,
    "run_at_startup": False,
    # 状態の呼び方（UI表示・Teams通知に反映。好きな言葉へ変更可）
    "labels": {"ok": "正常", "warn": "注意", "critical": "要確認", "stale": "応答なし"},
    # 状態色（トレイアイコン・ウィジェットの文字色に反映。#RGB/#RRGGBB で指定）
    "colors": {"ok": "#3BA55D", "warn": "#E8A33D", "critical": "#E24C4C",
               "stale": "#8A8A8A", "lux": "#4A90D9"},
    # 閾値付近のバタつき防止に使うヒステリシス幅（各指標の実単位）
    "hysteresis": {"temp": 0.5, "humid": 2.0},
    # センサID(文字列) -> 部屋名
    "sensors": {},
    # 部屋名 -> ルーム設定(DEFAULT_ROOM と同形)
    "rooms": {},
    # デスクトップ常駐ウィジェット
    "widget": {
        "enabled": False,
        # 表示する項目: [{"room": "会議室A", "metric": "temp"}, ...]
        "items": [],
        # 配置モード: "taskbar"=タスクバーに重ねて追従（既定） / "float"=任意位置に浮遊
        "dock": "taskbar",
        # float モードで記憶した表示位置（画面座標）
        "pos": None,
        # taskbar モードでのトレイ左端からの間隔(px)。ドラッグで横移動すると記憶。
        "taskbar_gap": 8,
        "opacity": 0.96,
    },
    # Rust 製タスクバーオーバーレイ（別プロセス）。詳細は overlay/README.md。
    "overlay": {
        # 起動時に overlay.exe を立ち上げ、ポーリング毎に state.json を書く。
        "enabled": True,
        # overlay.exe の明示パス（空なら EnvMonitor exe と同じ場所／環境変数を探索）。
        "exe": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """base を override で再帰マージした新しい dict を返す（override 優先）。"""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    """スレッドセーフな設定ホルダ."""

    def __init__(self, data: dict[str, Any]):
        self.lock = threading.RLock()
        # ファイル書き込みを直列化する専用ロック（poller/GUI の同時保存対策）。
        self._save_lock = threading.Lock()
        self._data = data
        self._sensors_mtime: float = 0.0

    # --- 読み取り（呼び出し側はできるだけ snapshot を使う） ---
    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            return copy.deepcopy(self._data.get(key, default))

    def room_config(self, room_name: str) -> dict[str, Any]:
        """部屋の設定を既定値で補完して返す。"""
        with self.lock:
            rc = self._data.get("rooms", {}).get(room_name, {})
            return _deep_merge(DEFAULT_ROOM, rc)

    def room_for_sensor(self, sensor_id: int) -> str:
        with self.lock:
            name = self._data.get("sensors", {}).get(str(sensor_id))
        return name or f"センサ{sensor_id}"

    def sensors(self) -> dict[str, str]:
        with self.lock:
            return dict(self._data.get("sensors", {}))

    # --- 書き込み ---
    def replace(self, new_data: dict[str, Any]) -> None:
        """設定全体を差し替えて保存する（設定画面の保存で使用）。

        ※sensors.json はユーザー専用（アプリは書き換えない）。ここでも触らない。
        """
        merged = _deep_merge(DEFAULT_CONFIG, new_data)
        with self.lock:
            self._data = merged
        self.save()

    def update(self, **kwargs: Any) -> None:
        with self.lock:
            self._data.update(kwargs)
        self.save()

    def set_sensors(self, mapping: dict[str, str]) -> None:
        """対応表の読み取りキャッシュ（config.json 側）だけ更新する。

        sensors.json はユーザーが手で用意する権威ファイルであり、アプリは書き換えない。
        """
        with self.lock:
            self._data["sensors"] = dict(mapping)
        self.save()

    def save(self) -> None:
        # 書き込み自体を直列化（poller スレッドの reload_sensors と
        # GUI の保存が同時に走っても tmp ファイルを壊さない）。
        data = self._snapshot_for_save()
        with self._save_lock:
            self._atomic_write(config_path(), data)

    def _snapshot_for_save(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._data)

    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        # tmp 名にプロセス/スレッド固有の接尾辞を付け、万一同時書き込みが
        # 起きても互いの中間ファイルを踏まないようにする。
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as e:
            log.error("ファイル保存に失敗(%s): %s", path.name, e)
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # --- センサ対応表（sensors.json）---
    # ※sensors.json はユーザー専用の権威ファイル。アプリは読むだけで書き込まない。
    def reload_sensors(self) -> bool:
        """sensors.json が外部編集されていれば読み込んで反映。変更時 True。"""
        path = sensors_path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if mtime == self._sensors_mtime:
            return False
        try:
            with open(path, encoding="utf-8-sig") as f:
                mapping = json.load(f)
            if not isinstance(mapping, dict):
                raise ValueError("sensors.json はオブジェクトである必要があります")
            # キーは文字列、値は部屋名(文字列)へ正規化
            mapping = {str(k): str(v) for k, v in mapping.items() if v}
        except (OSError, json.JSONDecodeError, ValueError) as e:
            log.error("sensors.json の読込に失敗: %s", e)
            self._sensors_mtime = mtime  # 壊れたファイルで再試行し続けない
            return False
        with self.lock:
            self._data["sensors"] = mapping
        self._sensors_mtime = mtime
        # config.json のキャッシュも更新
        self.save()
        log.info("sensors.json を再読込（%d件）", len(mapping))
        return True


def load_config() -> Config:
    path = config_path()
    if path.exists():
        try:
            # utf-8-sig: メモ帳等が付与する BOM を許容する
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.error("設定の読込に失敗。既定値を使用: %s", e)
            data = copy.deepcopy(DEFAULT_CONFIG)
    else:
        data = copy.deepcopy(DEFAULT_CONFIG)
    # 型/範囲フォールバック（手編集 config.json を安全化）。UI門番の代替。
    # ※循環 import を避けるため関数内 import。
    from .validate import normalize
    data, warnings = normalize(data)
    for w in warnings:
        log.warning("設定の正規化: %s", w)
    cfg = Config(data)
    if not path.exists():
        cfg.save()

    # センサ対応表: sensors.json はユーザーが用意する権威ファイル。
    # あれば読み込む。無ければアプリは作らない（ユーザーが後から置けば自動反映）。
    if sensors_path().exists():
        cfg.reload_sensors()
    return cfg
