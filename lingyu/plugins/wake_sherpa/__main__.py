from lingyu.plugins.stdio import serve
from lingyu.plugins.wake_sherpa.hello import HELLO
from lingyu.plugins.wake_sherpa.plugin import Wake


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
