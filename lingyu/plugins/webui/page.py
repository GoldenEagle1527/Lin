from __future__ import annotations

import html
import json
import math
from pathlib import Path

from lingyu.plugins.webui.constants import GROUPS, GROUP_TITLES, SLOT_LABELS
from lingyu.plugins.webui.edits import config_field
from lingyu.plugins.webui.startup import api_key_status

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
