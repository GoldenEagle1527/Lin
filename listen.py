"""麦克风实时听写。说完一句、停顿约半秒后打印识别结果。

用法:
  .venv\\Scripts\\python.exe listen.py
  .venv\\Scripts\\python.exe listen.py --file 某个.wav
  .venv\\Scripts\\python.exe listen.py --list-devices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sounddevice as sd

from lingyu.loop import run_listen, run_listen_file

ROOT = Path(__file__).resolve().parent


def list_devices() -> None:
    devices = sd.query_devices()
    default_in, _default_out = sd.default.device
    print("输入设备:")
    for index, device in enumerate(devices):
        if device["max_input_channels"] < 1:
            continue
        mark = " *" if index == default_in else "  "
        print(f"{mark}{index}: {device['name']}")
    print("带 * 的是当前默认麦克风。换麦克风: python listen.py --device 编号")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地中文语音识别")
    parser.add_argument("--file", type=Path, help="识别一个 wav 文件后退出")
    parser.add_argument("--device", type=int, help="麦克风设备编号")
    parser.add_argument("--list-devices", action="store_true", help="列出麦克风")
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="推理线程数。缺省用启动文件里该槽的配置，插件默认 4",
    )
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    print("正在加载 SenseVoice...", flush=True)
    startup = ROOT / "lingyu.json"
    if args.file:
        run_listen_file(startup, args.file, threads=args.threads)
        return

    try:
        run_listen(startup, device=args.device, threads=args.threads)
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
