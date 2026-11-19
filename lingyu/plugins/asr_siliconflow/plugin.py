from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm


class CloudAsr:
    def __init__(self) -> None:
        self.transcriber = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.cloud_asr import CloudTranscriber

        config_of(params)
        self.transcriber = CloudTranscriber()
        return {}

    def transcribe(self, params: dict, _notify) -> dict:
        if self.transcriber is None:
            raise RuntimeError("还没有 configure")
        samples = decode_pcm(params, expect_rate=self.transcriber.sample_rate)
        return {"text": self.transcriber.transcribe(samples)}
