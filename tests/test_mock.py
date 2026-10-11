"""本地端到端自测：模拟 NapCat（OneBot 11 HTTP）与 OpenAI 兼容接口。

运行：
    python tests/test_mock.py

不需要真实的 QQ、NapCat 或 API Key，全部流量都在 127.0.0.1 上，
用于验证：分页回溯、区间过滤、长文分块、汇总合并、按日归档输出。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import qq_digest  # noqa: E402

GROUP_ID = '10010'
GROUP_NAME = '测试群'
N_MESSAGES = 300          # > 一页 200 条，必然触发翻页
MOCK_SUMMARY = 'MockAI 摘要 OK'


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _build_messages(napcat_port: int) -> list[dict]:
    """构造 N 条落在「今天 12:00 ~ 次日 12:00」区间内的消息。

    其中 6 条带可下载图片（i % 50 == 0），1 条带失效图片链接（i == 77），
    用于验证图片下载、编号重排与失败回退。
    """
    start = dt.datetime.combine(dt.date.today(), dt.time(hour=12, minute=0))
    msgs = []
    for i in range(N_MESSAGES):
        ts = start + dt.timedelta(minutes=4 * i + 60)   # 从 13:00 开始，300 条 ≈ 20 小时，全部落在周期内
        segs = [{'type': 'text', 'data': {'text': f'消息内容 {i}'}}]
        if i % 50 == 0:
            segs.append({'type': 'image',
                         'data': {'url': f'http://127.0.0.1:{napcat_port}/img/{i}.jpg'}})
        elif i == 77:
            segs.append({'type': 'image',
                         'data': {'url': f'http://127.0.0.1:{napcat_port}/img/broken.jpg'}})
        msgs.append({
            'message_id': 100000 + i,
            'time': int(ts.timestamp()),
            'sender': {'user_id': 1000 + i % 7, 'nickname': f'用户{i % 7}'},
            'message': segs,
        })
    return msgs


MESSAGES: list[dict] = []


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(length).decode()) if length else {}


class MockNapCat(_QuietHandler):
    """按 NapCat 的真实语义实现：message_seq 锚点 + reverse_order 往回翻；
    另外提供图片下载（/img/*.jpg），broken.jpg 返回 404 模拟失效链接。"""

    def do_GET(self):
        if self.path.startswith('/img/') and 'broken' not in self.path:
            body = b'\xff\xd8\xff\xe0' + b'fakejpegdata' * 32
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        payload = self._body()
        if self.path == '/get_group_msg_history':
            count = int(payload.get('count') or 200)
            anchor = payload.get('message_seq')
            if anchor is None:
                page = MESSAGES[:count]
            else:
                idx = next((i for i, m in enumerate(MESSAGES)
                            if m['message_id'] == anchor), None)
                page = [] if idx is None else MESSAGES[idx + 1: idx + 1 + count]
            self._json({'status': 'ok', 'retcode': 0,
                        'data': {'messages': page}})
        elif self.path == '/get_login_info':
            self._json({'status': 'ok', 'retcode': 0,
                        'data': {'user_id': 88888, 'nickname': '测试小号'}})
        elif self.path == '/get_group_info':
            self._json({'status': 'ok', 'retcode': 0,
                        'data': {'group_id': int(GROUP_ID), 'group_name': GROUP_NAME}})
        else:
            self._json({'status': 'failed', 'retcode': 404, 'data': None})


class MockAI(_QuietHandler):
    """OpenAI 兼容 /chat/completions，返回带图片引用的固定摘要。"""

    def do_POST(self):
        if self.path.endswith('/chat/completions'):
            self._body()  # 读取并丢弃请求体
            content = MOCK_SUMMARY + '\n\n大家看这张：[图片#1]'
            self._json({
                'choices': [{'message': {'content': content},
                             'finish_reason': 'stop'}],
                'usage': {'completion_tokens_details': {'reasoning_tokens': 0}},
            })
        else:
            self._json({'error': 'not found'})


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.napcat = ThreadingHTTPServer(('127.0.0.1', _free_port()), MockNapCat)
        cls.ai = ThreadingHTTPServer(('127.0.0.1', _free_port()), MockAI)
        # 图片 URL 里要带上端口，先起服务再生成消息
        MESSAGES[:] = sorted(_build_messages(cls.napcat.server_address[1]),
                             key=lambda m: -m['time'])  # 新 -> 旧
        for srv in (cls.napcat, cls.ai):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        cls.tmp_path = Path(cls.tmp.name)
        cls.config = cls.tmp_path / 'config.json'
        cls.config.write_text(json.dumps({
            'napcat_api': f'http://127.0.0.1:{cls.napcat.server_address[1]}',
            'groups': [{'id': GROUP_ID, 'name': GROUP_NAME}],
            'ai': {
                'base': f'http://127.0.0.1:{cls.ai.server_address[1]}/v1',
                'model': 'mock-model',
                'key': 'mock-key',
            },
            'output_dir': str(cls.tmp_path / 'output'),
            'chunk_chars': 2000,   # 故意调小，触发「分块总结 + 汇总」路径
        }, ensure_ascii=False), encoding='utf-8')
        # dry-run 专用配置（独立输出目录，便于断言「不写文件」）
        cls.config_dry = cls.tmp_path / 'config_dry.json'
        cls.config_dry.write_text(json.dumps({
            'napcat_api': f'http://127.0.0.1:{cls.napcat.server_address[1]}',
            'groups': [{'id': GROUP_ID, 'name': GROUP_NAME}],
            'output_dir': str(cls.tmp_path / 'output_dry'),
        }, ensure_ascii=False), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.napcat, cls.ai):
            srv.shutdown()
        cls.tmp.cleanup()

    def _run(self, *extra: str, config: Path | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        return subprocess.run(
            [sys.executable, str(ROOT / 'qq_digest.py'),
             '--config', str(config or self.config), *extra],
            capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)

    def test_check(self):
        r = self._run('--check')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('测试小号', r.stdout)
        self.assertIn('全部通过', r.stdout)

    def test_dry_run(self):
        # 未配置 AI 也能跑：只拉取统计，不调用 AI、不写文件
        r = self._run('--dry-run', '--include-current', config=self.config_dry)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'拉到 {N_MESSAGES} 条消息', r.stdout)
        self.assertIn('--dry-run：只统计不总结', r.stdout)
        dry_out = self.tmp_path / 'output_dry'
        self.assertFalse(dry_out.exists() and any(dry_out.iterdir()),
                         'dry-run 不应产生输出文件')

    def test_summarize_today(self):
        # 今天 12:00 起的周期尚未结束，用 --include-current 强行总结
        r = self._run('--include-current')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'拉到 {N_MESSAGES} 条消息', r.stdout)   # 分页必须拉全
        self.assertIn('成功保留 6/7 张', r.stdout)             # 6 张正常 + 1 张失效链接

        tag = dt.date.today().strftime('%y%m%d')
        day_dir = self.tmp_path / 'output' / GROUP_NAME / tag
        out = day_dir / f'{tag}.md'
        self.assertTrue(out.exists(), f'输出文件不存在：{out}')
        text = out.read_text(encoding='utf-8')
        self.assertIn(MOCK_SUMMARY, text)                      # AI 摘要已写入
        self.assertIn('消息内容 0', text)                       # 最旧一条（翻页到底）
        self.assertIn(f'消息内容 {N_MESSAGES - 1}', text)       # 最新一条
        self.assertIn('点击展开完整记录', text)                  # 原始记录折叠块

        # 图片保留：6 张成功，编号重排后 1..6；失效的那张还原为 [图片]
        imgs = sorted((day_dir / 'images').glob('*.*'))
        self.assertEqual(len(imgs), 6, [p.name for p in imgs])
        self.assertIn('> 图片：6/7 张已保留', text)             # 元信息行
        self.assertIn('大家看这张：![图片#1](images/001_', text)  # AI 引用被内嵌
        self.assertIn('## 附：本期图片（6/7 张）', text)         # 文末图片列表
        self.assertNotIn('[图片#7]', text)                      # 失败图片已回退
        self.assertIn('[图片]', text)                           # 回退占位符存在


if __name__ == '__main__':
    unittest.main(verbosity=2)
