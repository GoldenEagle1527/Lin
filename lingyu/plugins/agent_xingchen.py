"""星辰对话。只接受文字；出字时先发 delta，再返回整句。"""

from __future__ import annotations

from lingyu.plugins.stdio import config_of, serve, text_of

HELLO = {
    "protocol": 1,
    "slot": "agent",
    "input": "text",
    "settings": [
        {"name": "model", "type": "string", "default": "", "label": "对话模型"},
    ],
}


class Agent:
    def __init__(self) -> None:
        self.chat = None

    def configure(self, params: dict, _notify) -> dict:
        from lingyu.chat import Xingchen

        config = config_of(params)
        chat = Xingchen()
        model = config.get("model", "")
        if isinstance(model, str) and model.strip():
            chat.model = model.strip()
        elif model not in ("", None) and not isinstance(model, str):
            raise ValueError("model 必须是字符串")
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


def main() -> None:
    plugin = Agent()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "reply": plugin.reply,
        },
    )


if __name__ == "__main__":
    main()
