"""各槽 configure 共用的字段读取。"""

from __future__ import annotations


def int_setting(config: dict, name: str, default: int) -> int:
    value = config.get(name, default)
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是整数")
    return int(value)


def float_setting(config: dict, name: str, default: float) -> float:
    value = config.get(name, default)
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是数字")
    return float(value)


def string_setting(config: dict, name: str, default: str = "") -> str:
    value = config.get(name, default)
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串")
    text = value.strip()
    return text or default
