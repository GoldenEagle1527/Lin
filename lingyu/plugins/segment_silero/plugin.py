from __future__ import annotations

import numpy as np

from lingyu.plugins.stdio import config_of, decode_pcm, encode_pcm, float_setting

# 与 serve.py 切句一致：端点前后各留约 0.4 秒，骨架不再裁剪。
_MARGIN_SECONDS = 0.4


class Segment:
    def __init__(self) -> None:
        self.segmenter = None
        self.vad = None
        self.pending = np.zeros(0, dtype=np.float32)
        self.captured = np.zeros(0, dtype=np.float32)

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.asr import UtteranceSegmenter

        config = config_of(params)
        segmenter = UtteranceSegmenter()
        segmenter.vad_config.silero_vad.min_silence_duration = float_setting(
            config, "min_silence_duration", 0.5
        )
        segmenter.vad_config.silero_vad.min_speech_duration = float_setting(
            config, "min_speech_duration", 0.25
        )
        self.segmenter = segmenter
        return {}

    def start(self, _params: dict, _notify) -> dict:
        if self.segmenter is None:
            raise RuntimeError("还没有 configure")
        vad = self.segmenter.new_vad()
        self.vad = vad
        self.pending = np.zeros(0, dtype=np.float32)
        self.captured = np.zeros(0, dtype=np.float32)
        return {}

    def push(self, params: dict, _notify) -> dict:
        if self.segmenter is None:
            raise RuntimeError("还没有 configure")
        if self.vad is None:
            raise RuntimeError("还没有 start")
        samples = decode_pcm(params, expect_rate=self.segmenter.sample_rate)
        self.pending = np.concatenate([self.pending, samples])
        window = int(self.segmenter.window_size)
        if window <= 0:
            raise RuntimeError("VAD 窗口大小无效")
        margin = int(_MARGIN_SECONDS * self.segmenter.sample_rate)
        while len(self.pending) >= window:
            piece = np.ascontiguousarray(self.pending[:window], dtype=np.float32)
            self.vad.accept_waveform(piece)
            self.captured = np.concatenate([self.captured, piece])
            self.pending = self.pending[window:]

        utterances: list[dict] = []
        while not self.vad.empty():
            segment = self.vad.front
            start = int(segment.start)
            speech_len = len(segment.samples)
            self.vad.pop()
            begin = max(0, start - margin)
            finish = min(len(self.captured), start + speech_len + margin)
            utterance = self.captured[begin:finish].copy()
            utterances.append(
                {
                    "pcm": encode_pcm(utterance),
                    "sample_rate": self.segmenter.sample_rate,
                }
            )
        return {"utterances": utterances}

    def reset(self, _params: dict, _notify) -> dict:
        self.vad = None
        self.pending = np.zeros(0, dtype=np.float32)
        self.captured = np.zeros(0, dtype=np.float32)
        return {}
