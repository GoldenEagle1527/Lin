from __future__ import annotations

import sys
import threading

from lingyu.plugins.webui.http import SettingsServer
from lingyu.plugins.webui.startup import fail, read_document, startup_path, webui_bind, StartupError

_server: SettingsServer | None = None
_ready = threading.Event()


def build_server() -> SettingsServer:
    path = startup_path()
    try:
        data = read_document(path)
    except StartupError as exc:
        fail(str(exc))
    host, port = webui_bind(data)
    try:
        return SettingsServer(host, port, path)
    except OSError as exc:
        fail(f"无法在 {host}:{port} 监听：{exc.strerror or exc}")


def active_server() -> SettingsServer | None:
    return _server


def server_ready() -> threading.Event:
    return _ready


def main() -> None:
    global _server
    _ready.clear()
    server = build_server()
    _server = server
    _ready.set()
    host = server.bind_host
    port = int(server.server_address[1])
    shown = f"[{host}]" if ":" in host else host
    print(f"凌雨设置页 http://{shown}:{port}/", file=sys.stderr, flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("\n已停止", file=sys.stderr)
    finally:
        _server = None
        server.server_close()
