from __future__ import annotations

import copy
import json
import math
from urllib.parse import quote

from lingyu.plugins.webui.constants import GROUPS
from lingyu.plugins.webui.startup import loopback_host


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
