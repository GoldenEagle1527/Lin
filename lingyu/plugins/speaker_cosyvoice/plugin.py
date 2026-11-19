from __future__ import annotations

from lingyu.plugins.stdio import config_of, string_setting, text_of


class Speech:
    def __init__(self) -> None:
        self.speaker = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.tts import Speaker

        config = config_of(params)
        voice = string_setting(config, "voice", "")
        self.speaker = Speaker(voice=voice) if voice else Speaker()
        return {}

    def _ready(self):
        if self.speaker is None:
            raise RuntimeError("还没有 configure")
        return self.speaker

    def say(self, params: dict, _notify) -> dict:
        self._ready().say(text_of(params))
        return {}

    def begin(self, _params: dict, _notify) -> dict:
        self._ready().begin()
        return {}

    def feed(self, params: dict, _notify) -> dict:
        self._ready().feed(text_of(params))
        return {}

    def finish(self, _params: dict, _notify) -> dict:
        self._ready().finish()
        return {}

    def cancel(self, _params: dict, _notify) -> dict:
        self._ready().cancel()
        return {}
