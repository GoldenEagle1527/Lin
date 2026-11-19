"""请求参数里的文字、配置和 PCM。"""

from __future__ import annotations

import base64

import numpy as np


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
