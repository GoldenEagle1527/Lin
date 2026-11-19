from __future__ import annotations

from lingyu.plugins.stdio import config_of, decode_pcm, int_setting, text_of


class Wake:
    def __init__(self) -> None:
        self.spotter = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.kws import WakeSpotter

        config = config_of(params)
        self.spotter = WakeSpotter(num_threads=int_setting(config, "threads", 4))
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
