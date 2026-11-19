"""一行一条 JSON。标准输出是协议，标准错误是日志。"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable

import numpy as np

Notify = Callable[[str, dict], None]
Handler = Callable[[dict, Notify], dict]


def config_of(params: dict) -> dict:
    config = params.get("config", {})
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("config 必须是对象")
    return config


def text_of(params: dict) -> str:
    if "text" not in params or params["text"] is None:
        raise ValueError("需要 text")
    text = params["text"]
    if not isinstance(text, str):
        raise ValueError("text 必须是字符串")
    return text


def decode_pcm(params: dict, expect_rate: int | None = None) -> np.ndarray:
    """把 params 里的 pcm 解成单声道 float32。"""
    if "pcm" not in params or "sample_rate" not in params:
        raise ValueError("需要 pcm 和 sample_rate")
    pcm = params["pcm"]
    rate = params["sample_rate"]
    if not isinstance(pcm, str):
        raise ValueError("pcm 必须是 base64 字符串")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise ValueError("sample_rate 必须是整数")
    rate = int(rate)
    try:
        raw = base64.b64decode(pcm, validate=False)
    except Exception as exc:
        raise ValueError("pcm 不是合法的 base64") from exc
    if len(raw) % 4 != 0:
        raise ValueError("pcm 长度不是 float32 的整数倍")
    samples = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=True)
    if expect_rate is not None and rate != expect_rate:
        raise ValueError(f"采样率应为 {expect_rate}，收到 {rate}")
    return np.ascontiguousarray(samples)


def encode_pcm(samples: np.ndarray) -> str:
    audio = np.ascontiguousarray(samples, dtype="<f4")
    return base64.b64encode(audio.tobytes()).decode("ascii")


def _write(message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def _log(text: str) -> None:
    sys.stderr.buffer.write(text.rstrip().encode("utf-8", errors="replace"))
    sys.stderr.buffer.write(b"\n")
    sys.stderr.buffer.flush()


def _error_text(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _invoke(message: dict, methods: dict[str, Handler], notify: Notify) -> dict:
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("缺少 method")
    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    handler = methods.get(method)
    if handler is None:
        raise ValueError(f"未知方法: {method}")
    result = handler(params, notify)
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise TypeError("方法必须返回对象")
    return result


def serve(hello_params: dict, methods: dict[str, Handler]) -> None:
    """先写 hello，再按方法表处理请求。未知方法或异常只回错误，不退出。"""

    def notify(method: str, params: dict | None = None) -> None:
        body = {} if params is None else params
        _write({"jsonrpc": "2.0", "method": method, "params": body})

    _write({"jsonrpc": "2.0", "method": "hello", "params": hello_params})

    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            return
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            _log(f"UnicodeDecodeError: {exc}")
            _write({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": 1, "message": "请求不是 UTF-8"},
            })
            continue
        if not line:
            continue

        req_id = None
        has_id = False
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("请求必须是 JSON 对象")
            has_id = "id" in message
            req_id = message.get("id")
            result = _invoke(message, methods, notify)
        except Exception as exc:
            _log(f"{exc.__class__.__name__}: {_error_text(exc)}")
            _write({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": 1, "message": _error_text(exc)},
            })
            continue

        if has_id:
            _write({"jsonrpc": "2.0", "id": req_id, "result": result})
