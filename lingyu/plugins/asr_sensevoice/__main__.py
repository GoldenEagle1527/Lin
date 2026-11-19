from lingyu.plugins.asr_sensevoice.hello import HELLO
from lingyu.plugins.asr_sensevoice.plugin import SenseVoice
from lingyu.plugins.stdio import serve


def main() -> None:
    plugin = SenseVoice()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "transcribe": plugin.transcribe,
        },
    )


if __name__ == "__main__":
    main()
