# QQ 群聊总结器 v1.0（qq-group-digest）

**双击一个脚本，把群里一整天的聊天记录变成一份可以永久保存的 Markdown 总结** —— AI 生成、重点图片保留、按日归档；不发群、无定时、零第三方依赖，你的 API Key 只存在你自己电脑上。

[![Release](https://img.shields.io/github/v/release/nanwaynan/qq-group-digest?label=release&color=2ea043)](https://github.com/nanwaynan/qq-group-digest/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-0078d4)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org/downloads/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)]()
[![向群聊发消息](https://img.shields.io/badge/向群聊发消息-0-red)]()
[![定时任务](https://img.shields.io/badge/定时任务-0-red)]()
[![遥测上报](https://img.shields.io/badge/遥测上报-0-red)]()

> ## 📌 当前状态（v1.0 · 2026-10-11）
> - **核心流程已实测可用** —— 单日数千条消息完整回溯、分块总结再汇总、按日归档，全部跑通。
> - **图片保留** —— 群里的重要图片会存到本地并在总结中内嵌，不再是一排 `[图片]` 占位符。
> - **多群支持** —— 配置里加几个群就总结几个群，一次跑完。
> - **微信版、图形界面** 在计划中，见文末「开发计划」。
> - 只想快速跑起来？直接看「快速开始」四步，配合 `python qq_digest.py --check` 自检。

> ## ⚠️ 使用前提（务必先读）
> 本工具只读取**你登录的 QQ 账号有权查看**的群聊记录，请遵守当地法律法规与平台用户协议，仅用于整理自己有权访问的群聊；使用产生的一切后果由使用者自行承担。完整说明见文末免责声明。

## 为什么做这个

每天 QQ 群里的信息量太大了，爬楼根本爬不完。QQ 自带的元宝总结确实能帮一把，但**看完就没了，留不下存档，也没法一天一天连续地总结下去**。

这个工具把每一天的群聊沉淀成一份 Markdown 文件：AI 帮你读完几千条消息，挑出话题、干货、精彩发言；重要图片也一起保留。今天写的，明年还能翻出来查。

## 为什么值得一试

- 📥 **完整回溯** —— 自动分页拉取指定群一整天（12:00 ~ 次日 12:00）的全部记录，单日数千条不漏；单页失败自动跳过重试，不会前功尽弃
- 🖼️ **图片保留** —— 聊天中的图片自动存到本地，AI 引用到的图片直接内嵌在总结正文里，其余的收进文末图片列表
- 🧠 **AI 深度总结** —— 结构化报告：本期概览 / 主要话题 / 有价值的信息 / 精彩发言 / 活跃成员
- 📄 **长文分块** —— 记录过长自动分块总结再汇总，避免上下文截断丢信息；推理模型的 token 配额坑已处理
- 🗂️ **按日归档 + 多群** —— `output/<群名>/<YYMMDD>/<YYMMDD>.md`，一天一个文件夹，几个群一起跑
- 🔒 **纯本地 & 零依赖** —— 不发群、无定时、无自启、无遥测；纯 Python 标准库，装个 Python 就能跑
- 🩺 **一条命令自检** —— `--check` 验证 NapCat、登录账号、群成员身份、AI 接口、输出目录
- 🙈 **Key 不出本机** —— 首次运行向导式输入，Key 只写进本地 `config.json`（已被 .gitignore 排除），全文可审计

## 快速开始

前置条件：Python 3.10+；一个 OpenAI 兼容的大模型 API（地址 + 模型名 + Key）。

1. **部署 NapCat，用 QQ 小号登录** —— 安装新版 QQ（NTQQ）→ 按 [NapCat 官方文档](https://napneko.github.io/) 安装 → 小号扫码登录 → 建议专门注册一个小号拉进目标群，主号零改动
2. **给 NapCat 开启 OneBot 11 HTTP 服务** —— WebUI（默认 `http://localhost:6099`）→ 网络配置 → 新建 HTTP 服务器：端口 `3000`、host `127.0.0.1`、开启
3. **运行配置向导** —— 下载本项目后：

   ```bash
   python qq_digest.py
   ```

   向导依次问你：**NapCat 地址 → 要总结的群号（可多个）→ AI 接口地址 / 模型名 / API Key → 保存目录**，写进本地 `config.json` 后立即开始第一次总结

4. **看结果** —— 打开 `output\<群名>\<YYMMDD>\<YYMMDD>.md`；以后每天想总结就再跑一次，或双击 `run.bat`

> 卡在哪一步？先跑 `python qq_digest.py --check`，它会告诉你 NapCat 通不通、小号在不在群里、AI 接口能不能用。

## 总结文件放在哪

默认在**项目文件夹下的 `output\` 目录**，按「群名 → 日期」两层归档：

```
qq-group-digest\
└─ output\
   └─ 深度思考\                ← 群名（或群号）
      └─ 261011\
         ├─ 261011.md          ← 总结正文 + 图片 + 完整原始记录
         └─ images\
            ├─ 001_1433_张三.jpg
            └─ ...
```

想换地方（比如存到桌面）：改 `config.json` 里的 `output_dir`，填绝对路径即可。

## 命令行

```bash
python qq_digest.py                  # 总结最近一个已结束的完整周期（最常用）
python qq_digest.py --date 2026-10-09
python qq_digest.py --include-current    # 强行总结尚未结束的当前周期
python qq_digest.py --group 123456       # 只总结某一个群（配置外的群号也可临时指定）
python qq_digest.py --max 5000           # 限制拉取条数（默认 60000）
python qq_digest.py --dry-run            # 只拉取消息并统计，不调用 AI、不写文件
python qq_digest.py --no-images          # 本次不保留图片
python qq_digest.py --check              # 自检 NapCat / AI 接口连通性
python qq_digest.py --setup              # 重新运行配置向导
python qq_digest.py --version
```

## 图片保留是怎么做的

1. 拉取记录时给每张图片登记来源（QQ 多媒体链接，失效时用本地缓存兜底）；
2. 并发下载（单期上限默认 100 张、单张 15MB，可在配置改），**下载成功的才给正式编号**，失效的自动还原为 `[图片]` 占位；
3. 总结正文里，AI 判断「这里在讨论某张图」时会标注图片编号，脚本把编号替换成真实图片内嵌到正文；
4. 其余成功下载的图片收进文末「附：本期图片」折叠列表，附发言人和时间。

> 说明：QQ 的历史图片链接有时效性，太久之前的图片可能下载不回来——越勤跑，留得越全。

## 配置参考

`config.json`（向导生成，或复制 `config.example.json` 修改）：

| 字段 | 说明 | 默认 |
|---|---|---|
| `napcat_api` | NapCat OneBot 11 HTTP API 地址 | `http://127.0.0.1:3000` |
| `napcat_token` | NapCat HTTP 服务若设了 token 则填写 | 空 |
| `groups` | 要总结的群列表 `{"id": "群号", "name": "群名称/备注"}`，可多个 | — |
| `ai.base` | OpenAI 兼容接口地址（**含 `/v1`**） | — |
| `ai.model` | 模型名 | — |
| `ai.key` | API Key（只存本机） | — |
| `output_dir` | 总结保存目录 | `./output` |
| `day_start_hour` | 「一天」从几点开始 | `12` |
| `chunk_chars` | 超过该字符数则分块总结 | `22000` |
| `max_tokens` | 单次 AI 调用上限；**推理模型请给足** | `32000` |
| `save_images` | 是否保留图片 | `true` |
| `max_images` | 单期最多保留多少张 | `100` |

### 时间口径

**一天 = 当天 12:00 到次日 12:00**（午间是讨论的天然分界点），文件名以周期起点命名：`261011.md` 覆盖 10月11日 12:00 ~ 10月12日 12:00。默认只总结**已结束**的完整周期，`--include-current` 强行总结当前周期。

## 安全 & 隐私

| 设计 | 原因 |
|---|---|
| **Key 只存本机 `config.json`** | 该文件被 `.gitignore` 排除，永远不会进 git 仓库 |
| **网络请求只有两处** | 你填的 NapCat 地址（默认本机）+ 你填的 AI 接口；可全局搜索 `urlopen` 逐条核对 |
| **零遥测** | 没有统计、没有版本检查、没有"回调 home" |
| **不发群** | 代码里不存在任何发消息接口调用（搜 `send_group_msg` 无结果） |
| **无定时无自启** | 纯手动触发，跑完就退出，不留后台进程 |
| **聊天记录只发给你自己填的 AI** | 不会发给作者或任何第三方；用本地推理（如 Ollama）可完全离线 |

## 自测（不需要真实 QQ 和 Key）

项目自带端到端测试：本地起一个模拟 NapCat 和模拟 AI 接口，完整走「分页回溯 → 图片下载与失效回退 → 分块总结 → 汇总 → 归档」：

```bash
python tests/test_mock.py
```

在别的机器部署完 Python 先跑这个，通过即说明脚本本身没问题，剩下的只是 NapCat 环境问题。

## 文件说明

```
qq-group-digest/
├─ qq_digest.py            核心脚本（纯标准库，唯一必需）
├─ config.example.json     配置模板（复制为 config.json 使用）
├─ config.json             本地配置（含 Key，自动生成，不会上传）
├─ run.bat                 Windows 双击入口
├─ tests/test_mock.py      端到端自测
├─ output/                 总结输出（自动生成，不会上传）
├─ README.md · LICENSE(MIT) · .gitignore
```

## 常见问答

**Q：我的 API Key 会被作者拿到吗？**
不会。Key 只存在你本机的 `config.json`；本项目没有遥测，全部网络请求就两处（NapCat + 你填的 AI 接口），单文件代码欢迎通读审计。

**Q：会不会往群里发消息？**
不会。只调 NapCat 的历史记录接口（读），代码里不存在发消息调用。

**Q：为什么用小号？**
主号零改动、零风险。小号拉进目标群即可，拉历史的前提是该账号能看到群历史消息。

**Q：为什么不提供 Docker 镜像？**
本工具依赖 NapCat 注入**桌面版 QQ**，QQ 必须跑在你的电脑上；总结脚本本身是零依赖单文件，容器化没有收益。真想容器化（如配 NapCat 官方 Docker 版上服务器），无需 Dockerfile：`docker run --rm -v "$(pwd)":/app -w /app python:3.12 python qq_digest.py`

**Q：和 AstrBot 等机器人框架是什么关系？**
没有关系。本项目不包含、不依赖任何机器人框架的代码，只通过 NapCat 暴露的 OneBot 11 HTTP API 通信。

**Q：能自动每天定时总结吗？**
项目刻意不带定时（保持无后台进程）。需要就用系统自带能力：Windows 任务计划程序 / crontab 定时执行 `python qq_digest.py`。

**Q：能总结多久之前的历史？**
受 QQ 自身消息记录（本地缓存 + 云端漫游）限制，且图片链接会过期。建议每天跑一次，别指望一次回溯几个月。

## 开发计划

- ✅ **v1.0**（当前）—— 单群/多群总结、图片保留、连通性自检、按日归档
- ⏳ **微信版** —— 同类能力适配微信（调研中，方案确定后发布）
- ⏳ **图形界面** —— 不想碰命令行的用户也能用
- ⏳ **可选定时归档**、更多模型适配、总结质量调优
- 💡 有想要的功能？去 [Issues](https://github.com/nanwaynan/qq-group-digest/issues) 提

## 交流 & 支持

- **QQ 交流群：`1121243020`** —— 使用问题、更新通知都发在群里
- **GitHub Issues**：[提问题 / 反馈](https://github.com/nanwaynan/qq-group-digest/issues)

> 跑不通？先执行 `python qq_digest.py --check`，把输出连同报错一起贴上来，定位快很多。

## 免责声明

本项目仅将用户**自己有权访问**的 QQ 群聊记录整理为本地文档，不向群聊发送任何消息。使用者应当：1）自行确认对目标群聊内容拥有合法的查看与整理权利；2）遵守所在地法律法规与腾讯平台用户协议；3）自行承担使用本项目产生的一切后果。**若他人使用本项目从事违法违规行为，与作者无关，后果由使用者自行承担。**

## License

[MIT](LICENSE)
