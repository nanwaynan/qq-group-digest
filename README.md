# QQ 群聊总结器（qq-group-digest）

A local-only tool that pulls a QQ group's chat history for a whole day and uses any OpenAI-compatible LLM to generate a structured Markdown digest.

拉取 QQ 群一整天的聊天记录，交给大模型生成结构化 Markdown 总结，按日期自动归档到本地文件夹。

**全程本地运行 · 不向群聊发送任何消息 · 无定时任务 · 仅 Python 标准库，零第三方依赖。**

---

## 先回答你最关心的问题：我的 API Key 会被作者拿到吗？

**不会。** 这不是一句口头承诺，是可以逐条验证的事实：

1. **Key 只存在于你本机的 `config.json`**，该文件已被 [.gitignore](.gitignore) 排除，永远不会进入你自己的 git 仓库；
2. 本项目**没有任何遥测、统计、版本检查**，代码里不存在除以下两处之外的任何网络请求（可在 [qq_digest.py](qq_digest.py) 中全局搜索 `urlopen` 自行验证）：
   - `POST {napcat_api}/...` —— 你自己填的 NapCat 地址（默认 `http://127.0.0.1:3000`，即你本机）；
   - `POST {ai.base}/chat/completions` —— 你自己填的 AI 接口地址；
3. 聊天记录只会发送到**你自己填的** AI 接口（用于总结），不会发给作者或任何第三方；
4. 代码里不存在 `send_group_msg` 等任何发消息接口调用，**绝不会向群聊发送内容**；
5. 全部功能就是一个几百行的 Python 单文件，只依赖标准库，欢迎通读审计。

首次运行时脚本会引导你输入群号、AI 接口地址和 Key（Key 输入不回显），写入本地 `config.json` 后就不再需要输入。

---

## 功能特性

- 📥 **完整回溯**：自动分页拉取指定群一整天（12:00 ~ 次日 12:00）的全部聊天记录，单日数千条不漏
- 🧠 **AI 深度总结**：生成结构化 Markdown 报告（概览 / 主要话题 / 有价值的信息 / 精彩发言 / 活跃成员）
- 📄 **长文分块**：记录过长时自动分块总结再汇总，避免上下文截断导致信息丢失
- 🗂️ **按日归档**：输出到 `output/<群名>/<YYMMDD>/<YYMMDD>.md`，一天一个文件夹，支持多个群
- 🔒 **纯本地**：不发群、无定时、无开机自启，完全手动触发
- 🩺 **连通性自检**：`--check` 一条命令验证 NapCat、群成员身份、AI 接口、输出目录

---

## 系统架构

```
┌──────────────────┐
│  QQ 客户端 (NTQQ) │ ← 用你的小号登录
└────────┬─────────┘
         │ NapCat 注入
┌────────▼─────────┐         OneBot 11 HTTP API
│      NapCat      │ ────────────────────────────┐
│  (OneBot 协议端)  │    http://127.0.0.1:3000    │
└──────────────────┘                              ▼
                                       ┌─────────────────────┐
                                       │    qq_digest.py      │
                                       │ （单文件，仅标准库）   │
                                       └──────────┬──────────┘
                                                  │ OpenAI 兼容接口
                                                  ▼
                                       ┌─────────────────────┐
                                       │  你配置的大模型 API    │
                                       │ （本地推理/云端均可）  │
                                       └──────────┬──────────┘
                                                  │
                                                  ▼
                                    output/<群名>/261009/261009.md
```

| 组件 | 作用 |
|---|---|
| **QQ 客户端 (NTQQ)** | 消息的实际载体 |
| **NapCat** | 注入 QQ 客户端，把消息封装成 OneBot 11 标准接口（[NapCatQQ](https://github.com/NapNeko/NapCatQQ)） |
| **qq_digest.py** | 核心脚本：拉取消息 → 调用 AI → 写入 md 文件 |
| **大模型 API** | 任意 OpenAI 兼容接口（本地推理如 Ollama，或云端服务均可） |

> 本项目是独立脚本，不包含也不依赖任何机器人框架（AstrBot 等）的代码，只通过 NapCat 暴露的 OneBot 11 HTTP API 通信。

---

## 快速开始

### 前置条件

- Python 3.10+（无 pip 依赖，装好 Python 就够了）
- 一台能运行桌面版 QQ 的电脑（Windows / Linux / macOS）
- 一个 OpenAI 兼容的大模型 API（地址 + 模型名 + Key）

### 三步跑通

**① 部署 NapCat，用 QQ 小号登录**

1. 安装新版 QQ 客户端（NTQQ）；
2. 按照 [NapCat 官方文档](https://napneko.github.io/) 安装 NapCat（Shell / Framework / Docker 方式均可）；
3. 首次启动用**小号**扫码登录（建议专门注册一个小号拉进目标群，主号零改动）；
4. 给 NapCat 开启 OneBot 11 HTTP 服务，见下方 [NapCat 配置](#napcat-配置)。

**② 下载本项目，运行配置向导**

```bash
git clone https://github.com/<你>/qq-group-digest.git
cd qq-group-digest
python qq_digest.py        # 自动进入配置向导
```

向导会依次问你：NapCat 地址 → 要总结的**群号**（可多个）→ **AI 接口地址 / 模型名 / API Key** → 保存目录，然后写入本地 `config.json` 并立即开始第一次总结。

**③ 完成**

总结文件在 `output/<群名>/<YYMMDD>/<YYMMDD>.md`，以后每天想总结就再跑一次：

```bash
python qq_digest.py                # 总结最近一个已结束的完整周期（最常用）
python qq_digest.py --check        # 不确定环境是否正常？先自检
```

Windows 用户也可以直接双击 `run.bat`。

---

## NapCat 配置

最简单的方式是在 NapCat WebUI（默认 `http://localhost:6099`）→ 网络配置 → 新建 **HTTP 服务器**：端口 `3000`、host `127.0.0.1`、开启即可。

也可以手动编辑 NapCat 的 `config/onebot11_<你的QQ号>.json`：

```json
{
  "network": {
    "httpServers": [{
      "name": "api",
      "enable": true,
      "port": 3000,
      "host": "127.0.0.1",
      "enableCors": true,
      "enableWebsocket": false
    }]
  }
}
```

注意事项（都是实测踩出来的）：

- `config/onebot11_<QQ号>.json` **优先于** 通用的 `config/onebot11.json`，改通用文件不生效是正常的；
- 如果你在 NapCat 侧设置了 token，把同样的 token 填进本项目 `config.json` 的 `napcat_token` 即可；
- HTTP 服务请保持只监听 `127.0.0.1`，**不要暴露到公网**；
- 拉取历史的前提：登录 NapCat 的账号是目标群的成员，能正常看到群历史消息。

---

## 配置参考

`config.json`（由向导生成，或复制 `config.example.json` 修改）：

| 字段 | 说明 | 默认 |
|---|---|---|
| `napcat_api` | NapCat OneBot 11 HTTP API 地址 | `http://127.0.0.1:3000` |
| `napcat_token` | NapCat HTTP 服务若设置了 token 则填写 | 空 |
| `groups` | 要总结的群列表，`{"id": "群号", "name": "群名称/备注"}`，可多个 | — |
| `ai.base` | OpenAI 兼容接口地址（**含 `/v1`**），如 `https://api.openai.com/v1` | — |
| `ai.model` | 模型名 | — |
| `ai.key` | API Key（只存在本机） | — |
| `output_dir` | 总结保存目录，`./output` 相对运行目录 | `./output` |
| `day_start_hour` | 「一天」从几点开始 | `12` |
| `chunk_chars` | 超过该字符数则分块总结 | `22000` |
| `max_tokens` | 单次 AI 调用上限；**推理模型请给足**，否则思维链会吃光预算导致正文为空 | `32000` |

---

## 命令行用法

```bash
python qq_digest.py                  # 最近一个已结束的完整周期（最常用）
python qq_digest.py --date 2026-10-09
python qq_digest.py --include-current    # 强行总结尚未结束的当前周期
python qq_digest.py --group 123456       # 只总结某一个群（配置外的群号也可临时指定）
python qq_digest.py --max 5000           # 限制拉取条数（默认 60000）
python qq_digest.py --dry-run            # 只拉取消息并统计，不调用 AI、不写文件
python qq_digest.py --check              # 测试 NapCat / AI 接口连通性
python qq_digest.py --setup              # 重新运行配置向导
python qq_digest.py --config /path/to/config.json   # 指定配置文件
```

### 时间口径

**一天 = 当天 12:00 到次日 12:00**，文件名以周期起点日期命名：

| 文件 | 覆盖的聊天时间段 |
|---|---|
| `261009.md` | 10月9日 12:00 ~ 10月10日 12:00 |
| `261008.md` | 10月8日 12:00 ~ 10月9日 12:00 |

这样设计的考虑：午间是讨论的天然分界点，前一天下午到当天上午的讨论归为一期；且生成时间落在中午，不会与当晚的活跃讨论重叠。默认只总结**已结束**的完整周期（`--include-current` 可强行总结当前周期）。

### 输出格式

每个 md 文件包含两部分：

1. **AI 总结正文**：本期概览 / 主要话题 / 有价值的信息 / 精彩发言 / 活跃成员；
2. **原始聊天记录**（Markdown 折叠块，便于溯源核对）。

---

## 自测（不需要真实 QQ 和 Key）

项目自带一个端到端测试：在 `127.0.0.1` 上临时起一个模拟 NapCat 和模拟 AI 接口，完整走一遍「分页回溯 → 区间过滤 → 分块总结 → 汇总 → 归档输出」：

```bash
python tests/test_mock.py
```

在别的机器上部署完 Python 后先跑这个，通过即说明脚本本身没问题，剩下只是 NapCat 的环境问题。

---

## FAQ

### 为什么不提供 Docker 镜像？

**结论：没必要。** 原因：

1. 本工具依赖 NapCat 注入**桌面版 QQ**，QQ 必须跑在你的电脑上；总结脚本本身只是一个标准库单文件，为它装 Docker 没有任何收益，反而多一层环境要求；
2. 脚本零依赖，任何有 Python 3.10+ 的机器上 `python qq_digest.py` 直接就能跑；
3. 如果你确实想容器化（比如配 NapCat 官方 Docker 版在服务器上无人值守），无需 Dockerfile，一行命令即可：

```bash
docker run --rm -v "$(pwd)":/app -w /app python:3.12 python qq_digest.py
```

### 能不能自动每天定时总结？

本项目刻意**不带定时**（保持纯手动、无后台进程）。需要的话用系统自带的定时能力调用一次即可：Windows 任务计划程序 / Linux crontab，定时执行 `python qq_digest.py`。

### 能总结多久之前的历史？

能拉取的范围受 QQ 自身消息记录（本地缓存 + 云端漫游）限制。建议定期（每天）运行，不要指望一次回溯几个月。群一天几千条消息时，拉取约一两分钟。

### 常见报错

| 现象 | 原因与处理 |
|---|---|
| `WinError 10061 连接被拒绝` | NapCat 没启动，或端口不对。先启动 NapCat 并登录，再 `python qq_digest.py --check` |
| `--check` 显示某群「查询失败」 | 登录 NapCat 的账号不在该群（小号要先入群） |
| 总结内容异常偏少或为空 | ① AI 侧 `max_tokens` 太小，推理模型思维链吃光预算导致正文为空——把 `max_tokens` 调大（默认 32000）；② NapCat 未开启 HTTP 服务或 token 不匹配 |
| AI 返回 `HTTP 401/403` | Key 无效或没权限访问该模型，检查 `ai.key` / `ai.model` |
| AI 返回 `HTTP 404` | `ai.base` 地址不对（注意要含 `/v1`），或模型名不存在 |
| 单次运行耗时较长 | 正常。几千条消息的拉取 + 分块总结通常需要几分钟，取决于 AI 服务速度 |

<details>
<summary>给贡献者：NapCat 分页的隐藏要求（脚本已内置处理）</summary>

`get_group_msg_history` 的分页机制有两个隐藏要求：

- 锚点用**本页最旧消息的 `message_id`** 传给 `message_seq`；
- **必须同时传 `reverse_order: true`**。

缺了 `reverse_order`，无论锚点传什么，每页都返回同一段最新消息。实测同一周期拉取量：191 条（错误）→ 4871 条（正确），相差 25 倍。

另外：NapCat 的短 ID 映射表只包含**进程启动后收到过**的消息，翻历史不要用响应里的 `real_seq` 作锚点（查不到会返回空），应使用 `message_id`（实测唯一稳定锚点）。群消息量大时翻页偶发超时，脚本对单页失败会跳过重试并继续回溯，连续多页失败才终止，不会前功尽弃。

</details>

---

## 隐私说明

- 聊天记录与总结全部保存在本地，脚本本身**不上传任何数据**；
- 是否外发取决于你配置的大模型 API：本地推理（如 Ollama）可完全离线；云端 API 则聊天内容会发送给对应服务商；
- 请遵守当地法律法规与平台用户协议，仅用于整理**自己有权访问**的群聊。

## 项目结构

```
├── qq_digest.py          # 核心脚本（唯一必需，仅标准库）
├── config.example.json   # 配置模板（复制为 config.json 使用）
├── config.json           # 本地配置（含 Key，已被 .gitignore 排除，首次运行自动生成）
├── run.bat               # Windows 双击运行
├── tests/
│   └── test_mock.py      # 端到端自测（模拟 NapCat + AI）
└── output/               # 总结输出（已被 .gitignore 排除）
```

## License

[MIT](LICENSE)
