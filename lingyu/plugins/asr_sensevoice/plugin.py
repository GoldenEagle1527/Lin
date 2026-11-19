from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm, int_setting, string_setting


class SenseVoice:
    def __init__(self) -> None:
        self.recognizer = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.asr import SpeechRecognizer

        config = config_of(params)
        self.recognizer = SpeechRecognizer(
            num_threads=int_setting(config, "threads", 4),
            language=string_setting(config, "language", "zh"),
        )
        return {}

    def transcribe(self, params: dict, _notify) -> dict:
        if self.recognizer is None:
            raise RuntimeError("还没有 configure")
        samples = decode_pcm(params, expect_rate=self.recognizer.sample_rate)
        return {"text": self.recognizer.transcribe(samples)}
