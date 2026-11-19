from lingyu.plugins.stdio import serve
from lingyu.plugins.segment_silero.hello import HELLO
from lingyu.plugins.segment_silero.plugin import Segment


def main() -> None:
    plugin = Segment()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "start": plugin.start,
            "push": plugin.push,
            "reset": plugin.reset,
        },
    )


if __name__ == "__main__":
    main()
