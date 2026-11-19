"""本机设置页。

不进音频环，也不读写 JSON-RPC。启动文件由环境变量 LINGYU_STARTUP 给出。
只监听回环地址。页面可以改 flow，以及 serve、listen 里每个槽的 config。
command 只显示，保存时按文件里的原样写回。
"""

from __future__ import annotations

import copy
import html
import json
import math
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn
from urllib.parse import parse_qs, quote, urlsplit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 1_048_576
LOOPBACK_NOTE = "只允许回环地址 127.0.0.1、localhost、::1。"
SAVED_NOTE = "已保存。流程数字下一轮生效，更换插件配置需要重启进程。"

GROUPS = ("serve", "listen")
GROUP_TITLES = {"serve": "对话服务", "listen": "本地听写"}
SLOT_LABELS = {
    "wake": "唤醒",
    "segment": "切句",
    "asr": "转写",
    "agent": "对话",
    "speaker": "朗读",
    "webui": "设置页",
}

_server: SettingsServer | None = None
_ready = threading.Event()


class StartupError(Exception):
    """启动文件这次读不出来。不要因此退出已经在跑的设置页。"""


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def loopback_host(host: str) -> str | None:
    raw = host.strip()
    if raw.lower() == "localhost":
        return "localhost"
    if raw == "127.0.0.1":
        return "127.0.0.1"
    if raw.strip("[]") == "::1":
        return "::1"
    return None


def require_loopback(host: str) -> str:
    normalized = loopback_host(host)
    if normalized is None:
        shown = host.strip() or host
        fail(f"拒绝绑定 {shown}：{LOOPBACK_NOTE}")
    return normalized


def api_key_status() -> str:
    """只回答环境变量是否非空，不返回密钥本身。"""
    value = os.environ.get("SILICONFLOW_API_KEY", "")
    if isinstance(value, str) and value.strip():
        return "已设置"
    return "未设置"


def startup_path() -> Path:
    raw = os.environ.get("LINGYU_STARTUP")
    if raw is None or not str(raw).strip():
        fail("缺少环境变量 LINGYU_STARTUP。请把它设为启动文件的绝对路径。")
    path = Path(str(raw).strip())
    if not path.is_absolute():
        fail(f"LINGYU_STARTUP 必须是启动文件的绝对路径，当前是：{path}")
    if not path.is_file():
        fail(f"找不到启动文件：{path}")
    return path


def read_document(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise StartupError(f"无法读取启动文件：{exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StartupError(f"启动文件不是合法 JSON（第 {exc.lineno} 行）") from exc
    if not isinstance(data, dict):
        raise StartupError("启动文件的顶层必须是 JSON 对象")
    return data


def webui_bind(data: dict) -> tuple[str, int]:
    config: dict = {}
    serve = data.get("serve")
    if isinstance(serve, dict):
        slot = serve.get("webui")
        if isinstance(slot, dict):
            raw_config = slot.get("config", {})
            if not isinstance(raw_config, dict):
                fail("serve.webui.config 必须是 JSON 对象")
            config = raw_config
    if "host" in config:
        host_value = config["host"]
        if not isinstance(host_value, str):
            fail("serve.webui.config.host 必须是字符串")
        host = require_loopback(host_value)
    else:
        host = DEFAULT_HOST
    if "port" in config:
        port_value = config["port"]
        if isinstance(port_value, bool) or not isinstance(port_value, int):
            fail("serve.webui.config.port 必须是整数")
        port = port_value
    else:
        port = DEFAULT_PORT
    if not 1 <= port <= 65535:
        fail(f"拒绝绑定：端口 {port} 超出范围")
    return host, port


def config_field(group: str, slot: str) -> str:
    return f"cfg.{group}.{quote(slot, safe='')}"


def parse_seconds(raw: str, label: str) -> tuple[int | float | None, str | None]:
    text = raw.strip()
    if not text:
        return None, f"{label}不能为空"
    try:
        value = float(text)
    except ValueError:
        return None, f"{label}必须是数字"
    if not math.isfinite(value) or value < 0:
        return None, f"{label}必须是大于等于 0 的数字"
    if "." in text or "e" in text.lower():
        return value, None
    return int(value), None


def validate_webui_config(config: dict) -> str | None:
    if "host" in config:
        host = config["host"]
        if not isinstance(host, str) or loopback_host(host) is None:
            return "serve.webui.config.host 只能是 127.0.0.1、localhost 或 ::1，没有写入"
    if "port" in config:
        port = config["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return "serve.webui.config.port 必须是 1 到 65535 的整数，没有写入"
    return None


def apply_edits(document: dict, form: dict[str, str]) -> tuple[dict | None, list[str]]:
    """返回新文档。有任何错误就不返回文档，调用方不得写文件。"""
    errors: list[str] = []
    if "flow" in document and not isinstance(document["flow"], dict):
        errors.append("flow 不是对象，没有写入")

    follow: int | float | None = None
    preroll: int | float | None = None
    ack = ""
    if "follow_seconds" not in form:
        errors.append("缺少续说秒数，没有写入")
    else:
        follow, message = parse_seconds(form["follow_seconds"], "续说秒数")
        if message:
            errors.append(message)
    if "preroll_seconds" not in form:
        errors.append("缺少预滚秒数，没有写入")
    else:
        preroll, message = parse_seconds(form["preroll_seconds"], "预滚秒数")
        if message:
            errors.append(message)
    if "ack" not in form:
        errors.append("缺少唤醒应答，没有写入")
    else:
        ack = form["ack"]
        if not isinstance(ack, str):
            errors.append("唤醒应答必须是文字")

    configs: dict[tuple[str, str], dict] = {}
    for group in GROUPS:
        slots = document.get(group)
        if not isinstance(slots, dict):
            continue
        for name, slot in slots.items():
            if not isinstance(slot, dict):
                continue
            field = config_field(group, name)
            label = f"{group}.{name}"
            if field not in form:
                errors.append(f"缺少 {label} 的配置，没有写入")
                continue
            try:
                parsed = json.loads(form[field])
            except json.JSONDecodeError as exc:
                errors.append(f"{label} 的配置不是合法 JSON：{exc.msg}")
                continue
            if not isinstance(parsed, dict):
                errors.append(f"{label} 的配置必须是 JSON 对象，没有写入")
                continue
            if group == "serve" and name == "webui":
                message = validate_webui_config(parsed)
                if message:
                    errors.append(message)
                    continue
            configs[(group, name)] = parsed

    if errors or follow is None or preroll is None:
        if not errors:
            errors.append("流程数字无效，没有写入")
        return None, errors

    updated = copy.deepcopy(document)
    flow = updated.get("flow")
    if not isinstance(flow, dict):
        flow = {}
        updated["flow"] = flow
    flow["follow_seconds"] = follow
    flow["preroll_seconds"] = preroll
    flow["ack"] = ack
    for (group, name), parsed in configs.items():
        updated[group][name]["config"] = parsed
    return updated, []


def replace_startup(path: Path, data: dict) -> None:
    """先写入同目录临时文件，再替换，避免启动文件只写了一半。"""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=".lingyu-webui-", suffix=".tmp", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return f"{value:.1f}"
        return str(value)
    return str(value)


def command_text(slot: dict) -> str:
    if "command" not in slot:
        return "（没有命令）"
    return json.dumps(slot["command"], ensure_ascii=False)


def config_text(slot: dict, form: dict[str, str] | None, group: str, name: str) -> str:
    if form is not None:
        field = config_field(group, name)
        if field in form:
            return form[field]
    config = slot.get("config", {})
    return json.dumps(config, ensure_ascii=False, indent=2)


PAGE_STYLE = """
:root { color-scheme: light; }
body {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  margin: 0 auto;
  max-width: 52rem;
  padding: 1.5rem 1.25rem 3rem;
  line-height: 1.5;
  background: #fafafa;
  color: #1c1c1c;
}
h1 { font-size: 1.55rem; margin: 0 0 0.35rem; }
h2 { font-size: 1.15rem; margin: 1.8rem 0 0.4rem; }
h3 { font-size: 1rem; margin: 0; }
.lead, .muted { color: #444; }
.slot {
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 0.8rem 1rem 1rem;
  margin: 0.75rem 0;
}
label { display: block; font-weight: 600; margin: 0.75rem 0 0.25rem; }
input[type="text"], textarea {
  width: 100%;
  box-sizing: border-box;
  font: inherit;
  padding: 0.4rem 0.55rem;
  border: 1px solid #bbb;
  border-radius: 4px;
  background: #fff;
}
textarea {
  font-family: Consolas, "Sarasa Mono SC", monospace;
  font-size: 0.92rem;
}
pre.command {
  margin: 0;
  background: #f3f3f3;
  border-radius: 4px;
  padding: 0.55rem 0.7rem;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.ok, .err { padding: 0.65rem 0.8rem; border-radius: 6px; }
.ok { background: #e7f6e7; border: 1px solid #8c8; }
.err { background: #fdecec; border: 1px solid #c88; }
button {
  margin-top: 0.4rem;
  font: inherit;
  padding: 0.4rem 1.15rem;
}
"""


def shell(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{PAGE_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def render_failure(message: str) -> str:
    body = f"<h1>凌雨设置</h1>\n<p class=\"err\">{esc(message)}</p>\n"
    return shell("凌雨设置", body)


def render_page(
    document: dict,
    startup: Path,
    *,
    errors: list[str] | None = None,
    notice: str | None = None,
    form: dict[str, str] | None = None,
) -> str:
    parts = [
        "<h1>凌雨设置</h1>",
        '<p class="lead">只改流程和各插件槽的配置。命令只读，保存时按原样写回。</p>',
        f"<p>SILICONFLOW_API_KEY：{esc(api_key_status())}</p>",
        '<p class="muted">只看这个环境变量是否非空，不读取 .env，也不显示密钥。</p>',
        f"<p class=\"muted\">启动文件：{esc(startup)}</p>",
    ]
    if notice:
        parts.append(f'<p class="ok">{esc(notice)}</p>')
    if errors:
        items = "".join(f"<li>{esc(item)}</li>" for item in errors)
        parts.append(f'<div class="err"><p>没有写入启动文件。</p><ul>{items}</ul></div>')

    flow = document.get("flow")
    flow_dict = flow if isinstance(flow, dict) else {}
    if form is None:
        follow = format_number(flow_dict.get("follow_seconds"))
        preroll = format_number(flow_dict.get("preroll_seconds"))
        ack_value = flow_dict.get("ack")
        ack = ack_value if isinstance(ack_value, str) else ""
    else:
        follow = form.get("follow_seconds", "")
        preroll = form.get("preroll_seconds", "")
        ack = form.get("ack", "")

    parts.append("<h2>流程</h2>")
    parts.append('<form method="post" action="/" autocomplete="off">')
    parts.append('<label for="follow_seconds">续说秒数（follow_seconds）</label>')
    parts.append(
        f'<input id="follow_seconds" name="follow_seconds" type="text" value="{esc(follow)}">'
    )
    parts.append('<label for="preroll_seconds">预滚秒数（preroll_seconds）</label>')
    parts.append(
        f'<input id="preroll_seconds" name="preroll_seconds" type="text" value="{esc(preroll)}">'
    )
    parts.append('<label for="ack">唤醒应答（ack）</label>')
    parts.append(f'<input id="ack" name="ack" type="text" value="{esc(ack)}">')

    field_index = 0
    for group in GROUPS:
        parts.append(f"<h2>{esc(GROUP_TITLES[group])}（{esc(group)}）</h2>")
        slots = document.get(group)
        if slots is None:
            parts.append("<p>没有槽位。</p>")
            continue
        if not isinstance(slots, dict):
            parts.append(f"<p>{esc(group)} 不是对象，这里不能编辑，保存时不会改动它。</p>")
            continue
        if not slots:
            parts.append("<p>没有槽位。</p>")
            continue
        for name, slot in slots.items():
            if not isinstance(slot, dict):
                parts.append(
                    f"<p>{esc(group)}.{esc(name)} 不是对象，已跳过，保存时不会改动。</p>"
                )
                continue
            label = SLOT_LABELS.get(name, name)
            field = config_field(group, name)
            field_index += 1
            field_id = f"cfg-{field_index}"
            text = config_text(slot, form, group, name)
            rows = min(16, max(4, text.count("\n") + 2))
            parts.append('<section class="slot">')
            parts.append(f"<h3>{esc(label)} · {esc(name)}</h3>")
            parts.append("<label>命令（只读）</label>")
            parts.append(f'<pre class="command">{esc(command_text(slot))}</pre>')
            parts.append(f'<label for="{field_id}">配置（JSON）</label>')
            parts.append(
                f'<textarea id="{field_id}" name="{esc(field)}" rows="{rows}" '
                f'spellcheck="false">{esc(text)}</textarea>'
            )
            parts.append("</section>")

    parts.append(
        '<p class="muted">命令不能在此修改。某一槽的配置若不是合法 JSON，这一次整个文件都不会写。</p>'
    )
    parts.append("<button type=\"submit\">保存</button>")
    parts.append("</form>")
    return shell("凌雨设置", "\n".join(parts))


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


if __name__ == "__main__":
    main()
