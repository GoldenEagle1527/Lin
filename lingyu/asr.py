"""本地中文语音识别：Silero VAD 切句，SenseVoice 转文字。"""

from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
VAD_PATH = ROOT / "models" / "silero_vad.onnx"
SAMPLE_RATE = 16000
_TAG = re.compile(r"<\|[^|]*\|>")


class UtteranceSegmenter:
    """Silero VAD 切句。不加载识别模型。"""

    def __init__(self) -> None:
        if not VAD_PATH.is_file():
            raise FileNotFoundError("缺少 models/silero_vad.onnx")

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(VAD_PATH)
        config.silero_vad.min_silence_duration = 0.5
        config.silero_vad.min_speech_duration = 0.25
        config.sample_rate = SAMPLE_RATE
        self.vad_config = config
        self.window_size = config.silero_vad.window_size
        self.sample_rate = SAMPLE_RATE

    def new_vad(self) -> sherpa_onnx.VoiceActivityDetector:
        return sherpa_onnx.VoiceActivityDetector(
            self.vad_config, buffer_size_in_seconds=30
        )


class SpeechRecognizer:
    def __init__(self, num_threads: int = 4, language: str = "zh") -> None:
        model = MODEL_DIR / "model.int8.onnx"
        tokens = MODEL_DIR / "tokens.txt"
        if not model.is_file() or not tokens.is_file():
            raise FileNotFoundError(
                "缺少语音模型。需要 "
                "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/"
            )

        self.sample_rate = SAMPLE_RATE
        self.segmenter = UtteranceSegmenter()
        self.window_size = self.segmenter.window_size
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
            language=language,
            use_itn=True,
            provider="cpu",
        )

    def new_vad(self) -> sherpa_onnx.VoiceActivityDetector:
        return self.segmenter.new_vad()

    def transcribe(self, samples: np.ndarray) -> str:
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        if audio.size < int(0.2 * self.sample_rate):
            return ""
        # SenseVoice 在语音紧贴音频两端时会吃掉首尾字，补一段静音。
        lead = np.zeros(int(0.2 * self.sample_rate), dtype=np.float32)
        tail = np.zeros(int(0.3 * self.sample_rate), dtype=np.float32)
        audio = np.concatenate([lead, audio, tail])
        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, audio)
        self.recognizer.decode_stream(stream)
        return _TAG.sub("", stream.result.text).strip()


def load_wav(path: Path) -> np.ndarray:
    """读 wav，转成 16 kHz 单声道 float32。"""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if sample_width != 2:
        raise ValueError(f"只支持 16-bit wav，当前采样宽度是 {sample_width} 字节")

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if sample_rate != SAMPLE_RATE:
        new_length = int(len(audio) * SAMPLE_RATE / sample_rate)
        source = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target = np.linspace(0.0, 1.0, num=new_length, endpoint=False)
        audio = np.interp(target, source, audio).astype(np.float32)

    return np.ascontiguousarray(audio, dtype=np.float32)
