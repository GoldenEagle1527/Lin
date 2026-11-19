"""本机 CosyVoice2。大模型一边出字，这边同一条合成会话里流式出声。"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

from lingyu.chat import load_env

ROOT = Path(__file__).resolve().parents[1]
COSY_ROOT = ROOT / "third_party" / "CosyVoice"
MATCHA_ROOT = COSY_ROOT / "third_party" / "Matcha-TTS"
MODEL_DIR = ROOT / "models" / "CosyVoice2-0.5B"
PROMPT_WAV = COSY_ROOT / "asset" / "zero_shot_prompt.wav"
PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
SAMPLE_RATE = 24000

_MARKDOWN = re.compile(r"[#*`_>]+")
_SPACE = re.compile(r"\s+")
_STRONG = "。！？!?；;…"
_WEAK = "，,、"


def _for_speech(text: str) -> str:
    cleaned = _MARKDOWN.sub("", text)
    cleaned = _SPACE.sub(" ", cleaned).strip()
    return cleaned


def _take_chunks(buf: str) -> tuple[list[str], str]:
    ready: list[str] = []
    while buf:
        strong = min((buf.find(mark) for mark in _STRONG if mark in buf), default=-1)
        weak = min((buf.find(mark) for mark in _WEAK if mark in buf), default=-1)
        cut = 0
        if strong >= 0:
            cut = strong + 1
        elif weak >= 0 and weak + 1 >= 8:
            cut = weak + 1
        elif len(buf) >= 24:
            cut = len(buf)
        if not cut:
            break
        piece = _for_speech(buf[:cut])
        buf = buf[cut:]
        if piece:
            ready.append(piece)
    return ready, buf


def _ensure_paths() -> None:
    if str(COSY_ROOT) not in sys.path:
        sys.path.insert(0, str(COSY_ROOT))
    if str(MATCHA_ROOT) not in sys.path:
        sys.path.insert(0, str(MATCHA_ROOT))
    if not MODEL_DIR.is_dir() or not (MODEL_DIR / "cosyvoice2.yaml").is_file():
        raise RuntimeError(
            f"缺少本机 CosyVoice2 模型。把它放到 {MODEL_DIR}"
        )
    if not PROMPT_WAV.is_file():
        raise RuntimeError(f"缺少参考音频 {PROMPT_WAV}")


class Speaker:
    def __init__(self, voice: str | None = None) -> None:
        load_env()
        _ensure_paths()
        prompt = Path(voice or os.environ.get("LINGYU_VOICE", "") or PROMPT_WAV)
        if not prompt.is_file():
            prompt = PROMPT_WAV
        self.prompt_wav = prompt
        self.prompt_text = os.environ.get("LINGYU_PROMPT_TEXT", PROMPT_TEXT).strip() or PROMPT_TEXT
        self.voice = prompt.name
        self.model = "CosyVoice2-0.5B"
        from cosyvoice.cli.cosyvoice import CosyVoice2
        import torch

        use_cuda = torch.cuda.is_available()
        os.environ.setdefault("TQDM_DISABLE", "1")
        self._cosy = CosyVoice2(
            str(MODEL_DIR),
            load_jit=False,
            load_trt=False,
            fp16=use_cuda,
        )
        self.sample_rate = int(self._cosy.sample_rate)
        self._buf = ""
        self._jobs: queue.Queue[str | None] | None = None
        self._pcm: queue.Queue[np.ndarray | None] | None = None
        self._threads: list[threading.Thread] = []
        self._error: BaseException | None = None

    def say(self, text: str) -> None:
        spoken = _for_speech(text)
        if not spoken:
            return
        self.begin()
        try:
            self.feed(spoken)
            self.finish()
        except Exception:
            self.cancel()
            raise

    def begin(self) -> None:
        self.cancel()
        self._buf = ""
        self._error = None
        self._jobs = queue.Queue()
        self._pcm = queue.Queue()
        synth = threading.Thread(target=self._synth_loop, daemon=True)
        play = threading.Thread(target=self._play_loop, daemon=True)
        self._threads = [synth, play]
        synth.start()
        play.start()

    def feed(self, piece: str) -> None:
        if not piece or self._jobs is None:
            return
        self._buf += piece
        chunks, self._buf = _take_chunks(self._buf)
        for chunk in chunks:
            self._jobs.put(chunk)

    def finish(self) -> None:
        leftover = _for_speech(self._buf)
        self._buf = ""
        if leftover and self._jobs is not None:
            self._jobs.put(leftover)
        if self._jobs is not None:
            self._jobs.put(None)
        for worker in self._threads:
            worker.join(timeout=120)
        self._threads = []
        self._jobs = None
        self._pcm = None
        if self._error is not None:
            raise RuntimeError(f"语音合成失败: {self._error}") from self._error

    def cancel(self) -> None:
        jobs, pcm, threads = self._jobs, self._pcm, self._threads
        self._jobs = None
        self._pcm = None
        self._threads = []
        self._buf = ""
        if jobs is not None:
            try:
                jobs.put_nowait(None)
            except Exception:
                pass
        if pcm is not None:
            try:
                pcm.put_nowait(None)
            except Exception:
                pass
        for worker in threads:
            worker.join(timeout=1)

    def _text_stream(self, jobs: queue.Queue[str | None]):
        while True:
            item = jobs.get()
            if item is None:
                return
            yield item

    def _synth_loop(self) -> None:
        jobs = self._jobs
        pcm = self._pcm
        if jobs is None or pcm is None:
            return
        try:
            for out in self._cosy.inference_zero_shot(
                self._text_stream(jobs),
                self.prompt_text,
                str(self.prompt_wav),
                stream=True,
                text_frontend=False,
            ):
                if self._pcm is not pcm:
                    return
                wav = out["tts_speech"].detach().float().cpu().numpy().reshape(-1)
                if wav.size:
                    pcm.put(np.ascontiguousarray(wav, dtype=np.float32))
        except BaseException as exc:
            self._error = exc
        finally:
            try:
                pcm.put(None)
            except Exception:
                pass

    def _play_loop(self) -> None:
        pcm = self._pcm
        if pcm is None:
            return
        try:
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                latency="low",
            ) as stream:
                while True:
                    chunk = pcm.get()
                    if chunk is None:
                        break
                    if chunk.size:
                        stream.write(np.clip(chunk, -1.0, 1.0).reshape(-1, 1))
        except BaseException as exc:
            if self._error is None:
                self._error = exc
