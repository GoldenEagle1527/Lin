"""麦克风上的一轮：待命、唤醒、切句、转写或送音频、流式朗读。"""

from __future__ import annotations

import json
import queue
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from lingyu.host import Host, PluginExited, start_listen, start_serve

SAMPLE_RATE = 16000
_CHUNK_SECONDS = 0.1


class _Flow:
    def __init__(self, follow_seconds: float = 25.0, preroll_seconds: float = 2.0, ack: str = "在") -> None:
        self.follow_seconds = follow_seconds
        self.preroll_seconds = preroll_seconds
        self.ack = ack


def _number(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        return None
    return number


def read_flow(path: Path, previous: _Flow | None = None) -> _Flow:
    """只重读 flow。读失败就沿用上一轮，不重启插件。"""
    fallback = previous or _Flow()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    raw = data.get("flow", {})
    if not isinstance(raw, dict):
        return fallback
    follow = _number(raw.get("follow_seconds", fallback.follow_seconds))
    preroll = _number(raw.get("preroll_seconds", fallback.preroll_seconds))
    ack = raw.get("ack", fallback.ack)
    if not isinstance(ack, str) or ack == "":
        ack = fallback.ack or "在"
    return _Flow(
        fallback.follow_seconds if follow is None else follow,
        fallback.preroll_seconds if preroll is None else preroll,
        ack,
    )


def _drain(audio_queue: queue.Queue) -> None:
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def _cancel(host: Host) -> None:
    speaker = host.speaker
    if speaker is None:
        return
    try:
        speaker.cancel()
    except Exception:
        return


def _shown_ack(ack: str) -> str:
    if ack.endswith(("。", "！", "？", "!", "?", ".", "…")):
        return ack
    return ack + "。"


def talk(host: Host, text: str | None, *, pcm: np.ndarray | None = None, sample_rate: int | None = None) -> None:
    if text is not None:
        print(f"\n你: {text}", flush=True)
    print("凌雨: ", end="", flush=True)
    speaker = host.speaker
    agent = host.agent
    if speaker is None or agent is None:
        print("\n[对话失败] 没有对话或朗读", flush=True)
        return
    try:
        speaker.begin()

        def on_delta(piece: str) -> None:
            print(piece, end="", flush=True)
            speaker.feed(piece)

        if pcm is not None:
            agent.reply(None, on_delta, pcm=pcm, sample_rate=sample_rate)
        else:
            agent.reply(text, on_delta)
        speaker.finish()
    except PluginExited:
        _cancel(host)
        raise
    except Exception as exc:
        _cancel(host)
        print(f"\n[对话失败] {exc}", flush=True)
        return
    print(flush=True)


class _Mic:
    def __init__(self, host: Host) -> None:
        self.host = host
        self.muted = False
        self.following = False
        self.opening = False
        self.deadline = 0.0
        self.preroll = np.zeros(0, dtype=np.float32)
        self.queue: queue.Queue[np.ndarray] = queue.Queue()

    def on_audio(self, indata, _frames, _time_info, status) -> None:
        if self.muted:
            return
        if status:
            print(f"\n[麦克风] {status}", flush=True)
        self.queue.put(np.array(indata[:, 0], dtype=np.float32, copy=True))

    def say_ack(self, text: str) -> None:
        if not text:
            return
        self.muted = True
        try:
            if self.host.speaker is not None:
                self.host.speaker.say(text)
            time.sleep(0.3)
        except PluginExited:
            raise
        except Exception as exc:
            print(f"[没能读出来] {exc}", flush=True)
        finally:
            _drain(self.queue)
            self.preroll = np.zeros(0, dtype=np.float32)
            self.muted = False

    def _after_speech(self, flow: _Flow) -> None:
        _drain(self.queue)
        self.preroll = np.zeros(0, dtype=np.float32)
        self.muted = False
        self.deadline = time.time() + flow.follow_seconds

    def _speak(self, flow: _Flow, text: str | None, pcm: np.ndarray | None, sample_rate: int | None) -> None:
        self.muted = True
        try:
            if pcm is not None:
                talk(self.host, None, pcm=pcm, sample_rate=sample_rate)
            else:
                talk(self.host, text)
        finally:
            self._after_speech(flow)

    def _handle_text(self, flow: _Flow, pcm: np.ndarray, sample_rate: int) -> None:
        seconds = len(pcm) / sample_rate if sample_rate else 0.0
        print(f"（转写中，这一句 {seconds:.1f} 秒）", flush=True)
        asr = self.host.asr
        if asr is None:
            print("[转写失败] 缺少转写", flush=True)
            return
        try:
            text = asr.transcribe(pcm, sample_rate)
        except PluginExited:
            raise
        except Exception as exc:
            print(f"[转写失败] {exc}", flush=True)
            return
        self.deadline = time.time() + flow.follow_seconds
        if not text:
            print("（没听清，再说一次）", flush=True)
            return
        if self.opening:
            wake = self.host.wake
            if wake is None:
                command = text
            else:
                try:
                    command = wake.strip(text)
                except PluginExited:
                    raise
                except Exception as exc:
                    print(f"[转写失败] {exc}", flush=True)
                    return
            self.opening = False
        else:
            command = text
        if command:
            self._speak(flow, command, None, None)
        else:
            print(f"（只听到「{text}」，接着说事情）", flush=True)

    def _handle_audio(self, flow: _Flow, pcm: np.ndarray, sample_rate: int) -> None:
        self.opening = False
        if pcm.size == 0:
            print("（没听清，再说一次）", flush=True)
            return
        self._speak(flow, None, pcm, sample_rate)

    def _handle(self, flow: _Flow, pcm: np.ndarray, sample_rate: int) -> None:
        self.deadline = time.time() + flow.follow_seconds
        agent = self.host.agent
        if agent is not None and agent.input == "audio":
            self._handle_audio(flow, pcm, sample_rate)
        else:
            self._handle_text(flow, pcm, sample_rate)

    def _on_keyword(self, flow: _Flow, keyword: str) -> None:
        heard = self.preroll.copy()
        print(f"\n听到「{keyword}」", flush=True)
        print(f"凌雨: {_shown_ack(flow.ack)}", flush=True)
        self.say_ack(flow.ack)
        segment = self.host.segment
        wake = self.host.wake
        if segment is None or wake is None:
            raise RuntimeError("没有唤醒或切句")
        segment.start()
        wake.reset()
        self.following = True
        self.opening = True
        self.deadline = time.time() + flow.follow_seconds
        if heard.size:
            for pcm, rate in segment.push(heard, SAMPLE_RATE):
                self._handle(flow, pcm, rate)

    def _on_timeout(self) -> None:
        segment = self.host.segment
        wake = self.host.wake
        if segment is not None:
            segment.reset()
        if wake is not None:
            wake.reset()
        self.following = False
        self.opening = False
        print("\n（待命。再说「凌雨」）", flush=True)

    def on_chunk(self, flow: _Flow, samples: np.ndarray) -> None:
        self.preroll = np.concatenate([self.preroll, samples])
        keep = int(flow.preroll_seconds * SAMPLE_RATE)
        if keep >= 0 and len(self.preroll) > keep:
            self.preroll = self.preroll[-keep:]
        if not self.following:
            wake = self.host.wake
            if wake is None:
                raise RuntimeError("没有唤醒")
            keyword = wake.accept(samples, SAMPLE_RATE)
            if keyword:
                self._on_keyword(flow, keyword)
            return
        if time.time() > self.deadline:
            self._on_timeout()
            return
        segment = self.host.segment
        if segment is None:
            raise RuntimeError("没有切句")
        for pcm, rate in segment.push(samples, SAMPLE_RATE):
            self._handle(flow, pcm, rate)


def _chosen_input(device: int | None):
    devices = sd.query_devices()
    if len(devices) == 0:
        print("没有找到音频设备")
        sys.exit(1)
    chosen = sd.default.device[0] if device is None else device
    print(f"麦克风: {devices[chosen]['name']}", flush=True)
    return chosen


def _second_label(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def serve_microphone(host: Host, device: int | None) -> None:
    mic = _Mic(host)
    chosen = _chosen_input(device)
    flow = read_flow(host.startup)
    print(f"待命。先说「凌雨」或「你好凌雨」，听到「{flow.ack}」后再说事情。", flush=True)
    print(
        f"唤醒后 {_second_label(flow.follow_seconds)} 秒内可以接着说，不用重复喊名字。Ctrl+C 结束。",
        flush=True,
    )
    chunk = int(_CHUNK_SECONDS * SAMPLE_RATE)
    with sd.InputStream(
        device=chosen,
        channels=1,
        dtype="float32",
        samplerate=SAMPLE_RATE,
        blocksize=chunk,
        callback=mic.on_audio,
    ):
        print("麦克风已打开。", flush=True)
        while True:
            flow = read_flow(host.startup, flow)
            host.check_alive()
            try:
                samples = mic.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            mic.on_chunk(flow, samples)


def run_serve(startup: Path, *, device: int | None, threads: int | None, voice: str | None) -> None:
    host = start_serve(startup, threads=threads, voice=voice, text_mode=False)
    try:
        serve_microphone(host, device)
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        host.close()


def run_text(startup: Path, text: str, *, voice: str | None) -> None:
    host = start_serve(startup, voice=voice, text_mode=True)
    try:
        talk(host, text)
    finally:
        host.close()


def _listen_microphone(host: Host, device: int | None) -> None:
    devices = sd.query_devices()
    if len(devices) == 0:
        print("没有找到音频设备")
        sys.exit(1)
    chosen = sd.default.device[0] if device is None else device
    print(f"麦克风: {devices[chosen]['name']}", flush=True)
    print("开始听。说完停半秒就会出字，Ctrl+C 结束。", flush=True)
    segment = host.segment
    asr = host.asr
    if segment is None or asr is None:
        raise RuntimeError("听写需要 segment 和 asr")
    segment.start()
    chunk = int(_CHUNK_SECONDS * SAMPLE_RATE)
    with sd.InputStream(
        device=chosen,
        channels=1,
        dtype="float32",
        samplerate=SAMPLE_RATE,
    ) as stream:
        print("麦克风已打开。", flush=True)
        while True:
            host.check_alive()
            samples, _overflowed = stream.read(chunk)
            flat = np.ascontiguousarray(samples.reshape(-1), dtype=np.float32)
            for pcm, rate in segment.push(flat, SAMPLE_RATE):
                try:
                    text = asr.transcribe(pcm, rate)
                except PluginExited:
                    raise
                except Exception as exc:
                    print(f"[转写失败] {exc}", flush=True)
                    continue
                if text:
                    print(text, flush=True)


def run_listen(startup: Path, *, device: int | None, threads: int | None) -> None:
    host = start_listen(startup, threads=threads, with_segment=True)
    try:
        _listen_microphone(host, device)
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        host.close()


def run_listen_file(startup: Path, path: Path, *, threads: int | None) -> None:
    from lingyu.asr import SAMPLE_RATE as wav_rate
    from lingyu.asr import load_wav

    host = start_listen(startup, threads=threads, with_segment=False)
    try:
        audio = load_wav(Path(path))
        if host.asr is None:
            raise RuntimeError("听写需要 asr")
        text = host.asr.transcribe(audio, wav_rate)
        print(text or "(没有识别到语音)")
    finally:
        host.close()
