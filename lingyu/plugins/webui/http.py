from __future__ import annotations

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from lingyu.plugins.webui.constants import MAX_BODY, SAVED_NOTE
from lingyu.plugins.webui.edits import apply_edits
from lingyu.plugins.webui.page import render_failure, render_page
from lingyu.plugins.webui.startup import StartupError, read_document, replace_startup


class SettingsHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server: SettingsServer

    def version_string(self) -> str:
        return "LingyuSettings"

    def do_GET(self) -> None:
        if not self._is_root():
            self._send_page(404, render_failure("没有这个页面。"))
            return
        try:
            document = read_document(self.server.startup)
        except StartupError as exc:
            self._send_page(200, render_failure(str(exc)))
            return
        self._send_page(200, render_page(document, self.server.startup))

    def do_POST(self) -> None:
        if not self._is_root():
            self._send_page(404, render_failure("没有这个页面。"))
            return
        try:
            form = self._read_form()
        except ValueError as exc:
            self._send_page(200, render_failure(str(exc)))
            return
        try:
            with self.server.save_lock:
                document = read_document(self.server.startup)
                updated, errors = apply_edits(document, form)
                if not errors and updated is not None:
                    replace_startup(self.server.startup, updated)
                    document = updated
                    notice = SAVED_NOTE
                    form_view = None
                else:
                    notice = None
                    form_view = form
        except StartupError as exc:
            self._send_page(200, render_failure(str(exc)))
            return
        except OSError as exc:
            self._send_page(200, render_failure(f"写入失败：{exc.strerror or exc}"))
            return
        self._send_page(
            200,
            render_page(
                document,
                self.server.startup,
                errors=errors,
                notice=notice,
                form=form_view,
            ),
        )

    def _is_root(self) -> bool:
        return urlsplit(self.path).path in {"", "/"}

    def _read_form(self) -> dict[str, str]:
        length_raw = self.headers.get("Content-Length", "")
        try:
            length = int(length_raw)
        except ValueError as exc:
            raise ValueError("无法读取提交内容，没有写入") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("提交内容过大，没有写入")
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("提交内容不是 UTF-8，没有写入") from exc
        parsed = parse_qs(text, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _send_page(self, status: int, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[设置页] {self.address_string()} {fmt % args}", file=sys.stderr)


class SettingsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, startup: Path) -> None:
        if host == "::1":
            self.address_family = socket.AF_INET6
        self.bind_host = host
        self.startup = startup
        self.save_lock = threading.Lock()
        super().__init__((host, port), SettingsHandler)
