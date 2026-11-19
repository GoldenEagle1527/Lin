"""用临时脚本当插件，不加载 sherpa 或 CosyVoice。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from lingyu.host import start_serve

STUB = r"""
import json
import sys
import time
from pathlib import Path

hello_slot = sys.argv[1]
protocol = int(sys.argv[2])
input_mode = sys.argv[3]
record = sys.argv[4]
mode = sys.argv[5]
marker = sys.argv[6]


def emit(obj):
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


if marker != "-":
    Path(marker).write_text("started", encoding="utf-8")

params = {"protocol": protocol, "slot": hello_slot, "settings": []}
if input_mode != "-":
    params["input"] = input_mode
emit({"jsonrpc": "2.0", "method": "hello", "params": params})

while True:
    raw = sys.stdin.buffer.readline()
    if not raw:
        break
    msg = json.loads(raw.decode("utf-8"))
    method = msg.get("method")
    if method == "configure" and record != "-":
        Path(record).write_text(
            json.dumps(msg["params"]["config"], ensure_ascii=False),
            encoding="utf-8",
        )
    if method == "reply" and mode == "stream":
        emit({"jsonrpc": "2.0", "method": "delta", "params": {"text": "甲"}})
        time.sleep(0.3)
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {"text": "甲乙"}})
        continue
    if "id" in msg:
        emit({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
"""


def write_stub(directory: Path) -> Path:
    path = directory / "stub_plugin.py"
    path.write_text(STUB, encoding="utf-8")
    return path


def command(
    script: Path,
    hello_slot: str,
    *,
    protocol: int = 1,
    input_mode: str | None = None,
    record: Path | None = None,
    mode: str = "plain",
    marker: Path | None = None,
) -> list[str]:
    return [
        sys.executable,
        str(script),
        hello_slot,
        str(protocol),
        input_mode if input_mode is not None else "-",
        str(record) if record is not None else "-",
        mode,
        str(marker) if marker is not None else "-",
    ]


def write_startup(path: Path, serve: dict) -> None:
    document = {
        "flow": {"follow_seconds": 25, "preroll_seconds": 2.0, "ack": "在"},
        "serve": serve,
        "listen": {},
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slot(cmd: list[str], config: dict | None = None) -> dict:
    return {"command": cmd, "config": {} if config is None else config}


class HostTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.script = write_stub(self.root)

    def test_hello_rejected(self) -> None:
        cases = (
            ("protocol", 2, "agent"),
            ("slot", 1, "nope"),
        )
        for name, protocol, announced in cases:
            with self.subTest(name=name):
                folder = self.root / name
                folder.mkdir()
                script = write_stub(folder)
                startup = folder / "lingyu.json"
                write_startup(
                    startup,
                    {
                        "agent": slot(
                            command(
                                script,
                                announced,
                                protocol=protocol,
                                input_mode="text",
                            )
                        )
                    },
                )
                with self.assertRaises(Exception) as caught:
                    start_serve(startup, text_mode=True)
                self.assertIn(str(script), str(caught.exception))

    def test_text_agent_requires_asr(self) -> None:
        startup = self.root / "lingyu.json"
        write_startup(
            startup,
            {
                "agent": slot(command(self.script, "agent", input_mode="text")),
                "wake": slot(command(self.script, "wake")),
                "segment": slot(command(self.script, "segment")),
                "speaker": slot(command(self.script, "speaker")),
            },
        )
        with self.assertRaises(Exception) as caught:
            start_serve(startup)
        self.assertIn("转写", str(caught.exception))

    def test_audio_agent_skips_asr(self) -> None:
        marker = self.root / "asr-started"
        startup = self.root / "lingyu.json"
        asr_command = command(self.script, "asr", marker=marker)
        write_startup(
            startup,
            {
                "agent": slot(command(self.script, "agent", input_mode="audio")),
                "asr": slot(asr_command),
                "wake": slot(command(self.script, "wake")),
                "segment": slot(command(self.script, "segment")),
                "speaker": slot(command(self.script, "speaker")),
            },
        )
        captured = StringIO()
        with redirect_stdout(captured):
            host = start_serve(startup)
        self.addCleanup(host.close)
        self.assertIsNone(host.asr)
        self.assertFalse(marker.exists())
        self.assertIn("跳过", captured.getvalue())

    def test_delta_is_delivered_before_result(self) -> None:
        startup = self.root / "lingyu.json"
        write_startup(
            startup,
            {
                "agent": slot(command(self.script, "agent", input_mode="text", mode="stream")),
                "speaker": slot(command(self.script, "speaker")),
            },
        )
        host = start_serve(startup, text_mode=True)
        self.addCleanup(host.close)
        holder: dict = {}

        def work() -> None:
            def on_delta(text: str) -> None:
                holder["delta_at"] = time.monotonic()
                holder["delta"] = text
                host.speaker.feed(text)

            holder["result"] = host.agent.reply("你好", on_delta)
            holder["done_at"] = time.monotonic()

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(3)
        self.assertFalse(worker.is_alive(), "reply 没有及时返回")
        self.assertEqual(holder["delta"], "甲")
        self.assertEqual(holder["result"], "甲乙")
        self.assertGreaterEqual(holder["done_at"] - holder["delta_at"], 0.2)

    def test_configure_receives_file_config(self) -> None:
        agent_config = {"name": "凌雨", "n": 2, "ok": True, "items": ["a", "b"]}
        speaker_config = {"voice": "demo.wav", "gain": 1.5}
        agent_record = self.root / "agent-config.json"
        speaker_record = self.root / "speaker-config.json"
        startup = self.root / "lingyu.json"
        write_startup(
            startup,
            {
                "agent": slot(
                    command(self.script, "agent", input_mode="text", record=agent_record),
                    agent_config,
                ),
                "speaker": slot(
                    command(self.script, "speaker", record=speaker_record),
                    speaker_config,
                ),
            },
        )
        host = start_serve(startup, text_mode=True)
        self.addCleanup(host.close)
        self.assertEqual(json.loads(agent_record.read_text(encoding="utf-8")), agent_config)
        self.assertEqual(json.loads(speaker_record.read_text(encoding="utf-8")), speaker_config)


if __name__ == "__main__":
    unittest.main()
