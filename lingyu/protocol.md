# 凌雨插件协议

这份文件是凌雨插件协议的规范，协议版本为 1。骨架与插件之间只认启动文件 `lingyu.json`，以及标准输入、标准输出上的消息。骨架启动插件进程，不加载、不 import 插件代码。因此任何语言都可以按本文件实现插件。记忆、工具、MCP 都在 Agent 进程内部，不进入本协议；实现 agent 时在该进程内部处理，不要为它们增加消息。

## 启动文件

启动文件是一份 JSON，名为 `lingyu.json`。骨架把它的路径放进环境变量 `LINGYU_STARTUP`。

顶层有三部分：`flow`、`serve`、`listen`。

`flow` 只给骨架用，不放进任何插件的 `configure`。页面可以改启动文件里的 `flow`，骨架下一轮重读。它有三个字段：

- `follow_seconds`：数字，单位秒。
- `preroll_seconds`：数字，单位秒。
- `ack`：字符串，应答语。骨架要播放应答语时，调用 `speaker.say`，`text` 就是 `ack`。

骨架每一轮重新读取 `flow`。修改这些数字后，下一轮生效；`ack` 同样随这一轮重读生效。修改任一槽的 `command` 或 `config` 不会进到已经运行的进程，必须重启该进程。

`serve` 与 `listen` 各是一张槽表。槽的值一律是对象：

- `command`：字符串数组。骨架用这个数组直接创建进程，不经过 shell，不展开通配，也不交给 `cmd` 或 `sh`。
- `config`：对象。走消息的槽由骨架经 `configure` 原样交给该插件，骨架不解释里面的字段。`webui` 自己读启动文件里的 `config`。密钥不出现在启动文件里。骨架在拉起插件之前把 `.env` 载入环境，子进程继承该环境，插件从环境读取密钥。

槽不存在、没有 `command`，或 `command` 为空数组，都算没有这条命令。

拉起规则：

- `serve` 的 `--text` 只拉起 `agent` 和 `speaker`。
- `listen` 麦克风模式拉起 `listen` 段的 `segment` 和 `asr`。`listen --file` 只拉起 `listen` 段的 `asr`，把整段 wav 交给 `transcribe`，不经过 `segment`。

下面只说明形状。其中的数字、应答语和命令都是示例，不是缺省值。

```json
{
  "flow": {
    "follow_seconds": 8,
    "preroll_seconds": 0.5,
    "ack": "在"
  },
  "serve": {
    "wake": {"command": ["python", "-m", "wake_plugin"], "config": {}},
    "segment": {"command": ["python", "-m", "segment_plugin"], "config": {}},
    "asr": {"command": ["python", "-m", "asr_plugin"], "config": {}},
    "agent": {"command": ["python", "-m", "agent_plugin"], "config": {}},
    "speaker": {"command": ["python", "-m", "speaker_plugin"], "config": {}},
    "webui": {"command": ["python", "-m", "webui_plugin"], "config": {"host": "127.0.0.1", "port": 8765}}
  },
  "listen": {
    "segment": {"command": ["python", "-m", "segment_plugin"], "config": {}},
    "asr": {"command": ["python", "-m", "asr_plugin"], "config": {}}
  }
}
```

## 消息

消息是 JSON-RPC 2.0，编码为 UTF-8。标准输出与标准输入上都是一行一条 JSON 对象，对象内部不换行，行尾换行。写出一条之后必须立刻 flush。不使用批量数组，也不使用长度前缀。标准输出上只有协议消息。标准错误是日志，骨架读到后加上槽名再打印。

方向固定：骨架把请求写入插件的标准输入，从插件的标准输出读取通知和回答。

每条消息都有 `"jsonrpc":"2.0"`。`params` 是对象。

- 请求带 `id`。`id` 由骨架分配，本协议使用整数。
- 回答带同一个 `id`。成功时有 `result`，没有 `error`。失败时有 `error`，没有 `result`。
- 通知不带 `id` 字段。不要写成 `"id": null`。通知没有回答。

走这套消息的插件进程起来后，先往标准输出写一条 `hello` 并 flush，然后才读取标准输入、接受调用。骨架先等这条通知，再发 `configure`。`webui` 不在此列。

`hello` 的形状：

```json
{"jsonrpc":"2.0","method":"hello","params":{"protocol":1,"slot":"agent","input":"text","settings":[]}}
```

- `protocol` 必须是整数 `1`。不是 `1` 时，骨架退出，并写明是哪条命令。
- `slot` 必须与启动文件里这个进程的槽名一致，取值是 `wake`、`segment`、`asr`、`agent`、`speaker` 之一。`webui` 不走这套消息。不一致时，骨架退出，并写明是哪条命令。
- `settings` 是字段声明数组，给换插件的人看该插件接受哪些 `config` 字段，不是页面的渲染协议。没有设置就是空数组。每个元素含 `name`（字符串）、`type`（字符串）、`default`（JSON 值）、`label`（中文标签）。设置页不向插件查询 `settings`，也不按这些声明逐项画输入框。页面把每个槽的 `config` 显示成通用 JSON 编辑器，也可以展开源码。保存时只写回 `config` 和 `flow`，`command` 按文件里的原样保留。
- `input` 只有 `agent` 携带，取值是 `text` 或 `audio`。其他槽的 `hello` 不带 `input`。

没有设置项的 `wake`：

```json
{"jsonrpc":"2.0","method":"hello","params":{"protocol":1,"slot":"wake","settings":[]}}
```

带一项设置的声明示例：

```json
{"jsonrpc":"2.0","method":"hello","params":{"protocol":1,"slot":"speaker","settings":[{"name":"voice","type":"string","default":"","label":"音色"}]}}
```

骨架接着发送 `configure`。`params.config` 就是启动文件里该槽的 `config` 对象，字段原样保留。插件回答 `result`，一般是 `{}`。示例见「各槽方法」。

文档里的 `wake.accept` 这种写法表示槽与方法。线上的 `method` 不带槽前缀：发给 `slot` 为 `wake` 的进程、方法名 `accept`。走标准输入输出的进程只实现自己槽的方法，外加共同的 `configure`。同名方法（两端都有的 `reset`）靠进程区分。`webui` 不参加这套消息。

| 文档称呼 | 所在进程的 slot | 线上 method |
| --- | --- | --- |
| configure | wake、segment、asr、agent、speaker | configure |
| wake.accept | wake | accept |
| wake.reset | wake | reset |
| wake.strip | wake | strip |
| segment.start | segment | start |
| segment.push | segment | push |
| segment.reset | segment | reset |
| asr.transcribe | asr | transcribe |
| agent.reply | agent | reply |
| speaker.say | speaker | say |
| speaker.begin | speaker | begin |
| speaker.feed | speaker | feed |
| speaker.finish | speaker | finish |
| speaker.cancel | speaker | cancel |

`hello` 与 `delta` 由插件发往骨架，方法名就是 `hello`、`delta`。

无参数的请求不包含 `params`。插件若收到 `"params":{}`，与不带 `params` 相同。

## 音频

音频编码只有一种：单声道、IEEE 754 二进制 32 位浮点、小端，记法 `<f4`。样本连续排列，没有 WAV 头，也没有其他容器。

消息里的字段：

- `pcm`：这段原始字节的 base64。使用标准 base64，允许末尾填充 `=`。不要加 `data:` 前缀，字符串内部不要换行。
- `sample_rate`：整数，表示每秒样本数。

麦克风进入骨架的采样率是 `16000`。消息里仍然写出实际的 `sample_rate`。朗读产生的音频不传回骨架，由 `speaker` 自己播放。

示例中的 `AACAPw==` 是一个浮点样本 `1.0` 的 base64，只用来演示编码。

## 错误

处理某条请求失败时，插件返回：

```json
{"jsonrpc":"2.0","id":1,"error":{"code":1,"message":"听不清"}}
```

`id` 与该请求相同。`error.code` 为整数 `1`。`error.message` 为字符串。

转写（`asr.transcribe`）或对话（`agent.reply`）失败时，插件按上面的对象回答。骨架打印这条错误，并继续听。

插件进程一旦退出，不论退出码，骨架停掉服务，并写明是哪条命令退出。

## 流式

流式是硬要求。

`agent` 每产出一段字，就发一条没有 `id` 的通知，然后立刻 flush。一段字一到就发，不等整句结束：

```json
{"jsonrpc":"2.0","method":"delta","params":{"text":"今天"}}
```

骨架读到 `delta`，立刻把同一段 `text` 写成 `speaker.feed` 发到 `speaker` 进程，不等 `agent.reply` 的 `result`。

`speaker.feed` 只把字放进合成队列就返回 `{}`，不等这句话说完。

`speaker.finish` 的响应表示已经播完。`speaker.say` 的响应也表示已经播完。朗读走 `delta` 到 `speaker.feed` 这条路径。`reply` 的 `result.text` 是整句，回到骨架。

一次文字对话在线上的顺序如下。`feed` 的 `id` 与 `reply` 的 `id` 各自配对，互不相干。

骨架写入 `agent` 的标准输入：

```json
{"jsonrpc":"2.0","id":7,"method":"reply","params":{"text":"今天天气怎么样"}}
```

`agent` 的标准输出，每行写出后立刻 flush：

```json
{"jsonrpc":"2.0","method":"delta","params":{"text":"今天"}}
```

```json
{"jsonrpc":"2.0","method":"delta","params":{"text":"天气不错。"}}
```

骨架每读到一条，立刻写入 `speaker` 的标准输入，并在收到入队结果后继续，仍然不等 `reply` 的整句：

```json
{"jsonrpc":"2.0","id":1,"method":"feed","params":{"text":"今天"}}
```

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

`agent` 最后给出整句：

```json
{"jsonrpc":"2.0","id":7,"result":{"text":"今天天气不错。"}}
```

骨架调用 `finish`。这条响应要等播放结束才返回：

```json
{"jsonrpc":"2.0","id":2,"method":"finish"}
```

```json
{"jsonrpc":"2.0","id":2,"result":{}}
```

## 各槽方法

除 `webui` 外，每个槽实现下面自己的方法，以及共同的 `configure`。请求写到该槽进程的标准输入，回答从该进程的标准输出读回。空字符串写成 `""`，空数组写成 `[]`，空对象写成 `{}`。

### configure

各槽共同。`params.config` 等于启动文件中该槽的 `config`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"configure","params":{"config":{}}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### wake.accept

参数 `{pcm, sample_rate}`。听到唤醒词时，`keyword` 为该词；没听到就是空字符串。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"accept","params":{"pcm":"AACAPw==","sample_rate":16000}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"keyword":""}}
```

### wake.reset

无参数。结果为 `{}`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"reset"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### wake.strip

参数 `{text}`。去掉句首的名字和语气词，剩下的放进 `command`。句首只剩名字或语气词时，`command` 为空字符串。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"strip","params":{"text":"凌雨今天天气怎么样"}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"command":"今天天气怎么样"}}
```

句首只剩名字时的结果是 `{"command":""}`。

### segment.start

无参数。唤醒后开一段新的切句。结果为 `{}`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"start"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### segment.push

参数 `{pcm, sample_rate}`。结果为 `{utterances:[{pcm, sample_rate}]}`。还没说完就是空数组。切出的音频已经包含端点前后的余量，骨架不再裁剪。每一段仍是本协议的音频编码，并自带 `sample_rate`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"push","params":{"pcm":"AACAPw==","sample_rate":16000}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"utterances":[{"pcm":"AACAPw==","sample_rate":16000}]}}
```

还没说完时，`result` 为 `{"utterances":[]}`。

### segment.reset

无参数。回到待命，丢掉切句状态。结果为 `{}`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"reset"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### asr.transcribe

参数 `{pcm, sample_rate}`。结果为 `{text}`。太短或没听清就是空字符串。失败时用「错误」里的对象；骨架打印并继续听。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"transcribe","params":{"pcm":"AACAPw==","sample_rate":16000}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"text":"今天天气怎么样"}}
```

### agent.reply

`hello.params.input` 决定参数，并决定要不要 `asr`。

- `input` 为 `text`：文字路径，参数是 `{text}`。此时必须有 `asr` 命令，否则启动失败。
- `input` 为 `audio`：音频路径，参数是 `{pcm, sample_rate}`。骨架不起 `asr`。启动文件里若写了 `asr`，骨架跳过，并记一行日志。

处理过程中可以先发零条或多条 `delta` 通知，规则见「流式」。最后的 `result` 为 `{text}`，`text` 是整句。对话失败时用「错误」里的对象；骨架打印并继续听。

文字路径请求：

```json
{"jsonrpc":"2.0","id":1,"method":"reply","params":{"text":"今天天气怎么样"}}
```

音频路径请求：

```json
{"jsonrpc":"2.0","id":1,"method":"reply","params":{"pcm":"AACAPw==","sample_rate":16000}}
```

通知（产出一段就发一条，可重复，先于响应，立刻 flush）：

```json
{"jsonrpc":"2.0","method":"delta","params":{"text":"今天天气不错。"}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"text":"今天天气不错。"}}
```

`serve` 的 `--text` 只拉起 `agent` 和 `speaker`。这条路径把字交给文字路径的 `reply`。

### speaker.say

参数 `{text}`。应答语用它。结果为 `{}`，返回时表示已经播完。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"say","params":{"text":"在"}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### speaker.begin

无参数。结果为 `{}`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"begin"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### speaker.feed

参数 `{text}`。只把字放进合成队列。结果为 `{}`，返回时这句话还不必说完。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"feed","params":{"text":"今天"}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### speaker.finish

无参数。结果为 `{}`。返回时表示已经播完。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"finish"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### speaker.cancel

无参数。结果为 `{}`。

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"cancel"}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

### webui

`webui` 不进音频环，也没有请求方法，所以这里没有请求和响应示例。骨架不向它写标准输入上的消息，只按它的 `command` 拉起进程，骨架退出时关掉该进程。

该进程继承环境变量 `LINGYU_STARTUP`，其值指向启动文件。页面只改 `flow` 和各槽的 `config`，不改 `command`。

绑定使用该槽 `config` 里的 `host` 与 `port`。`host` 缺省 `127.0.0.1`，`port` 缺省 `8765`。`host` 只允许回环地址。
