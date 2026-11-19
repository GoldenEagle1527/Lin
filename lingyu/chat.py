"""硅基流动星辰对话。只读环境变量里的密钥。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEFAULT_MODEL = "XingChenAGI/Xing4.0-29B"

SYSTEM = (
    "你是凌雨，运行在用户电脑上的语音助手。"
    "用口语短句回答，一般一两句，适合被读出来。"
    "不要用 Markdown、列表和表情。"
    "用户的话来自语音识别，可能有错字，按最可能的意思理解。"
)


def load_env(path: Path | None = None) -> None:
    env_file = path or (ROOT / ".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Xingchen:
    def __init__(self) -> None:
        load_env()
        api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("没有 SILICONFLOW_API_KEY。把它写进项目根目录的 .env")
        self.api_key = api_key
        self.model = os.environ.get("SILICONFLOW_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]

    def reply(self, user_text: str, on_delta) -> str:
        self.messages.append({"role": "user", "content": user_text})
        self._trim()
        parts: list[str] = []
        try:
            for piece in self._stream():
                parts.append(piece)
                on_delta(piece)
        except Exception:
            self.messages.pop()
            raise
        answer = "".join(parts).strip()
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def _trim(self) -> None:
        if len(self.messages) > 17:
            self.messages = [self.messages[0], *self.messages[-16:]]

    def _stream(self):
        payload = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "enable_thinking": False,
            "max_tokens": 300,
            "temperature": 0.7,
        }
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"硅基流动返回 {exc.code}: {detail}") from None

        with response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    yield content
