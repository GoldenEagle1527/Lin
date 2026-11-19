"""凌雨服务：本机听「凌雨」，喊醒后的话走星辰语音识别，回答用语音读出来。

用法:
  .venv\\Scripts\\python.exe serve.py
  .venv\\Scripts\\python.exe serve.py --text 现在几点
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lingyu.loop import run_serve, run_text

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="凌雨：唤醒后才对话")
    parser.add_argument("--text", help="直接发一句话，不打开麦克风")
    parser.add_argument("--device", type=int, help="麦克风设备编号")
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="识别线程数。缺省用启动文件里该槽的配置，插件默认 4",
    )
    parser.add_argument(
        "--voice",
        help="本机 CosyVoice2 参考 wav 路径，默认用官方 zero_shot 提示音",
    )
    args = parser.parse_args()
    startup = ROOT / "lingyu.json"
    if args.text:
        run_text(startup, args.text, voice=args.voice)
        return
    run_serve(startup, device=args.device, threads=args.threads, voice=args.voice)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
