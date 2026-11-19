from lingyu.plugins.asr_siliconflow.hello import HELLO
from lingyu.plugins.asr_siliconflow.plugin import CloudAsr
from lingyu.plugins.stdio import serve


def main() -> None:
    plugin = CloudAsr()
    serve(
        HELLO,
        {
            "configure": plugin.configure,
            "transcribe": plugin.transcribe,
        },
    )


if __name__ == "__main__":
    main()
