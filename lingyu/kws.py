"""本机唤醒。只听「凌雨」「你好凌雨」「凌雨凌雨」。"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KEYWORDS = ROOT / "models" / "keywords.txt"
SAMPLE_RATE = 16000

_WAKE_WORD = (
    r"(?:凌雨|林雨|灵雨|淋雨|陵雨|玲雨|凌宇|林宇|"
    r"零雨|林语|灵语|凌语|霖雨|林羽|凌羽|令雨|凌予|林予)"
)
_GAP = r"[，,。！!？?、\s]*"
_LEADING_WAKE = re.compile(rf"^(?:你好{_GAP}|好{_GAP})?{_WAKE_WORD}(?:{_GAP}{_WAKE_WORD})*")
_PUNCT = "，,。！!？?、 \t"
_FILLERS = {"嗯", "啊", "呃", "哦", "唔", "唉", "额"}


def command_after_wake(text: str) -> str:
    """去掉句首的唤醒词。只剩名字或语气词时，返回空字符串。"""
    cleaned = _LEADING_WAKE.sub("", text.strip()).lstrip(_PUNCT).strip()
    if cleaned in _FILLERS:
        return ""
    return cleaned


class WakeSpotter:
    def __init__(self, num_threads: int = 2) -> None:
        encoder = MODEL_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        decoder = MODEL_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
        joiner = MODEL_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        tokens = MODEL_DIR / "tokens.txt"
        missing = [path for path in (encoder, decoder, joiner, tokens, KEYWORDS) if not path.is_file()]
        if missing:
            raise FileNotFoundError("缺少唤醒模型: " + ", ".join(str(path) for path in missing))

        self.sample_rate = SAMPLE_RATE
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            keywords_file=str(KEYWORDS),
            num_threads=num_threads,
            keywords_score=1.5,
            keywords_threshold=0.1,
            provider="cpu",
        )
        self.stream = self.spotter.create_stream()

    def reset(self) -> None:
        self.stream = self.spotter.create_stream()

    def accept(self, samples: np.ndarray) -> str:
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        self.stream.accept_waveform(self.sample_rate, audio)
        found = ""
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            keyword = self.spotter.get_result(self.stream)
            if keyword:
                found = keyword
                self.spotter.reset_stream(self.stream)
        return found
