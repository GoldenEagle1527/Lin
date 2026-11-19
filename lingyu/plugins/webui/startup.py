from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

from lingyu.plugins.webui.constants import DEFAULT_HOST, DEFAULT_PORT, LOOPBACK_NOTE


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
