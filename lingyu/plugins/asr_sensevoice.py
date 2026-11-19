"""本机 SenseVoice 转写。切句由 segment 槽负责，这里只调用 transcribe。"""

from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm, serve

HELLO = {
    "protocol": 1,
    "slot": "asr",
    "settings": [
        {"name": "threads", "type": "int", "default": 4, "label": "识别线程数"},
        {"name": "language", "type": "string", "default": "zh", "label": "识别语言"},
    ],
}


def _threads(config: dict) -> int:
    value = config.get("threads", 4)
    if value is None or value == "":
        return 4
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threads 必须是整数")
    return int(value)


def _language(config: dict) -> str:
    value = config.get("language", "zh")
    if value is None or value == "":
        return "zh"
    if not isinstance(value, str):
        raise ValueError("language 必须是字符串")
    text = value.strip()
    return text or "zh"


class SenseVoice:
    def __init__(self) -> None:
        self.recognizer = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.asr import SpeechRecognizer

        config = config_of(params)
        self.recognizer = SpeechRecognizer(
            num_threads=_threads(config),
            language=_language(config),
        )
        return {}

    def transcribe(self, params: dict, _notify) -> dict:
        if self.recognizer is None:
            raise RuntimeError("还没有 configure")
        samples = decode_pcm(params, expect_rate=self.recognizer.sample_rate)
        return {"text": self.recognizer.transcribe(samples)}


def main() -> None:
    plugin = SenseVoice()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "transcribe": plugin.transcribe,
        },
    )


if __name__ == "__main__":
    main()
