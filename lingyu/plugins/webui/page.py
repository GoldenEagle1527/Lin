"""设置页。表台式布局，配置用通用 JSON 编辑器，不按插件声明画字段。"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

from lingyu.plugins.webui.constants import GROUPS, GROUP_TITLES, SLOT_LABELS
from lingyu.plugins.webui.edits import config_field
from lingyu.plugins.webui.startup import api_key_status

_DIR = Path(__file__).parent
LEAD = "只改流程和各插件槽的配置。命令只读，保存时按原样写回。"
WARN = "命令不能在此修改。某一槽的配置若不是合法 JSON，这一次整个文件都不会写。"
WHEN = "流程数字下一轮生效。更换插件配置需要重启进程。"
FLOW_FIELDS = (
    ("follow_seconds", "续说秒数", "回答结束后可以接着说，不用再喊名字。缺省 25 秒。"),
    ("preroll_seconds", "预滚秒数", "唤醒前留给切句的音频。缺省 2 秒。"),
    ("ack", "唤醒应答", "听到名字后先读这一句。缺省「在」。"),
)


def asset(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


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
    style = asset("json_editor.css") + asset("desk.css")
    script = asset("json_editor.js") + asset("desk.js")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>\n{style}\n</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        f"<script>\n{script}\n</script>\n"
        "</body>\n</html>\n"
    )


def json_editor(field_id: str, name: str, value: str) -> str:
    return (
        f'<div class="json-editor" data-json-editor id="{esc(field_id)}">'
        f'<textarea class="json-field" name="{esc(name)}">{esc(value)}</textarea>'
        "</div>"
    )


def render_failure(message: str) -> str:
    body = f'<main class="page"><h1>凌雨设置</h1><p class="banner err">{esc(message)}</p></main>'
    return shell("凌雨设置", body)


def render_page(
    document: dict,
    startup: Path,
    *,
    errors: list[str] | None = None,
    notice: str | None = None,
    form: dict[str, str] | None = None,
) -> str:
    parts = ['<main class="page">']
    if notice:
        parts.append(f'<p class="banner ok">{esc(notice)}</p>')
    if errors:
        items = "".join(f"<li>{esc(item)}</li>" for item in errors)
        parts.append(f'<div class="banner err"><p>没有写入启动文件。</p><ul>{items}</ul></div>')
    parts.append('<p id="form-error" class="banner err" hidden></p>')
    parts.append('<form method="post" action="/" autocomplete="off">')

    flow = document.get("flow")
    flow_dict = flow if isinstance(flow, dict) else {}
    if form is None:
        values = {
            "follow_seconds": format_number(flow_dict.get("follow_seconds")),
            "preroll_seconds": format_number(flow_dict.get("preroll_seconds")),
            "ack": flow_dict.get("ack") if isinstance(flow_dict.get("ack"), str) else "",
        }
    else:
        values = {key: form.get(key, "") for key, _label, _hint in FLOW_FIELDS}

    meters = []
    for key, label, _hint in FLOW_FIELDS:
        meters.append(
            f'<label class="meter" for="{key}"><span><b>{esc(label)}</b><small>{esc(key)}</small></span>'
            f'<input id="{key}" name="{key}" type="text" value="{esc(values[key])}" '
            'autocomplete="off" spellcheck="false"></label>'
        )
    parts.append(
        '<header class="band glass"><div class="brand"><p class="kicker">语音助手</p><h1>凌雨设置</h1>'
        '<div class="themes" role="group" aria-label="颜色">'
        '<button type="button" data-theme-set="system" aria-pressed="true">系统</button>'
        '<button type="button" data-theme-set="light" aria-pressed="false">浅色</button>'
        '<button type="button" data-theme-set="dark" aria-pressed="false">深色</button>'
        "</div></div>"
        f'<div class="meters">{"".join(meters)}</div>'
        '<button class="save" type="submit">保存</button></header>'
    )
    parts.append(
        f'<p class="sub">{esc(LEAD)} {esc(WHEN)} 密钥 {esc(api_key_status())}。</p>'
        f'<p class="path">{esc(startup)}</p>'
    )

    rows = []
    field_index = 0
    for group in GROUPS:
        slots = document.get(group)
        if not isinstance(slots, dict) or not slots:
            continue
        visible = [(name, slot) for name, slot in slots.items() if isinstance(slot, dict)]
        for index, (name, slot) in enumerate(visible):
            field_index += 1
            group_cell = (
                f'<td class="group" rowspan="{len(visible)}">{esc(GROUP_TITLES[group])}</td>'
                if index == 0
                else ""
            )
            field = config_field(group, name)
            rows.append(
                "<tr>"
                + group_cell
                + '<td class="slotname">'
                + f"<strong>{esc(SLOT_LABELS.get(name, name))}</strong><span>{esc(name)}</span></td>"
                + f'<td><pre class="command">{esc(command_text(slot))}</pre></td>'
                + "<td>"
                + json_editor(f"cfg-{field_index}", field, config_text(slot, form, group, name))
                + "</td></tr>"
            )
    if rows:
        parts.append(
            '<section class="sheet glass"><div class="table-wrap"><table><thead><tr>'
            '<th scope="col">分组</th><th scope="col">槽</th>'
            '<th scope="col">命令</th><th scope="col">配置</th>'
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div></section>"
        )
    else:
        parts.append('<p class="hint">没有槽位。</p>')
    parts.append(f'<p class="hint">{esc(WARN)}</p></form></main>')
    return shell("凌雨设置", "".join(parts))
