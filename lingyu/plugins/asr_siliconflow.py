"""星辰云端转写。模型名仍来自环境变量，configure 时才构造客户端。"""

from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm, serve

HELLO = {
    "protocol": 1,
    "slot": "asr",
    "settings": [],
}


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


def main() -> None:
    plugin = CloudAsr()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "transcribe": plugin.transcribe,
        },
    )


if __name__ == "__main__":
    main()
