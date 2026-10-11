#!/usr/bin/env python3
"""qq_digest —— QQ 群聊天记录 AI 总结（本地运行，不向群聊发送任何消息）

时间口径
    「一天」= 当天 12:00 到次日 12:00（可用配置项 day_start_hour 修改）。
    例：10月8日 12:00 ~ 10月9日 12:00 的消息，算作 10月8日 这一天。

配置
    首次运行自动进入配置向导，信息只保存在脚本同目录的 config.json
    （含 API Key，已被 .gitignore 排除，不会进入 git 仓库）。
    全部配置也可以直接编辑 config.json 或复制 config.example.json 修改。

用法
    python qq_digest.py                  # 首次配置后，总结最近一个已结束的完整周期
    python qq_digest.py --date 2026-10-09
    python qq_digest.py --include-current
    python qq_digest.py --group 123456   # 只总结某一个群
    python qq_digest.py --check          # 测试 NapCat / AI 接口连通性
    python qq_digest.py --dry-run        # 只拉取消息并统计，不调用 AI、不写文件
    python qq_digest.py --setup          # 重新运行配置向导

依赖
    Python 3.10+，仅标准库，无任何第三方依赖。
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

__version__ = '1.0.0'

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / 'config.json'

# NapCat 拉取参数（一般不用动）
PAGE_SIZE = 200        # 每页条数
MAX_PAGES = 400        # 最多翻页数（200 * 400 = 8 万条，足够覆盖一天）
MAX_RETRY = 3          # 单页 / 单次 AI 调用失败重试次数
PAGE_FAIL_LIMIT = 5    # 连续失败这么多页才放弃回溯（单页失败不丢已有数据）


def log(msg: str) -> None:
    print(msg, flush=True)


# ============================== 配置 ==============================

def default_config() -> dict:
    return {
        'napcat_api': 'http://127.0.0.1:3000',   # NapCat OneBot 11 HTTP API
        'napcat_token': '',                      # NapCat HTTP 服务若设了 token 则填写
        'groups': [],                            # [{'id': '群号', 'name': '群名称/备注'}]
        'ai': {
            'base': '',                          # OpenAI 兼容接口地址，含 /v1
            'model': '',
            'key': '',
        },
        'output_dir': './output',                # 总结文件保存位置
        'day_start_hour': 12,                    # 「一天」从几点开始
        'chunk_chars': 22000,                    # 超过该长度则分块总结
        'max_tokens': 32000,                     # 单次 AI 调用上限（推理模型要给足）
        'save_images': True,                     # 保留聊天中的图片到本地
        'max_images': 100,                       # 单期最多保留多少张
    }


def load_config(path: Path) -> dict | None:
    """读取配置；文件不存在返回 None，格式错误直接报错退出。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        log(f'配置文件 {path} 解析失败：{e}')
        raise SystemExit(1)
    if not isinstance(data, dict):
        log(f'配置文件 {path} 格式错误：顶层应为 JSON 对象')
        raise SystemExit(1)
    cfg = default_config()
    cfg.update({k: v for k, v in data.items() if k != 'ai'})
    if isinstance(data.get('ai'), dict):
        cfg['ai'].update(data['ai'])
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    """原子写入配置文件。"""
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def validate_config(cfg: dict, need_ai: bool) -> list[str]:
    problems = []
    if not cfg.get('napcat_api'):
        problems.append('缺少 napcat_api（NapCat 的 HTTP API 地址）')
    if not cfg.get('groups'):
        problems.append('缺少 groups（要总结的群号列表）')
    for g in cfg.get('groups') or []:
        if not str(g.get('id') or '').strip():
            problems.append(f'groups 中有群缺少 id：{g}')
    if need_ai:
        ai = cfg.get('ai') or {}
        if not ai.get('base'):
            problems.append('缺少 ai.base（OpenAI 兼容接口地址，含 /v1）')
        if not ai.get('model'):
            problems.append('缺少 ai.model（模型名）')
        if not ai.get('key'):
            problems.append('缺少 ai.key（API Key）')
    return problems


# ============================== 配置向导 ==============================

def ask(prompt: str, default: str = '') -> str:
    """带默认值的输入；直接回车取默认值。"""
    s = input(prompt).strip()
    return s or default


def ask_secret(prompt: str) -> str:
    """读敏感输入：真实终端下不回显；管道/脚本环境下退化为普通 input，
    以便无人值守配置（此时回显由运行环境决定）。"""
    try:
        if sys.stdin and sys.stdin.isatty():
            return getpass.getpass(prompt).strip()
    except Exception:
        pass
    return input(prompt).strip()


def run_wizard(path: Path, existing: dict | None) -> dict:
    """交互式配置向导，写入 path 并返回完整配置。"""
    cfg = existing or default_config()
    print()
    log('═' * 62)
    log(' 首次配置向导')
    log('═' * 62)
    log('你填写的一切只保存在本机的 config.json 中（已被 .gitignore 排除，')
    log('不会进入 git 仓库）。本脚本没有任何上传、统计或遥测逻辑，')
    log('网络请求只有两处：NapCat 地址和你自己填的 AI 接口地址。')
    log('')

    cfg['napcat_api'] = ask(
        f'[1/4] NapCat API 地址 [{cfg.get("napcat_api") or "http://127.0.0.1:3000"}]: ',
        cfg.get('napcat_api') or 'http://127.0.0.1:3000').rstrip('/')
    cfg['napcat_token'] = ask(
        '      NapCat Token（HTTP 服务没设 token 就直接回车）: ',
        cfg.get('napcat_token') or '')

    groups = [g for g in (cfg.get('groups') or []) if str(g.get('id') or '').strip()]
    if groups:
        names = '、'.join(f"{g['id']}({g.get('name') or '未命名'})" for g in groups)
        keep = ask(f'[2/4] 保留已配置的 {len(groups)} 个群（{names}）？(Y/n): ')
        if keep.lower() in ('n', 'no'):
            groups = []
    if not groups:
        while True:
            gid = ask('      要总结的群号（直接回车结束）: ')
            if not gid:
                break
            gname = ask('      群名称/备注（可回车跳过）: ')
            groups.append({'id': gid, 'name': gname})
            if ask('      继续添加其他群？(y/N): ').lower() not in ('y', 'yes'):
                break
    if not groups:
        log('至少需要配置一个群号。')
        raise SystemExit(1)
    cfg['groups'] = groups

    ai = cfg.get('ai') or {}
    log('[3/4] AI 接口（任意 OpenAI 兼容服务，本地推理或云端均可）')
    ai['base'] = ask('      接口地址（含 /v1）: ', ai.get('base') or '').rstrip('/')
    ai['model'] = ask('      模型名: ', ai.get('model') or '')
    if ai.get('key'):
        masked = ai['key'][:3] + '***' + ai['key'][-4:] if len(ai['key']) > 8 else '***'
        new_key = ask_secret(f'      API Key（回车保留 {masked}）: ')
        if new_key:
            ai['key'] = new_key
    else:
        ai['key'] = ask_secret('      API Key（输入不回显）: ')
    cfg['ai'] = ai

    cfg['output_dir'] = ask(
        f'[4/4] 总结保存目录 [{cfg.get("output_dir") or "./output"}]: ',
        cfg.get('output_dir') or './output')

    save_config(path, cfg)
    log('')
    log(f'已写入 {path}')
    log('该文件包含你的 API Key，请勿手动提交到 git（.gitignore 已排除）。')
    log('以后想改配置：直接编辑 config.json，或重新运行 python qq_digest.py --setup')
    return cfg


# ============================== 时间口径 ==============================

def period_bounds(label_day: dt.date, day_start_hour: int) -> tuple[float, float]:
    """返回统计区间 [当天 day_start_hour 点, 次日同点) 的 Unix 时间戳。"""
    start = dt.datetime.combine(label_day, dt.time(hour=day_start_hour))
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


def latest_complete_day(day_start_hour: int, now: dt.datetime | None = None) -> dt.date:
    """最近一个已结束的完整周期对应的日期标签。

    现在 10-09 13:35 -> 已结束的是 10-08（10-08 12:00 ~ 10-09 12:00）
    """
    now = now or dt.datetime.now()
    return (now - dt.timedelta(hours=day_start_hour)).date() - dt.timedelta(days=1)


# ============================== NapCat 接口 ==============================

def napcat_call(napcat_api: str, action: str, payload: dict,
                token: str = '', timeout: int = 90) -> dict:
    body = json.dumps(payload).encode()
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(
        f'{napcat_api}{action}', data=body, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_messages(napcat_api: str, token: str, group_id: str,
                   start_ts: float, end_ts: float, max_count: int) -> list[dict]:
    """从最新往回翻页，收集 [start_ts, end_ts) 区间内的消息。

    关键经验（缺一不可，否则每页都返回同一段最新消息，数据少 25 倍）：
      - 锚点 message_seq 用「本页最旧消息」的 message_id
      - 必须同时传 reverse_order=True
    """
    collected: list[dict] = []
    seen: set[str] = set()
    anchor = None
    failed_pages = 0

    for page in range(1, MAX_PAGES + 1):
        payload = {'group_id': str(group_id), 'count': PAGE_SIZE}
        if anchor is not None:
            payload['message_seq'] = anchor
            payload['reverse_order'] = True

        data = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                data = napcat_call(napcat_api, '/get_group_msg_history',
                                   payload, token)
                break
            except Exception as e:
                if attempt < MAX_RETRY:
                    time.sleep(2 * attempt)
                else:
                    failed_pages += 1
                    log(f'  第 {page} 页失败（重试 {MAX_RETRY} 次）：'
                        f'{type(e).__name__}: {e}')
        if data is None:
            # 单页失败不丢弃已拉取的数据；连续多页失败才视为终止
            if failed_pages >= PAGE_FAIL_LIMIT:
                log(f'  连续 {failed_pages} 页失败，停止回溯（已收集 {len(collected)} 条）')
                break
            log(f'  跳过该页，继续回溯（已收集 {len(collected)} 条）')
            continue

        failed_pages = 0
        msgs = (data.get('data') or {}).get('messages') or []
        if not msgs:
            break

        for m in msgs:
            mid = str(m.get('message_id'))
            if mid in seen:
                continue
            seen.add(mid)
            ts = m.get('time')
            if ts and start_ts <= ts < end_ts:
                collected.append(m)

        times = [m['time'] for m in msgs if m.get('time')]
        if not times:
            break

        if page % 10 == 0:
            lo = dt.datetime.fromtimestamp(min(times))
            log(f'  已翻 {page} 页，收集 {len(collected)} 条，'
                f'当前回溯到 {lo:%m-%d %H:%M}')

        # 翻过区间起点就停
        if min(times) < start_ts:
            break
        if len(collected) >= max_count:
            break

        oldest = min(msgs, key=lambda x: x.get('time', 0))
        new_anchor = oldest.get('message_id')
        if new_anchor is None or new_anchor == anchor:
            break
        anchor = new_anchor

    collected.sort(key=lambda m: m.get('time', 0))
    return collected


def _image_source(seg_data: dict) -> str | None:
    """从 image 段落里取图片来源：优先 http url，其次 QQ 本地缓存路径。"""
    url = seg_data.get('url')
    if isinstance(url, str) and url.startswith('http'):
        return url
    f = seg_data.get('file')
    if isinstance(f, str):
        if f.startswith('http'):
            return f
        try:
            if len(f) > 3 and Path(f).exists():
                return f
        except OSError:
            pass
    return None


def extract_text(msg: dict) -> tuple[str, list[str | None]]:
    """把一条消息转成可读文本；同时返回各图片段的来源（供下载）。"""
    parts = []
    sources: list[str | None] = []
    for seg in msg.get('message') or []:
        t = seg.get('type')
        d = seg.get('data') or {}
        if t == 'text':
            parts.append(str(d.get('text', '')))
        elif t == 'at':
            qq = d.get('qq')
            parts.append(f'@{qq}' if qq and qq != 'all' else '@全体成员')
        elif t == 'image':
            parts.append('[图片]')
            sources.append(_image_source(d))
        elif t == 'forward':
            parts.append('[合并转发]')
        elif t == 'file':
            parts.append(f"[文件:{d.get('name', '')}]")
        elif t == 'video':
            parts.append('[视频]')
        elif t == 'record':
            parts.append('[语音]')
    return re.sub(r'\s+', ' ', ''.join(parts)).strip(), sources


def build_transcript(msgs: list[dict]) -> tuple[str, int, list[dict]]:
    """构造纯文本记录；图片段记为 [图片#pid]，并返回待下载图片清单。"""
    lines = []
    pending: list[dict] = []
    for m in msgs:
        text, sources = extract_text(m)
        if not text:
            continue
        sender = m.get('sender') or {}
        name = sender.get('card') or sender.get('nickname') or str(m.get('user_id'))
        for src in sources:
            pid = len(pending) + 1
            pending.append({'pid': pid, 'src': src,
                            'who': str(name), 'ts': m.get('time', 0)})
            text = text.replace('[图片]', f'[图片#{pid}]', 1)
        ts = dt.datetime.fromtimestamp(m.get('time', 0)).strftime('%m-%d %H:%M')
        lines.append(f'[{ts}] {name}: {text}')
    return '\n'.join(lines), len(lines), pending


def sanitize_folder(name: str) -> str:
    """把群名转成可安全用作文件夹名的字符串。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]', '_', name).strip().strip('.')
    return cleaned


# ============================== 图片保留 ==============================

IMG_EXT_BY_CTYPE = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
    'image/webp': '.webp', 'image/bmp': '.bmp',
}
IMG_MAX_MB = 15          # 单张图片大小上限
IMG_TIMEOUT = 25         # 单张下载超时（秒）
IMG_WORKERS = 6          # 并发下载数


def _fetch_image(src: str, dest: Path) -> str | None:
    """下载（或复制）一张图片到 dest，成功返回 content-type（本地文件返回扩展名），失败返回 None。"""
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=IMG_TIMEOUT) as r:
            ctype = (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if ctype and not ctype.startswith('image/'):
                return None
            limit = int(IMG_MAX_MB * 1024 * 1024)
            data = b''
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                data += chunk
                if len(data) > limit:
                    return None
        dest.write_bytes(data)
        return ctype or 'image/jpeg'
    # 本地缓存路径直接复制
    p = Path(src)
    if p.stat().st_size > IMG_MAX_MB * 1024 * 1024:
        return None
    shutil.copyfile(p, dest)
    return p.suffix.lstrip('.').lower() or 'jpg'


def download_images(pending: list[dict], dest_dir: Path,
                    max_images: int) -> dict[int, tuple[Path, str]]:
    """并发下载待保留图片，返回 {pid: (临时文件, 类型)}；失败的不在结果里。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cands = [p for p in pending if p.get('src')][:max(0, max_images)]
    if not cands:
        return {}

    def work(p: dict):
        tmp = dest_dir / f'.img_{p["pid"]:03d}.part'
        try:
            ctype = _fetch_image(p['src'], tmp)
            if ctype:
                return p['pid'], tmp, ctype
        except Exception:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return p['pid'], None, None

    results: dict[int, tuple[Path, str]] = {}
    with ThreadPoolExecutor(max_workers=IMG_WORKERS) as ex:
        for pid, tmp, ctype in ex.map(work, cands):
            if tmp is not None:
                results[pid] = (tmp, ctype)
    return results


def save_kept_images(pending: list[dict], results: dict,
                     img_dir: Path) -> dict[int, dict]:
    """把下载成功的图片按最终编号重命名，返回 {最终编号: 图片信息}。"""
    files: dict[int, dict] = {}
    for fid, pid in enumerate(sorted(results), 1):
        tmp, ctype = results[pid]
        info = pending[pid - 1]
        ext = IMG_EXT_BY_CTYPE.get(ctype)
        if not ext:
            ext = Path(str(info['src'])).suffix.lower() or '.jpg'
            if not ext.startswith('.'):
                ext = '.' + ext
        ts = dt.datetime.fromtimestamp(info['ts'])
        who = sanitize_folder(info['who'])[:20] or '群友'
        name = f'{fid:03d}_{ts:%H%M}_{who}{ext}'
        tmp.replace(img_dir / name)
        files[fid] = {'name': name, 'who': info['who'], 'ts': ts}
    return files


def remap_image_markers(transcript: str, pending: list[dict],
                        results: dict) -> str:
    """下载结束后重编号：成功的 pid → 最终编号，失败的还原为 [图片]。"""
    pid2fid = {pid: fid for fid, pid in enumerate(sorted(results), 1)}

    def _sub(m: re.Match) -> str:
        pid = int(m.group(1))
        return f'[图片#{pid2fid[pid]}]' if pid in pid2fid else '[图片]'

    return re.sub(r'\[图片#(\d+)\]', _sub, transcript)


def embed_images(summary: str, files: dict) -> str:
    """把 AI 摘要中首次出现的图片编号替换为内嵌图片，其余保留文字标注。"""
    for fid, info in sorted(files.items()):
        for pat in (r'\[图片#%d\]', r'[（(]图片#%d[）)]', r'图片#%d(?!\d)'):
            m = re.search(pat % fid, summary)
            if m:
                summary = (summary[:m.start()]
                           + f'![图片#{fid}](images/{info["name"]})'
                           + summary[m.end():])
                break
    return summary


def build_gallery(files: dict) -> str:
    """构造文末图片列表（Markdown）。"""
    parts = []
    for fid, info in sorted(files.items()):
        ts = info['ts'].strftime('%m-%d %H:%M')
        parts.append(f'**图片#{fid}** · {info["who"]} · {ts}\n\n'
                     f'![图片#{fid}](images/{info["name"]})\n')
    return '\n'.join(parts)


# ============================== AI 总结 ==============================

CHUNK_PROMPT = """你是群聊内容整理助手。下面是 QQ 群「{group_name}」在 {period} 的**第 {idx}/{total} 部分**聊天记录。

请对这部分内容做**详细**的中文摘要，保留具体信息，Markdown 格式：

## 讨论话题
逐个列出本部分涉及的话题，每个都要写清：谁在讨论、具体说了什么、结论是什么。**越具体越好，保留工具名、网址、价格、版本号、命令等细节。**

## 有价值的信息
工具、资源、方法、教程、链接、踩坑经验，逐条列出。

## 值得记录的发言
引用原话，注明发言人。

注意：
- 忠实原始记录，不要编造
- 记录中的「[图片#n]」是聊天中图片的编号。若上下文明显在讨论某张图（比如发图后大家围着聊），在相应话题处标注（图片#n）；看不出来图的就别提，**严禁臆测图片内容**
- 不要客套话和总结性空话，直接给信息
- 这部分大约 {count} 条发言

记录如下：
---
{transcript}
---"""

FINAL_PROMPT = """下面是 QQ 群「{group_name}」在 {period} 的分段摘要（共 {total} 段）。
请把它们**合并**成一份完整、连贯、详细的群聊总结，Markdown 格式：

## 📌 本期概览
用 3-5 句话概括这段时间群里主要聊了什么。

## 🔥 主要话题
逐个列出主要讨论话题（按重要性排序，8-15 个），每个说明：讨论了什么、细节、结论或进展。保留工具名、版本号、价格、链接等具体信息。

## 💡 有价值的信息
分门别类整理干货：工具/资源/方法/教程/链接/踩坑经验。这是最重要的部分，务必详尽。

## 💬 精彩发言
挑 6-10 条有代表性的发言，引用原话并注明发言人。

## 👥 活跃成员
列出活跃成员及其关注点。

要求：
- 合并时去重，但不要丢失信息
- 忠实原始记录，不编造
- 分段摘要中的「图片#n」编号标注要保留，读者可对照文末图片列表查看原图
- 语言简洁，重点是信息密度

分段摘要如下：
---
{summaries}
---"""


def ai_chat(ai: dict, messages: list[dict], max_tokens: int,
            temperature: float = 0.3, timeout: int = 1800,
            retries: int = MAX_RETRY) -> str:
    """调用 OpenAI 兼容接口，带重试。

    注意：推理模型（deepseek-r1、hy3 等）的思维链 token 计入 max_tokens，
    配额给少了会 finish_reason=length 且正文为空，因此默认给足 32000。
    """
    last_err = None
    for attempt in range(1, retries + 1):
        body = json.dumps({
            'model': ai['model'],
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': temperature,
        }).encode()
        req = urllib.request.Request(
            f"{ai['base']}/chat/completions",
            data=body,
            headers={
                'Authorization': f"Bearer {ai['key']}",
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:500]
            last_err = f'HTTP {e.code}: {detail}'
            log(f'      调用失败（{attempt}/{retries}）：{last_err}')
            time.sleep(2 * attempt)
            continue
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            log(f'      调用异常（{attempt}/{retries}）：{last_err}')
            time.sleep(2 * attempt)
            continue

        choice = (data.get('choices') or [{}])[0]
        content = ((choice.get('message') or {}).get('content') or '').strip()
        finish = choice.get('finish_reason')
        usage = data.get('usage') or {}
        reasoning = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')

        if content:
            if finish == 'length':
                log(f'      注意：输出达到长度上限（推理 {reasoning} tokens），可能被截断')
            return content

        last_err = f'返回空内容（finish_reason={finish}, reasoning_tokens={reasoning}）'
        log(f'      空响应（{attempt}/{retries}）：{last_err}')
        time.sleep(2 * attempt)

    raise RuntimeError(f'AI 调用失败（已重试 {retries} 次）：{last_err}')


def ai_summarize(ai: dict, group_name: str, period: str,
                 transcript: str, chunk_chars: int, max_tokens: int) -> str:
    """分块总结 + 汇总，避免单次塞太多导致内容被压缩。"""
    if len(transcript) <= chunk_chars:
        log(f'  记录 {len(transcript)} 字符，单次总结')
        return ai_chat(ai, [
            {'role': 'user', 'content': CHUNK_PROMPT.format(
                group_name=group_name, period=period, idx=1, total=1,
                count='若干', transcript=transcript)},
        ], max_tokens=max_tokens)

    # 按行切块，尽量不切断单条消息
    lines = transcript.split('\n')
    chunks, cur, cur_len = [], [], 0
    for line in lines:
        if cur_len + len(line) > chunk_chars and cur:
            chunks.append('\n'.join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append('\n'.join(cur))

    log(f'  记录较长，分 {len(chunks)} 块分别总结')

    partials = []
    for i, chunk in enumerate(chunks, 1):
        log(f'    第 {i}/{len(chunks)} 块（{len(chunk)} 字符）...')
        n = chunk.count('\n') + 1
        partials.append(ai_chat(ai, [
            {'role': 'user', 'content': CHUNK_PROMPT.format(
                group_name=group_name, period=period, idx=i,
                total=len(chunks), count=n, transcript=chunk)},
        ], max_tokens=max_tokens))
        log(f'      完成（{len(partials[-1])} 字符）')

    log(f'  汇总 {len(partials)} 段摘要...')
    combined = '\n\n'.join(
        f'### 第 {i} 段摘要\n{p}' for i, p in enumerate(partials, 1))
    return ai_chat(ai, [
        {'role': 'user', 'content': FINAL_PROMPT.format(
            group_name=group_name, period=period,
            total=len(partials), summaries=combined)},
    ], max_tokens=12000)


# ============================== 子命令：check ==============================

def cmd_check(cfg: dict, groups: list[dict]) -> int:
    """测试 NapCat / AI 接口连通性，不拉消息不花钱。"""
    ok = True
    base = cfg['napcat_api']
    token = cfg.get('napcat_token') or ''

    log(f'[1/3] NapCat：{base}')
    try:
        info = napcat_call(base, '/get_login_info', {}, token, timeout=10)
        d = info.get('data') or {}
        log(f'      连接正常，已登录账号：{d.get("user_id")}（{d.get("nickname")}）')
    except Exception as e:
        ok = False
        log(f'      连接失败：{type(e).__name__}: {e}')
        log('      → NapCat 没启动？端口不对？或 token 不匹配？')

    for g in groups:
        gid = str(g['id'])
        try:
            info = napcat_call(base, '/get_group_info',
                               {'group_id': gid}, token, timeout=10)
            name = (info.get('data') or {}).get('group_name') or '（未知群名）'
            log(f'      群 {gid}：{name} —— 账号在该群中')
        except Exception as e:
            log(f'      群 {gid}：查询失败（{type(e).__name__}）'
                f'—— 可能不在该群，或该群信息不可见')

    ai = cfg.get('ai') or {}
    log(f'[2/3] AI 接口：{ai.get("base") or "（未配置）"}')
    if not (ai.get('base') and ai.get('model') and ai.get('key')):
        log('      AI 未配置完整，跳过（--dry-run 模式不需要 AI）')
    else:
        try:
            data = ai_chat(ai, [{'role': 'user', 'content': '连通性测试，请回复：OK'}],
                           max_tokens=512, timeout=60, retries=1)
            log(f'      连接正常，模型有响应（{len(data)} 字符）')
        except Exception as e:
            ok = False
            log(f'      连接失败：{e}')

    log('[3/3] 输出目录')
    out = Path(cfg.get('output_dir') or './output')
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / '.write_test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        log(f'      {out.resolve()} 可写')
    except Exception as e:
        ok = False
        log(f'      {out} 不可写：{e}')

    log('')
    log('全部通过 ✔' if ok else '存在问题 ✘（见上方日志）')
    return 0 if ok else 1


# ============================== 主流程 ==============================

def run_group(g: dict, cfg: dict, label: dt.date, start_ts: float,
              end_ts: float, period: str, args) -> int:
    """总结单个群，返回 0 成功 / 1 跳过或失败。"""
    gid = str(g['id'])
    gname = str(g.get('name') or '')
    display = gname or f'群 {gid}'

    log('=' * 64)
    log(f'总结 {display}（{gid}）')
    log(f'时间区间：{period}')
    log(f'日期标签：{label.isoformat()}')
    log('=' * 64)

    log('[1/4] 拉取聊天记录（分页回溯）...')
    t0 = time.time()
    msgs = fetch_messages(cfg['napcat_api'], cfg.get('napcat_token') or '',
                          gid, start_ts, end_ts, args.max)
    if not msgs:
        log('  区间内没有消息，跳过。')
        return 1
    transcript, line_count, pending = build_transcript(msgs)
    log(f'  拉到 {len(msgs)} 条消息，有效发言 {line_count} 条，'
        f'{len(transcript)} 字符，耗时 {time.time() - t0:.1f}s')

    # 输出目录提前确定，图片就下在 md 旁边
    tag = label.strftime('%y%m%d')
    folder_name = sanitize_folder(gname) or gid
    folder = Path(cfg.get('output_dir') or './output') / folder_name / tag

    # 保留图片：下载成功才给正式编号，失败还原为 [图片]
    files: dict[int, dict] = {}
    if pending and not args.dry_run and cfg.get('save_images', True) \
            and not getattr(args, 'no_images', False):
        max_images = int(cfg.get('max_images') or 100)
        log(f'[2/4] 保留图片：发现 {len(pending)} 张（上限 {max_images} 张）...')
        results = download_images(pending, folder / 'images', max_images)
        if results:
            transcript = remap_image_markers(transcript, pending, results)
            files = save_kept_images(pending, results, folder / 'images')
            log(f'  成功保留 {len(files)}/{len(pending)} 张')
        else:
            log('  没有图片下载成功（历史图片链接可能已过期），继续纯文字总结')

    if args.dry_run:
        log('  --dry-run：只统计不总结。最近 10 条预览：')
        for line in transcript.split('\n')[-10:]:
            log(f'    {line}')
        return 0

    log('[3/4] 调用 AI 总结...')
    t1 = time.time()
    try:
        summary = ai_summarize(cfg['ai'], display, period, transcript,
                               int(cfg.get('chunk_chars') or 22000),
                               int(cfg.get('max_tokens') or 32000))
    except RuntimeError as e:
        log(f'  {e}')
        return 1
    if files:
        summary = embed_images(summary, files)
    log(f'  完成，{len(summary)} 字符，耗时 {time.time() - t1:.1f}s')

    log('[4/4] 写入文件...')
    folder.mkdir(parents=True, exist_ok=True)
    out_file = folder / f'{tag}.md'

    img_meta = f'> 图片：{len(files)}/{len(pending)} 张已保留\n' if pending else ''
    img_section = ''
    if files:
        img_section = f"""---

## 附：本期图片（{len(files)}/{len(pending)} 张）

<details>
<summary>点击展开图片列表（正文中已内嵌 AI 引用的图片）</summary>

{build_gallery(files)}

</details>
"""

    out_file.write_text(f"""# {display} 群聊总结 - {label.isoformat()}

> 群号：{gid}
> 时间区间：{period}
> 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}
> 有效发言：{line_count} 条
{img_meta}> AI 模型：{cfg['ai']['model']}

---

{summary}

{img_section}---

## 附：原始聊天记录

<details>
<summary>点击展开完整记录（{line_count} 条）</summary>

```
{transcript}
```

</details>
""", encoding='utf-8')

    log(f'  已保存：{out_file}')
    log('')
    log('--- 总结预览（前 1500 字）---')
    log(summary[:1500])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog='qq_digest.py',
        description='QQ 群聊天记录 AI 总结（本地运行，不向群聊发送任何消息）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python qq_digest.py                  总结最近一个已结束的完整周期
  python qq_digest.py --date 2026-10-09
  python qq_digest.py --include-current
  python qq_digest.py --group 123456   只总结某一个群
  python qq_digest.py --check          测试 NapCat / AI 连通性
  python qq_digest.py --dry-run        只拉取统计，不调用 AI
  python qq_digest.py --setup          重新运行配置向导
""")
    ap.add_argument('--config', default=str(DEFAULT_CONFIG_PATH),
                    help=f'配置文件路径（默认 {DEFAULT_CONFIG_PATH.name}）')
    ap.add_argument('--setup', action='store_true', help='（重新）运行配置向导')
    ap.add_argument('--check', action='store_true',
                    help='测试 NapCat / AI 接口连通性，不拉取不总结')
    ap.add_argument('--dry-run', action='store_true',
                    help='只拉取消息并统计，不调用 AI、不写文件')
    ap.add_argument('--date', help='日期标签 YYYY-MM-DD（该日 12:00 ~ 次日 12:00）')
    ap.add_argument('--group', help='只总结指定群号（可在配置之外临时指定）')
    ap.add_argument('--max', type=int, default=60000, help='每个群最多拉取条数')
    ap.add_argument('--include-current', action='store_true',
                    help='允许总结尚未结束的当前周期')
    ap.add_argument('--no-images', action='store_true',
                    help='本次不保留图片（覆盖配置里的 save_images）')
    ap.add_argument('--version', action='version',
                    version=f'%(prog)s {__version__}')
    args = ap.parse_args(argv)

    path = Path(args.config)
    cfg = load_config(path)

    if cfg is None and not args.setup and not sys.stdin.isatty():
        log(f'未找到配置文件 {path}，且当前不是交互终端。')
        log('请复制 config.example.json 为 config.json 并填写，')
        log('或在终端中运行 python qq_digest.py 进入配置向导。')
        return 1

    if args.setup or cfg is None:
        try:
            cfg = run_wizard(path, cfg)
        except (EOFError, KeyboardInterrupt):
            log('\n已取消配置。')
            return 1
        if args.setup and not (args.check or args.dry_run):
            return 0

    if args.check:
        return cmd_check(cfg, resolve_groups(cfg, args.group))

    problems = validate_config(cfg, need_ai=not args.dry_run)
    if problems:
        log('配置不完整，无法继续：')
        for p in problems:
            log(f'  - {p}')
        log('运行 python qq_digest.py --setup 重新配置，或直接编辑配置文件。')
        return 1

    day_start_hour = int(cfg.get('day_start_hour') or 12)
    if args.date:
        try:
            label = dt.date.fromisoformat(args.date)
        except ValueError:
            log(f'--date 格式应为 YYYY-MM-DD，收到：{args.date}')
            return 1
    else:
        if args.include_current:
            # 当前正在进行的周期（必然未结束）：now 落在 [L 12:00, L+1 12:00)
            label = (dt.datetime.now() - dt.timedelta(hours=day_start_hour)).date()
        else:
            label = latest_complete_day(day_start_hour)
    start_ts, end_ts = period_bounds(label, day_start_hour)
    start_dt = dt.datetime.fromtimestamp(start_ts)
    end_dt = dt.datetime.fromtimestamp(end_ts)
    period = f'{start_dt:%Y-%m-%d %H:%M} ~ {end_dt:%Y-%m-%d %H:%M}'

    if end_dt > dt.datetime.now() and not args.include_current:
        log(f'周期 {period} 尚未结束，跳过。')
        log('（如需强行总结当前周期，加 --include-current）')
        return 1

    groups = resolve_groups(cfg, args.group)
    log(f'NapCat：{cfg["napcat_api"]}    AI：{cfg["ai"]["model"]} @ {cfg["ai"]["base"]}')
    log(f'待总结群：{", ".join(str(g["id"]) for g in groups)}')

    failed = 0
    for i, g in enumerate(groups, 1):
        if len(groups) > 1:
            log(f'\n>>> 第 {i}/{len(groups)} 个群')
        try:
            if run_group(g, cfg, label, start_ts, end_ts, period, args) != 0:
                failed += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f'  处理群 {g["id"]} 时出错：{type(e).__name__}: {e}')
            failed += 1
    return 1 if failed else 0


def resolve_groups(cfg: dict, only_group: str | None) -> list[dict]:
    """按 --group 过滤；配置外的群号也允许临时使用。"""
    groups = cfg.get('groups') or []
    if not only_group:
        seen: set[str] = set()
        uniq = []
        for g in groups:
            gid = str(g['id'])
            if gid not in seen:
                seen.add(gid)
                uniq.append(g)
        return uniq
    match = [g for g in groups if str(g['id']) == str(only_group)]
    return match or [{'id': str(only_group), 'name': ''}]


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断。', file=sys.stderr)
        sys.exit(130)
