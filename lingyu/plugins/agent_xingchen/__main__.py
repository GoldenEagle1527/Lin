from lingyu.plugins.agent_xingchen.hello import HELLO
from lingyu.plugins.agent_xingchen.plugin import Agent
from lingyu.plugins.stdio import serve


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
