"""拉起插件进程，按一行一条 JSON-RPC 对话。不 import 插件代码。"""

from __future__ import annotations

import base64
import copy
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from lingyu.chat import load_env

_REQUEST_TIMEOUT = 300.0
_HELLO_TIMEOUT = 120.0


class RpcError(RuntimeError):
    """插件按协议返回了 error。调用方打印后继续听。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class PluginExited(RuntimeError):
    """插件进程没了。服务应停掉，并写明命令。"""

    def __init__(self, slot: str, command: list[str], code: int | None = None) -> None:
        self.slot = slot
        self.command = list(command)
        self.code = code
        shown = _command_line(command)
        if code is None:
            detail = f"插件 {slot} 进程已退出。命令: {shown}"
        else:
            detail = f"插件 {slot} 进程已退出（退出码 {code}）。命令: {shown}"
        super().__init__(detail)


def _command_line(command: list[str]) -> str:
    return " ".join(command)


def encode_pcm(samples: np.ndarray) -> str:
    audio = np.ascontiguousarray(samples, dtype=np.dtype("<f4"))
    return base64.b64encode(audio.tobytes()).decode("ascii")


def decode_pcm(payload: str) -> np.ndarray:
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise RpcError("pcm 不是合法的 base64") from exc
    if len(raw) % 4 != 0:
        raise RpcError("pcm 长度不是 float32 的整数倍")
    samples = np.frombuffer(raw, dtype=np.dtype("<f4")).astype(np.float32, copy=True)
    return np.ascontiguousarray(samples)


def _audio_params(samples: np.ndarray, sample_rate: int) -> dict:
    rate = int(sample_rate)
    return {"pcm": encode_pcm(samples), "sample_rate": rate}


class _Waiter:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: dict | None = None
        self.error: dict | None = None
        self.exited = False


def _close_stream(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        return


def _pump(slot: str, stream) -> None:
    try:
        while True:
            try:
                raw = stream.readline()
            except (OSError, ValueError):
                break
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                print(f"[{slot}] {line}", file=sys.stderr, flush=True)
    finally:
        _close_stream(stream)


class Plugin:
    """一个槽、一个进程、一条只读标准输出的线程。"""

    def __init__(
        self,
        slot: str,
        command: list[str],
        config: dict,
        cwd: str,
        env: dict[str, str],
    ) -> None:
        self.slot = slot
        self.command = list(command)
        self.config = config
        self.input_mode: str | None = None
        self._proc: subprocess.Popen | None = None
        self._stdin = None
        self._closing = False
        self._closed = False
        self._dead = threading.Event()
        self._hello: dict | None = None
        self._hello_event = threading.Event()
        self._on_delta = None
        self._delta_error: BaseException | None = None
        self._pending: dict[int, _Waiter] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._next = 1
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                shell=False,
            )
        except OSError as exc:
            raise RuntimeError(
                f"无法启动插件 {slot}：{exc}。命令: {_command_line(self.command)}"
            ) from exc
        self._stdin = self._proc.stdin
        threading.Thread(
            target=_pump,
            args=(slot, self._proc.stderr),
            name=f"lingyu-{slot}-stderr",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stdout,
            name=f"lingyu-{slot}-stdout",
            daemon=True,
        ).start()

    def start(self) -> None:
        hello = self._wait_hello()
        self._validate_hello(hello)
        self.request("configure", {"config": self.config})

    def request(self, method: str, params: dict | None = None, timeout: float = _REQUEST_TIMEOUT) -> dict:
        if self._gone():
            raise self._exited()
        req_id = self._allocate_id()
        waiter = _Waiter()
        with self._pending_lock:
            self._pending[req_id] = waiter
        message: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._write(message)
            deadline = time.monotonic() + timeout
            while not waiter.event.wait(0.05):
                if self._gone():
                    raise self._exited()
                delayed = self._take_delta_error()
                if delayed is not None:
                    raise delayed
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"插件 {self.slot} 响应超时：{method}。命令: {_command_line(self.command)}"
                    )
            delayed = self._take_delta_error()
            if delayed is not None:
                raise delayed
            if waiter.exited or (waiter.result is None and waiter.error is None):
                raise self._exited()
            if waiter.error is not None:
                text = waiter.error.get("message") or "插件返回错误"
                code = waiter.error.get("code")
                raise RpcError(str(text), code if type(code) is int else None)
            return waiter.result or {}
        finally:
            with self._pending_lock:
                self._pending.pop(req_id, None)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._closing = True
        stdin = self._stdin
        self._stdin = None
        if stdin is not None:
            try:
                stdin.close()
            except Exception:
                pass
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        self._dead.set()
        _close_stream(proc.stdout)
        _close_stream(proc.stderr)
        _close_stream(proc.stdin)

    def failed(self) -> bool:
        if self._closing or self._closed:
            return False
        return self._gone()

    def _gone(self) -> bool:
        if self._dead.is_set():
            return True
        proc = self._proc
        return proc is not None and proc.poll() is not None

    def _returncode(self) -> int | None:
        proc = self._proc
        if proc is None:
            return None
        return proc.poll()

    def _exited(self) -> PluginExited:
        return PluginExited(self.slot, self.command, self._returncode())

    def _allocate_id(self) -> int:
        with self._id_lock:
            value = self._next
            self._next += 1
            return value

    def _take_delta_error(self) -> BaseException | None:
        error = self._delta_error
        if error is None:
            return None
        self._delta_error = None
        return error

    def _write(self, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        data = payload + b"\n"
        with self._write_lock:
            stdin = self._stdin
            if stdin is None:
                raise self._exited()
            try:
                stdin.write(data)
                stdin.flush()
            except OSError as exc:
                raise self._exited() from exc

    def _wait_hello(self) -> dict:
        deadline = time.monotonic() + _HELLO_TIMEOUT
        while not self._hello_event.wait(0.05):
            if self._gone():
                raise self._exited()
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"插件 {self.slot} 没有发送 hello。命令: {_command_line(self.command)}"
                )
        return self._hello or {}

    def _validate_hello(self, hello: dict) -> None:
        protocol = hello.get("protocol")
        announced = hello.get("slot")
        if type(protocol) is not int or protocol != 1 or announced != self.slot:
            raise RuntimeError(
                f"插件 {self.slot} 握手失败：protocol 必须是整数 1，slot 必须是 {self.slot}。"
                f"收到 protocol={protocol!r}，slot={announced!r}。"
                f"命令: {_command_line(self.command)}"
            )
        if self.slot == "agent":
            mode = hello.get("input")
            if mode not in ("text", "audio"):
                raise RuntimeError(
                    f"插件 agent 的 input 必须是 text 或 audio，收到 {mode!r}。"
                    f"命令: {_command_line(self.command)}"
                )
            self.input_mode = mode

    def _read_stdout(self) -> None:
        proc = self._proc
        stdout = None if proc is None else proc.stdout
        try:
            if stdout is None:
                return
            while True:
                try:
                    raw = stdout.readline()
                except (OSError, ValueError):
                    break
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[{self.slot}] {line}", file=sys.stderr, flush=True)
                    continue
                if not isinstance(message, dict):
                    print(f"[{self.slot}] {line}", file=sys.stderr, flush=True)
                    continue
                try:
                    self._handle(message)
                except Exception as exc:
                    print(f"[{self.slot}] {exc}", file=sys.stderr, flush=True)
        finally:
            self._mark_dead()
            _close_stream(stdout)

    def _handle(self, message: dict) -> None:
        if "id" in message and ("result" in message or "error" in message):
            self._deliver(message)
            return
        if "id" in message or "method" not in message:
            return
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(method, str):
            return
        if not isinstance(params, dict):
            params = {}
        if method == "hello":
            if not self._hello_event.is_set():
                self._hello = params
                self._hello_event.set()
            return
        if method == "delta":
            self._emit_delta(params)

    def _emit_delta(self, params: dict) -> None:
        # 读线程在这里直接回调。不能拿着本插件的锁：回调会去 speaker.feed，
        # 那条调用要等 speaker 自己的读线程把入队结果读回来。
        callback = self._on_delta
        if callback is None:
            return
        text = params.get("text", "")
        if text is None:
            return
        text = str(text)
        if text == "":
            return
        try:
            callback(text)
        except Exception as exc:
            self._delta_error = exc

    def _deliver(self, message: dict) -> None:
        with self._pending_lock:
            waiter = self._pending.get(message.get("id"))
        if waiter is None:
            return
        if "error" in message and message["error"] is not None:
            error = message["error"]
            if isinstance(error, dict):
                waiter.error = error
            else:
                waiter.error = {"code": 1, "message": str(error)}
        elif "result" in message:
            result = message["result"]
            if result is None:
                result = {}
            if isinstance(result, dict):
                waiter.result = result
            else:
                waiter.error = {"code": 1, "message": "插件 result 必须是对象"}
        else:
            waiter.error = {"code": 1, "message": "插件回答缺少 result"}
        waiter.event.set()

    def _mark_dead(self) -> None:
        self._dead.set()
        with self._pending_lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            if waiter.result is None and waiter.error is None:
                waiter.exited = True
            waiter.event.set()


class _Webui:
    def __init__(self, command: list[str], cwd: str, env: dict[str, str]) -> None:
        self.slot = "webui"
        self.command = list(command)
        self._closing = False
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            shell=False,
        )
        if self._proc.stdout is not None:
            threading.Thread(
                target=_pump,
                args=("webui", self._proc.stdout),
                name="lingyu-webui-stdout",
                daemon=True,
            ).start()
        if self._proc.stderr is not None:
            threading.Thread(
                target=_pump,
                args=("webui", self._proc.stderr),
                name="lingyu-webui-stderr",
                daemon=True,
            ).start()

    def failed(self) -> bool:
        if self._closing:
            return False
        return self._proc.poll() is not None

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        proc = self._proc
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        _close_stream(proc.stdout)
        _close_stream(proc.stderr)

    def returncode(self) -> int | None:
        return self._proc.poll()


class WakeAPI:
    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def accept(self, pcm: np.ndarray, sample_rate: int) -> str:
        result = self._plugin.request("accept", _audio_params(pcm, sample_rate))
        keyword = result.get("keyword", "")
        if keyword is None:
            return ""
        return str(keyword)

    def reset(self) -> None:
        self._plugin.request("reset")

    def strip(self, text: str) -> str:
        result = self._plugin.request("strip", {"text": text})
        command = result.get("command", "")
        if command is None:
            return ""
        return str(command)


class SegmentAPI:
    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def start(self) -> None:
        self._plugin.request("start")

    def push(self, pcm: np.ndarray, sample_rate: int) -> list[tuple[np.ndarray, int]]:
        result = self._plugin.request("push", _audio_params(pcm, sample_rate))
        raw = result.get("utterances", [])
        if not isinstance(raw, list):
            raise RpcError("切句结果缺少 utterances")
        utterances: list[tuple[np.ndarray, int]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise RpcError("切句结果格式不对")
            pcm_text = item.get("pcm")
            rate = item.get("sample_rate")
            if not isinstance(pcm_text, str) or type(rate) not in (int, float):
                raise RpcError("切句结果格式不对")
            utterances.append((decode_pcm(pcm_text), int(rate)))
        return utterances

    def reset(self) -> None:
        self._plugin.request("reset")


class AsrAPI:
    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def transcribe(self, pcm: np.ndarray, sample_rate: int) -> str:
        result = self._plugin.request("transcribe", _audio_params(pcm, sample_rate))
        text = result.get("text", "")
        if text is None:
            return ""
        return str(text)


class AgentAPI:
    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    @property
    def input(self) -> str:
        return self._plugin.input_mode or ""

    def reply(self, text, on_delta=None, *, pcm=None, sample_rate=None) -> str:
        if self.input == "audio":
            if pcm is None or sample_rate is None:
                raise RuntimeError("agent 的 input 是 audio，需要把这一句音频交过去")
            params = _audio_params(pcm, sample_rate)
        else:
            params = {"text": "" if text is None else text}
        plugin = self._plugin
        plugin._delta_error = None
        plugin._on_delta = on_delta
        try:
            result = plugin.request("reply", params)
        finally:
            plugin._on_delta = None
        delayed = plugin._take_delta_error()
        if delayed is not None:
            raise delayed
        answer = result.get("text", "")
        if answer is None:
            return ""
        return str(answer)


class SpeakerAPI:
    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def say(self, text: str) -> None:
        self._plugin.request("say", {"text": text})

    def begin(self) -> None:
        self._plugin.request("begin")

    def feed(self, text: str) -> None:
        self._plugin.request("feed", {"text": text})

    def finish(self) -> None:
        self._plugin.request("finish")

    def cancel(self) -> None:
        self._plugin.request("cancel")


def _load_document(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RuntimeError(f"无法读取启动文件 {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"启动文件不是合法 JSON：{path}（第 {exc.lineno} 行）") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"启动文件的顶层必须是 JSON 对象：{path}")
    return data


def _command_of(section: dict, name: str) -> list[str] | None:
    """槽不存在、没有 command，或 command 为空，都算没有这条命令。"""
    if not isinstance(section, dict) or name not in section:
        return None
    slot = section.get(name)
    if not isinstance(slot, dict) or "command" not in slot:
        return None
    command = slot.get("command")
    if command is None:
        return None
    if not isinstance(command, list):
        raise RuntimeError(f"插件 {name} 的 command 必须是字符串数组")
    if len(command) == 0:
        return None
    parts: list[str] = []
    for part in command:
        if not isinstance(part, str) or part == "":
            raise RuntimeError(f"插件 {name} 的 command 必须是非空字符串数组")
        parts.append(part)
    return parts


def _config_of(section: dict, name: str, extra: dict | None) -> dict:
    slot = section.get(name) if isinstance(section, dict) else None
    raw = {}
    if isinstance(slot, dict):
        raw = slot.get("config", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise RuntimeError(f"插件 {name} 的 config 必须是 JSON 对象")
    config = copy.deepcopy(raw)
    if extra:
        config.update(extra)
    return config


def _prepare_env(startup: Path) -> dict[str, str]:
    load_env()
    os.environ["LINGYU_STARTUP"] = str(startup)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    return os.environ.copy()


class Host:
    def __init__(self, startup: Path) -> None:
        self.startup = Path(startup).resolve()
        self.agent_input = ""
        self.wake: WakeAPI | None = None
        self.segment: SegmentAPI | None = None
        self.asr: AsrAPI | None = None
        self.agent: AgentAPI | None = None
        self.speaker: SpeakerAPI | None = None
        self._cwd = str(self.startup.parent)
        self._env: dict[str, str] = {}
        self._plugins: list[Plugin] = []
        self._by_name: dict[str, Plugin] = {}
        self._webui: _Webui | None = None
        self._closing = False
        self._closed = False

    def check_alive(self) -> None:
        if self._closing or self._closed:
            return
        for plugin in self._plugins:
            if plugin.failed():
                raise plugin._exited()
        webui = self._webui
        if webui is not None and webui.failed():
            raise PluginExited("webui", webui.command, webui.returncode())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._closing = True
        for plugin in self._plugins:
            plugin.close()
        if self._webui is not None:
            self._webui.close()

    def _launch(self, name: str, section: dict, extra: dict | None) -> Plugin:
        command = _command_of(section, name)
        if command is None:
            raise RuntimeError(f"启动文件缺少 {name} 命令")
        plugin = Plugin(name, command, _config_of(section, name, extra), self._cwd, self._env)
        try:
            plugin.start()
        except BaseException:
            plugin.close()
            raise
        self._plugins.append(plugin)
        self._by_name[name] = plugin
        return plugin

    def _launch_webui(self, section: dict) -> None:
        command = _command_of(section, "webui")
        if command is None:
            return
        try:
            self._webui = _Webui(command, self._cwd, self._env)
        except OSError as exc:
            raise RuntimeError(
                f"无法启动插件 webui：{exc}。命令: {_command_line(command)}"
            ) from exc

    def _build_api(self) -> None:
        if "wake" in self._by_name:
            self.wake = WakeAPI(self._by_name["wake"])
        if "segment" in self._by_name:
            self.segment = SegmentAPI(self._by_name["segment"])
        if "asr" in self._by_name:
            self.asr = AsrAPI(self._by_name["asr"])
        if "agent" in self._by_name:
            self.agent = AgentAPI(self._by_name["agent"])
            self.agent_input = self.agent.input
        if "speaker" in self._by_name:
            self.speaker = SpeakerAPI(self._by_name["speaker"])

    def _open_serve(self, *, threads: int | None, voice: str | None, text_mode: bool) -> None:
        self._env = _prepare_env(self.startup)
        data = _load_document(self.startup)
        serve = data.get("serve")
        if not isinstance(serve, dict):
            raise RuntimeError("启动文件缺少 serve")
        self._launch("agent", serve, None)
        mode = self._by_name["agent"].input_mode
        if text_mode:
            if mode != "text":
                raise RuntimeError(f"文本模式要求 agent.input 为 text，当前是 {mode!r}")
            extra = {"voice": voice} if voice else None
            self._launch("speaker", serve, extra)
            self._build_api()
            return
        if mode == "text":
            asr_command = _command_of(serve, "asr")
            if asr_command is None:
                raise RuntimeError("agent 的 input 是 text，但启动文件里没有 asr 命令，缺少转写")
            self._launch("asr", serve, None)
        elif mode == "audio":
            asr_command = _command_of(serve, "asr")
            if asr_command:
                print(
                    f"agent 的 input 是 audio，已跳过 asr。命令: {_command_line(asr_command)}",
                    flush=True,
                )
        wake_extra = {"threads": threads} if threads is not None else None
        self._launch("wake", serve, wake_extra)
        self._launch("segment", serve, None)
        speaker_extra = {"voice": voice} if voice else None
        self._launch("speaker", serve, speaker_extra)
        self._launch_webui(serve)
        self._build_api()

    def _open_listen(self, *, threads: int | None, with_segment: bool) -> None:
        self._env = _prepare_env(self.startup)
        data = _load_document(self.startup)
        listen = data.get("listen")
        if not isinstance(listen, dict):
            raise RuntimeError("启动文件缺少 listen")
        if with_segment:
            self._launch("segment", listen, None)
        asr_extra = {"threads": threads} if threads is not None else None
        self._launch("asr", listen, asr_extra)
        self._build_api()


def start_serve(
    startup: Path,
    *,
    threads: int | None = None,
    voice: str | None = None,
    text_mode: bool = False,
) -> Host:
    host = Host(startup)
    try:
        host._open_serve(threads=threads, voice=voice, text_mode=text_mode)
    except BaseException:
        host.close()
        raise
    return host


def start_listen(startup: Path, *, threads: int | None = None, with_segment: bool = True) -> Host:
    host = Host(startup)
    try:
        host._open_listen(threads=threads, with_segment=with_segment)
    except BaseException:
        host.close()
        raise
    return host
