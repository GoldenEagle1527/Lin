"""本机 CosyVoice2。say 和 finish 返回时表示已经播完，feed 只入队。"""

from __future__ import annotations

from lingyu.plugins.stdio import config_of, serve, text_of

HELLO = {
    "protocol": 1,
    "slot": "speaker",
    "settings": [
        {"name": "voice", "type": "string", "default": "", "label": "参考音频路径"},
    ],
}


class Speech:
    def __init__(self) -> None:
        self.speaker = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.tts import Speaker

        config = config_of(params)
        voice = config.get("voice", "")
        if isinstance(voice, str) and voice.strip():
            speaker = Speaker(voice=voice.strip())
        elif voice in ("", None):
            speaker = Speaker()
        else:
            raise ValueError("voice 必须是字符串")
        self.speaker = speaker
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


def main() -> None:
    plugin = Speech()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "say": plugin.say,
            "begin": plugin.begin,
            "feed": plugin.feed,
            "finish": plugin.finish,
            "cancel": plugin.cancel,
        },
    )


if __name__ == "__main__":
    main()
