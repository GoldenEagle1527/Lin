# 凌雨

跑在这台电脑上的语音助手。用户喊醒她，她听完一句，短答，再读出来。

对用户说出口的规则以 `lingyu/chat.py` 里的 `SYSTEM` 为准。改说话方式时，两处一起改。

## 身份

- 名字是凌雨。唤醒词是「凌雨」「你好凌雨」「凌雨凌雨」。识别成林雨、灵雨、凌宇这类近音，也当成在叫她。
- 她是语音助手，不是客服，也不扮演长篇角色。
- 用户的话来自语音识别，会有错字。按最可能的意思理解，不要把错字当话题。

## 怎么说话

- 口语短句，一般一两句，适合被读出来。
- 不用 Markdown、列表、标题、表情和括号里的舞台说明。
- 先给结论。用户追问再补一句。
- 没听清、意思不完整，就短问一句，不要猜着长答。
- 没有联网工具。天气、新闻、股价这类实时信息不要编。不知道就说不知道。
- 对话插件这个进程里记得最近约八轮。进程结束，对话就没了。不要假装记得上次开机说过的话。

## 一轮怎么走

骨架只管麦克风、静音、预滚、待命和续说。唤醒、切句、转写、对话、朗读、设置页各自是一个进程。

登记只有根目录的 `lingyu.json`。换插件只改对应槽的 `command` 数组。插件按 `lingyu/protocol.md` 说话。协议以那份文件为准。密钥只放在 `.env`。

1. 待命。唤醒进程只听唤醒词，闲聊不送去转写。
2. 听到唤醒词，先读 `flow` 里的应答语。缺省是「在」。唤醒前的预滚留给切句，缺省 2 秒，避免名字和正事粘在一起时被切掉。
3. 切句进程切出一句。缺省最短语音约 0.25 秒，停顿约 0.5 秒算一句结束。
4. 对话插件声明 `input` 为 `text` 时，这一句走转写，再把文字交给对话。声明为 `audio` 时不起转写，把切好的一句音频交给对话。缺省的星辰插件是 `text`。星辰转写会丢掉短于 0.2 秒的片段。
5. `text` 这一路，唤醒后的第一句要剥掉句首的名字和语气词。剥完是空的，就等用户接着说，不要空转一轮对话。
6. 对话插件每出一段字就发 `delta`。骨架立刻交给朗读的 `feed`，不等整句。
7. 她自己说话时麦克风静音。说完清掉这段积压的音频，避免把自己的声音听成用户的话。
8. 回答结束后可以接着说，不用再喊名字。这段时间看 `follow_seconds`，缺省 25 秒。超时回到待命。

`flow` 里的数字和应答语下一轮生效。槽的 `config` 或 `command` 改了要重启进程。麦克风模式会一起起设置页，缺省 http://127.0.0.1:8765/ 。页面只改 `flow` 和各槽 `config`，不改 `command`。

直接测一句、不打开麦克风：`serve.py --text`。这条只拉起对话和朗读。

## 现在能做和不能做

能做的只有听、答、读。对话走硅基流动，密钥只放在项目根目录的 `.env`，不要写进代码。

还没有这些能力，不要在回复里假装做过：

- 查网页、查天气、读邮件、控电脑、打开文件
- 跨次记忆
- 用户插话打断正在说的话。这一句会说完，然后才听下一句

`listen.py` 是单独的本地听写，用 SenseVoice，不唤醒、不对话、不上传。

## 代码

| 文件 | 做什么 |
| --- | --- |
| `serve.py` | 对话服务入口。把参数交给骨架 |
| `listen.py` | 本地听写入口 |
| `lingyu/host.py` | 按 `lingyu.json` 拉起插件进程，用标准输入输出收发 |
| `lingyu/loop.py` | 一轮流程：麦克风、静音、预滚、待命、续说，把 `delta` 交给 `feed` |
| `lingyu/protocol.md` | 插件协议 |
| `lingyu.json` | 唯一登记处。`flow`，以及 serve、listen 各槽的 `command` 和 `config` |
| `lingyu/plugins/wake_sherpa.py` | 唤醒槽 |
| `lingyu/plugins/segment_silero.py` | 切句槽 |
| `lingyu/plugins/asr_siliconflow.py` | 对话服务的转写槽 |
| `lingyu/plugins/asr_sensevoice.py` | 听写的转写槽 |
| `lingyu/plugins/agent_xingchen.py` | 对话槽。`input` 为 `text` |
| `lingyu/plugins/speaker_cosyvoice.py` | 朗读槽 |
| `lingyu/plugins/webui.py` | 设置页。自己读启动文件 |
| `lingyu/kws.py` | 唤醒插件内部在用。本机唤醒，以及剥掉句首唤醒词 |
| `lingyu/asr.py` | 切句和 SenseVoice。切句插件、听写转写在用 |
| `lingyu/cloud_asr.py` | 星辰转写，云端转写插件在用。429 和 5xx 会重试 |
| `lingyu/chat.py` | 星辰对话，对话插件在用。流式输出，`max_tokens` 300，不开启思考。约八轮记忆在这个进程里 |
| `lingyu/tts.py` | CosyVoice2，朗读插件在用。按句号、问号切块，逗号至少 8 个字才切 |

采样率不要混用：麦克风和转写是 16 kHz，朗读是 24 kHz。

## 环境

`.env`：

- `SILICONFLOW_API_KEY`：对话和转写共用
- `SILICONFLOW_MODEL`：默认 `XingChenAGI/Xing4.0-29B`
- `SILICONFLOW_ASR_MODEL`：默认 `XingChenAGI/XingChenASR-V3.2-Ultra`
- `LINGYU_VOICE`：CosyVoice2 参考 wav。空着就用官方 zero-shot 提示音
- `LINGYU_PROMPT_TEXT`：这段参考音对应的文本

模型在 `models/`，CosyVoice 源码在 `third_party/`。这两处不进 git。

## 启动

```text
.venv\Scripts\python.exe serve.py
.venv\Scripts\python.exe serve.py --text 现在几点
.venv\Scripts\python.exe listen.py --list-devices
```

`--threads` 只有显式传入才覆盖本次运行的线程数。不写就用启动文件里该槽的配置。`serve.py` 盖到唤醒槽，`listen.py` 盖到听写的转写槽。`--voice` 同样只覆盖本次朗读的参考音。不写就用启动文件。

`--device` 指定麦克风编号。`--text` 直接发一句，不打开麦克风。`listen.py --file` 把整段 wav 交给听写的转写后退出。`--list-devices` 列出麦克风。Ctrl+C 结束。
