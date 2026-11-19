"""插件进程共用的标准输入输出协议。"""

from lingyu.plugins.stdio.codec import config_of, decode_pcm, encode_pcm, text_of
from lingyu.plugins.stdio.rpc import Handler, Notify, serve
from lingyu.plugins.stdio.settings import float_setting, int_setting, string_setting

__all__ = [
    "Handler",
    "Notify",
    "config_of",
    "decode_pcm",
    "encode_pcm",
    "float_setting",
    "int_setting",
    "serve",
    "string_setting",
    "text_of",
]
