"""検証用モックサーバ: /env1.php で JSON配列の配列を返す.

使い方:
    python tools/mock_server.py [port]
環境変数 ENVMON_SCENARIO で返すデータを切替:
    normal (既定) / hot / lowbatt / mixed
"""
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


def now_ts() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S.") + f"{datetime.now().microsecond // 10:05d}"


def records():
    scenario = os.environ.get("ENVMON_SCENARIO", "normal")
    ts = now_ts()
    # [null, ts, sensor_id, 気温, 湿度, 照度lux, 電圧]
    if scenario == "hot":
        return [
            [None, ts, 1, 35.2, 45.0, 800.0, 3.1],   # 会議室A 高温
            [None, ts, 2, 22.0, 50.0, 10.0, 3.0],
        ]
    if scenario == "lowbatt":
        return [
            [None, ts, 1, 24.0, 55.0, 600.0, 3.0],
            [None, ts, 2, 23.0, 52.0, 5.0, 2.4],     # サーバ室 低電圧
        ]
    if scenario == "mixed":
        return [
            [None, ts, 1, 35.2, 45.0, 800.0, 3.1],
            [None, ts, 2, 23.0, 52.0, 5.0, 2.4],
            [None, ts, 3, 21.5, 60.0, 300.0, 3.2],
        ]
    # normal
    return [
        [None, ts, 1, 24.0, 55.0, 600.0, 3.1],
        [None, ts, 2, 22.0, 50.0, 10.0, 3.0],
    ]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/env1.php"):
            body = json.dumps(records()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # 静かに


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(f"mock server on http://127.0.0.1:{port}/env1.php scenario={os.environ.get('ENVMON_SCENARIO','normal')}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
