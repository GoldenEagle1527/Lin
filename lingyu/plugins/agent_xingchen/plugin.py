from __future__ import annotations

from lingyu.plugins.stdio import config_of, string_setting, text_of


class Agent:
    def __init__(self) -> None:
        self.chat = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.chat import Xingchen

        config = config_of(params)
        chat = Xingchen()
        model = string_setting(config, "model", "")
        if model:
            chat.model = model
        self.chat = chat
        return {}

    def reply(self, params: dict, notify) -> dict:
        if "pcm" in params and "text" not in params:
            raise RuntimeError("这个实现只接受文字")
        if self.chat is None:
            raise RuntimeError("还没有 configure")
        text = text_of(params)

        def on_delta(piece: str) -> None:
            notify("delta", {"text": piece})

        answer = self.chat.reply(text, on_delta=on_delta)
        return {"text": answer}
