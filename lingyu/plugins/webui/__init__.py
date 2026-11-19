"""本机设置页。

不进音频环，也不读写 JSON-RPC。启动文件由环境变量 LINGYU_STARTUP 给出。
只监听回环地址。页面可以改 flow，以及 serve、listen 里每个槽的 config。
command 只显示，保存时按文件里的原样写回。
"""

from lingyu.plugins.webui.app import active_server, main, server_ready

__all__ = ["active_server", "main", "server_ready"]
