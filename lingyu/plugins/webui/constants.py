DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 1_048_576
LOOPBACK_NOTE = "只允许回环地址 127.0.0.1、localhost、::1。"
SAVED_NOTE = "已保存。流程数字下一轮生效，更换插件配置需要重启进程。"

GROUPS = ("serve", "listen")
GROUP_TITLES = {"serve": "对话服务", "listen": "本地听写"}
SLOT_LABELS = {
    "wake": "唤醒",
    "segment": "切句",
    "asr": "转写",
    "agent": "对话",
    "speaker": "朗读",
    "webui": "设置页",
}
