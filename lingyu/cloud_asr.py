"""硅基流动星辰语音识别。本机只切句，转写走云端。"""

from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

from lingyu.asr import SAMPLE_RATE
from lingyu.chat import load_env

ASR_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "XingChenAGI/XingChenASR-V3.2-Ultra"
_TAG = re.compile(r"<\|[^|]*\|>")


def wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    audio = np.clip(np.ascontiguousarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _multipart(model: str, audio: bytes) -> tuple[bytes, str]:
    boundary = "----Lingyu" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            b'Content-Disposition: form-data; name="model"\r\n\r\n',
            model.encode("utf-8"),
            f"\r\n--{boundary}\r\n".encode("utf-8"),
            b'Content-Disposition: form-data; name="file"; filename="utterance.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            audio,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return body, boundary


class CloudTranscriber:
    def __init__(self) -> None:
        load_env()
        api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("没有 SILICONFLOW_API_KEY。把它写进项目根目录的 .env")
        self.api_key = api_key
        self.model = os.environ.get("SILICONFLOW_ASR_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.sample_rate = SAMPLE_RATE

    def transcribe(self, samples: np.ndarray) -> str:
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        if audio.size < int(0.2 * self.sample_rate):
            return ""
        lead = np.zeros(int(0.15 * self.sample_rate), dtype=np.float32)
        tail = np.zeros(int(0.2 * self.sample_rate), dtype=np.float32)
        wav = wav_bytes(np.concatenate([lead, audio, tail]))
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._request(wav)
            except RuntimeError as exc:
                last_error = exc
                if not any(code in str(exc) for code in (" 429:", " 500:", " 502:", " 503:", " 504:")):
                    raise
                if attempt == 2:
                    raise
                time.sleep(0.4 * (attempt + 1))
        raise last_error or RuntimeError("星辰转写失败")

    def _request(self, wav: bytes) -> str:
        payload, boundary = _multipart(self.model, wav)
        request = urllib.request.Request(
            ASR_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"星辰转写返回 {exc.code}: {detail}") from None

        with response:
            body = json.loads(response.read().decode("utf-8"))
        return _TAG.sub("", str(body.get("text") or "")).strip()
