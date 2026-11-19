from lingyu.plugins.speaker_cosyvoice.hello import HELLO
from lingyu.plugins.speaker_cosyvoice.plugin import Speech
from lingyu.plugins.stdio import serve


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
