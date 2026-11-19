"""本机唤醒。WakeSpotter 在 configure 时才构造。"""

from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm, serve, text_of

HELLO = {
    "protocol": 1,
    "slot": "wake",
    "settings": [
        {"name": "threads", "type": "int", "default": 4, "label": "识别线程数"},
    ],
}


def _threads(config: dict) -> int:
    value = config.get("threads", 4)
    if value is None or value == "":
        return 4
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threads 必须是整数")
    return int(value)


class Wake:
    def __init__(self) -> None:
        self.spotter = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.kws import WakeSpotter

        config = config_of(params)
        self.spotter = WakeSpotter(num_threads=_threads(config))
        return {}

    def _ready(self):
        if self.spotter is None:
            raise RuntimeError("还没有 configure")
        return self.spotter

    def accept(self, params: dict, _notify) -> dict:
        spotter = self._ready()
        samples = decode_pcm(params, expect_rate=spotter.sample_rate)
        return {"keyword": spotter.accept(samples)}

    def reset(self, _params: dict, _notify) -> dict:
        self._ready().reset()
        return {}

    def strip(self, params: dict, _notify) -> dict:
        from lingyu.kws import command_after_wake

        return {"command": command_after_wake(text_of(params))}


def main() -> None:
    plugin = Wake()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "accept": plugin.accept,
            "reset": plugin.reset,
            "strip": plugin.strip,
        },
    )


if __name__ == "__main__":
    main()
