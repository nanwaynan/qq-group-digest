#!/usr/bin/env python3
"""qq_digest 图形界面（tkinter，零第三方依赖）

双击「启动.bat」或「启动.command」默认打开本界面；也可以在终端运行：
    python qq_gui.py

界面功能与命令行完全一致（复用 qq_digest.py 的实现）：
    · 首次启动自动进入配置向导（群号 / NapCat / AI 接口与 Key）
    · 一键「开始总结」，右侧实时显示日志
    · 「连通性检测」验证 NapCat / 账号 / 群 / AI / 输出目录
    · 「打开输出目录」直接跳转看结果

依赖：Python 3.8+（Windows 自带 tkinter；Ubuntu 等 Linux 需 python3-tk）
"""

from __future__ import annotations

import datetime as dt
import queue
import sys
import threading
import webbrowser
from pathlib import Path

if sys.version_info < (3, 8):
    sys.stderr.write('需要 Python 3.8 或更高版本，当前为 %s\n' % sys.version.split()[0])
    raise SystemExit(1)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    sys.stderr.write(
        '未找到 tkinter（图形界面库）。\n'
        '  · Windows / macOS：官方安装包自带，请用官方 Python 重装\n'
        '  · Ubuntu / Debian：sudo apt install python3-tk\n'
        '装好后重新运行；也可以继续用命令行：python qq_digest.py\n')
    raise SystemExit(1)

import qq_digest as core

PY_URL = 'https://www.python.org/downloads/'


class DigestApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg_path = core.DEFAULT_CONFIG_PATH
        self.cfg = core.load_config(self.cfg_path)
        self.busy = False
        self.msgq: queue.Queue = queue.Queue()

        root.title(f'QQ 群聊总结器 v{core.__version__}')
        root.geometry('980x680')
        root.minsize(860, 560)

        self._build_widgets()
        self._refresh_config_view()
        self.root.after(100, self._drain)

        if not self.cfg:
            self._append('首次使用：请先完成配置向导。\n')
            self.root.after(300, self.open_wizard)
        elif core.validate_config(self.cfg, need_ai=True):
            self.root.after(300, self.open_wizard)
        else:
            self._append('已读取配置，点「开始总结」即可。\n')

    # ---------------- 界面构建 ----------------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        top.pack(fill='x')

        ttk.Label(top, text='QQ 群聊总结器', font=('Microsoft YaHei UI', 15, 'bold')).pack(side='left')
        ttk.Label(top, text=f'v{core.__version__} · 全程本地运行，不发群、无定时',
                  foreground='#666').pack(side='left', padx=(10, 0), pady=(6, 0))

        # 配置概览
        box = ttk.LabelFrame(self.root, text='当前配置', padding=10)
        box.pack(fill='x', padx=12, pady=(0, 6))
        self.lbl_cfg = ttk.Label(box, text='', justify='left', anchor='w')
        self.lbl_cfg.pack(fill='x')

        # 按钮区
        btns = ttk.Frame(self.root, padding=(12, 0))
        btns.pack(fill='x')
        self.btn_run = ttk.Button(btns, text='▶ 开始总结', command=self.on_run)
        self.btn_run.pack(side='left')
        self.btn_check = ttk.Button(btns, text='连通性检测', command=self.on_check)
        self.btn_check.pack(side='left', padx=6)
        self.btn_cfg = ttk.Button(btns, text='配置向导', command=self.open_wizard)
        self.btn_cfg.pack(side='left', padx=6)
        self.btn_open = ttk.Button(btns, text='打开输出目录', command=self.open_output)
        self.btn_open.pack(side='left', padx=6)
        ttk.Button(btns, text='更多选项 ▾', command=self.open_options).pack(side='left', padx=6)

        self.var_status = tk.StringVar(value='就绪')
        ttk.Label(btns, textvariable=self.var_status, foreground='#0a6').pack(side='right')

        # 日志
        logbox = ttk.LabelFrame(self.root, text='运行日志', padding=6)
        logbox.pack(fill='both', expand=True, padx=12, pady=8)
        self.txt = scrolledtext.ScrolledText(logbox, wrap='word', height=24,
                                             font=('Consolas', 10))
        self.txt.pack(fill='both', expand=True)
        self.txt.configure(state='disabled')

    # ---------------- 配置展示 ----------------

    def _refresh_config_view(self):
        cfg = self.cfg or {}
        ai = cfg.get('ai') or {}
        groups = cfg.get('groups') or []
        glist = '、'.join(f"{g.get('id')}（{g.get('name') or '未命名'}）" for g in groups) or '（未配置）'
        key = ai.get('key') or ''
        masked = (key[:3] + '***' + key[-4:]) if len(key) > 8 else ('已设置' if key else '（未配置）')
        self.lbl_cfg.configure(text=(
            f"总结的群：{glist}\n"
            f"NapCat：{cfg.get('napcat_api') or '（未配置）'}\n"
            f"AI 接口：{ai.get('base') or '（未配置）'}    模型：{ai.get('model') or '（未配置）'}    Key：{masked}\n"
            f"输出目录：{cfg.get('output_dir') or './output'}"
        ))

    # ---------------- 日志 ----------------

    def _append(self, text: str):
        self.txt.configure(state='normal')
        self.txt.insert('end', text)
        self.txt.see('end')
        self.txt.configure(state='disabled')

    def log(self, text: str):
        """线程安全的日志写入（供工作线程调用）。"""
        self.msgq.put(('log', text))

    def _drain(self):
        try:
            while True:
                kind, payload = self.msgq.get_nowait()
                if kind == 'log':
                    self._append(payload if payload.endswith('\n') else payload + '\n')
                elif kind == 'status':
                    self.var_status.set(payload)
                elif kind == 'done':
                    self._finish(payload)
                elif kind == 'open':
                    self._open_path(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # ---------------- 任务调度 ----------------

    def _start_task(self, name: str, fn):
        if self.busy:
            messagebox.showinfo('正在运行', '有任务正在执行，请等它结束。')
            return
        self.busy = True
        for b in (self.btn_run, self.btn_check, self.btn_cfg):
            b.state(['disabled'])
        self.var_status.set(f'{name}中...')
        self._append(f'\n{"=" * 60}\n{name}开始 {dt.datetime.now():%H:%M:%S}\n{"=" * 60}')

        def worker():
            code = 1
            try:
                code = fn()
            except Exception as e:
                self.log(f'任务异常：{type(e).__name__}: {e}')
            self.msgq.put(('done', (name, code)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, payload):
        name, code = payload
        self.busy = False
        for b in (self.btn_run, self.btn_check, self.btn_cfg):
            b.state(['!disabled'])
        if code == 0:
            self.var_status.set(f'{name}完成 ✔')
            self._append(f'{name}完成（{dt.datetime.now():%H:%M:%S}）\n')
        else:
            self.var_status.set(f'{name}结束，但有失败/跳过项')
            self._append(f'{name}结束，退出码 {code}（详见上方日志）\n')
        if name == '开始总结' and code == 0:
            if messagebox.askyesno('完成', '总结已生成，现在打开输出目录看看？'):
                self._open_path(self._output_root())

    # ---------------- 动作 ----------------

    def _load(self) -> bool:
        """重新读一次配置，返回是否可用。"""
        self.cfg = core.load_config(self.cfg_path)
        self._refresh_config_view()
        problems = core.validate_config(self.cfg, need_ai=True)
        if problems:
            messagebox.showwarning('配置不完整', '\n'.join(problems) + '\n\n请先完成配置向导。')
            self.open_wizard()
            return False
        return True

    def on_run(self):
        if not self._load():
            return
        self._start_task('开始总结', lambda: self._run_summary(label=None))

    def _run_summary(self, label) -> int:
        return self._run_summary_custom(label, 60000, True)

    def _run_summary_custom(self, label, max_count: int,
                            save_images: bool) -> int:
        cfg = self.cfg
        day_start_hour = int(cfg.get('day_start_hour') or 12)
        if label is None:
            label = core.latest_complete_day(day_start_hour)
        start_ts, end_ts = core.period_bounds(label, day_start_hour)
        start_dt = dt.datetime.fromtimestamp(start_ts)
        end_dt = dt.datetime.fromtimestamp(end_ts)
        period = f'{start_dt:%Y-%m-%d %H:%M} ~ {end_dt:%Y-%m-%d %H:%M}'

        self.log(f'日期标签：{label.isoformat()}')
        self.log(f'时间区间：{period}')
        groups = core.resolve_groups(cfg, None)
        failed = 0
        for i, g in enumerate(groups, 1):
            if len(groups) > 1:
                self.log(f'\n>>> 第 {i}/{len(groups)} 个群')
            try:
                if core.run_group(g, cfg, label, start_ts, end_ts, period,
                                  max_count, False, not save_images) != 0:
                    failed += 1
            except Exception as e:
                self.log(f'  处理群 {g.get("id")} 时出错：{type(e).__name__}: {e}')
                failed += 1
        return 1 if failed else 0

    def on_check(self):
        if not self._load():
            return
        self._start_task('连通性检测', self._run_check)

    def _run_check(self) -> int:
        return core.cmd_check(self.cfg, core.resolve_groups(self.cfg, None))

    def open_wizard(self):
        if self.busy:
            messagebox.showinfo('正在运行', '有任务正在执行，请等它结束。')
            return
        WizardDialog(self.root, self.cfg_path, self.cfg, on_saved=self._on_saved)

    def _on_saved(self, cfg: dict):
        self.cfg = cfg
        self._refresh_config_view()
        self._append('配置已保存。\n')

    def open_options(self):
        if not self._load():
            return
        OptionsDialog(self.root, self.cfg_path, self.cfg,
                      on_saved=self._on_saved, runner=self)

    def _output_root(self) -> Path:
        return Path((self.cfg or {}).get('output_dir') or './output').resolve()

    def open_output(self):
        path = self._output_root()
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def _open_path(self, path: Path):
        try:
            if sys.platform.startswith('win'):
                import os
                os.startfile(str(path))            # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', str(path)])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', str(path)])
        except Exception as e:
            messagebox.showwarning('打开失败', f'请手动打开：{path}\n（{e}）')


class WizardDialog:
    """配置向导（图形版），字段与命令行向导一致。"""

    def __init__(self, master, cfg_path: Path, cfg: dict | None, on_saved=None):
        self.cfg_path = cfg_path
        self.cfg = cfg or core.default_config()
        self.on_saved = on_saved
        self.existing_groups = list(self.cfg.get('groups') or [])

        self.win = tk.Toplevel(master)
        self.win.title('配置向导')
        self.win.geometry('660x560')
        self.win.transient(master)
        self.win.grab_set()

        pad = {'padx': 12, 'pady': 4}
        ttk.Label(self.win, text='几步填完，信息只保存在本机 config.json（不会上传）',
                  font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', **pad)

        nb = ttk.Notebook(self.win)
        nb.pack(fill='both', expand=True, padx=12, pady=8)

        # --- 第 1 页：连接 ---
        p1 = ttk.Frame(nb, padding=12)
        nb.add(p1, text=' 1. 连接设置 ')
        ttk.Label(p1, text='NapCat API 地址（没改过端口就用默认）').pack(anchor='w', pady=(0, 2))
        self.v_api = tk.StringVar(value=self.cfg.get('napcat_api') or 'http://127.0.0.1:3000')
        ttk.Entry(p1, textvariable=self.v_api).pack(fill='x')
        ttk.Label(p1, text='NapCat Token（没设置过就留空）').pack(anchor='w', pady=(10, 2))
        self.v_token = tk.StringVar(value=self.cfg.get('napcat_token') or '')
        ttk.Entry(p1, textvariable=self.v_token).pack(fill='x')
        ttk.Label(p1, text='总结保存目录').pack(anchor='w', pady=(10, 2))
        row = ttk.Frame(p1)
        row.pack(fill='x')
        self.v_out = tk.StringVar(value=self.cfg.get('output_dir') or './output')
        ttk.Entry(row, textvariable=self.v_out).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择...', command=self._pick_dir).pack(side='left', padx=(6, 0))

        # --- 第 2 页：群号 ---
        p2 = ttk.Frame(nb, padding=12)
        nb.add(p2, text=' 2. 要总结的群 ')
        ttk.Label(p2, text='每行一个：群号,群名称（群名称可省略，用英文逗号分隔）').pack(anchor='w')
        self.txt_groups = scrolledtext.ScrolledText(p2, height=10, font=('Consolas', 10))
        self.txt_groups.pack(fill='both', expand=True, pady=6)
        if self.existing_groups:
            self.txt_groups.insert('1.0', '\n'.join(
                f"{g.get('id')},{g.get('name') or ''}".rstrip(',')
                for g in self.existing_groups))
        ttk.Label(p2, text='群号在哪看：QQ 打开该群 → 右上角群资料 → 群号',
                  foreground='#666').pack(anchor='w')

        # --- 第 3 页：AI ---
        p3 = ttk.Frame(nb, padding=12)
        nb.add(p3, text=' 3. AI 接口 ')
        ai = self.cfg.get('ai') or {}
        ttk.Label(p3, text='接口地址（OpenAI 兼容，结尾要带 /v1）').pack(anchor='w', pady=(0, 2))
        self.v_base = tk.StringVar(value=ai.get('base') or '')
        ttk.Entry(p3, textvariable=self.v_base).pack(fill='x')
        ttk.Label(p3, text='模型名').pack(anchor='w', pady=(10, 2))
        self.v_model = tk.StringVar(value=ai.get('model') or '')
        ttk.Entry(p3, textvariable=self.v_model).pack(fill='x')
        ttk.Label(p3, text='API Key（留空则保留原值）').pack(anchor='w', pady=(10, 2))
        self.v_key = tk.StringVar(value='')
        ttk.Entry(p3, textvariable=self.v_key, show='*').pack(fill='x')
        ttk.Label(p3, text='示例：https://api.deepseek.com/v1 + deepseek-chat\n'
                           '本地 Ollama：http://127.0.0.1:11434/v1 + qwen2.5',
                  foreground='#666', justify='left').pack(anchor='w', pady=(8, 0))

        # --- 底部按钮 ---
        bottom = ttk.Frame(self.win, padding=(12, 0, 12, 12))
        bottom.pack(fill='x')
        ttk.Button(bottom, text='保存并关闭', command=self._save).pack(side='right')
        ttk.Button(bottom, text='取消', command=self.win.destroy).pack(side='right', padx=6)

    def _pick_dir(self):
        d = filedialog.askdirectory(title='选择总结保存目录')
        if d:
            self.v_out.set(d)

    def _save(self):
        groups = []
        for line in self.txt_groups.get('1.0', 'end').strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.replace('，', ',').split(',', 1)]
            if not parts[0]:
                continue
            groups.append({'id': parts[0], 'name': parts[1] if len(parts) > 1 else ''})
        if not groups:
            messagebox.showwarning('缺少群号', '请在第 2 页至少填一个群号。')
            return

        cfg = dict(self.cfg)
        cfg['napcat_api'] = self.v_api.get().strip().rstrip('/')
        cfg['napcat_token'] = self.v_token.get().strip()
        cfg['output_dir'] = self.v_out.get().strip() or './output'
        cfg['groups'] = groups
        ai = dict(cfg.get('ai') or core.default_config()['ai'])
        ai['base'] = self.v_base.get().strip().rstrip('/')
        ai['model'] = self.v_model.get().strip()
        new_key = self.v_key.get().strip()
        if new_key:
            ai['key'] = new_key
        cfg['ai'] = ai

        problems = core.validate_config(cfg, need_ai=True)
        if problems:
            messagebox.showwarning('还差一点', '\n'.join(problems))
            return

        core.save_config(self.cfg_path, cfg)
        if self.on_saved:
            self.on_saved(cfg)
        messagebox.showinfo('已保存', f'配置已写入：\n{self.cfg_path}')
        self.win.destroy()


class OptionsDialog:
    """高级选项：日期、拉取上限、图片。"""

    def __init__(self, master, cfg_path: Path, cfg: dict, on_saved=None, runner=None):
        self.cfg_path = cfg_path
        self.cfg = cfg
        self.runner = runner
        self.win = tk.Toplevel(master)
        self.win.title('更多选项')
        self.win.geometry('460x400')
        self.win.transient(master)
        self.win.grab_set()

        f = ttk.Frame(self.win, padding=12)
        f.pack(fill='both', expand=True)

        ttk.Label(f, text='总结哪一天（留空 = 最近一个已结束的完整周期）').pack(anchor='w')
        self.v_date = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_date).pack(fill='x')
        ttk.Label(f, text='格式：2026-10-09（该日 12:00 ~ 次日 12:00）',
                  foreground='#666').pack(anchor='w', pady=(2, 10))

        self.v_cur = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='总结尚未结束的当前周期（--include-current）',
                        variable=self.v_cur).pack(anchor='w', pady=(0, 10))

        ttk.Label(f, text='每个群最多拉取条数').pack(anchor='w')
        self.v_max = tk.StringVar(value='60000')
        ttk.Entry(f, textvariable=self.v_max).pack(fill='x', pady=(0, 10))

        self.v_img = tk.BooleanVar(value=bool(self.cfg.get('save_images', True)))
        ttk.Checkbutton(f, text='保留聊天图片', variable=self.v_img).pack(anchor='w', pady=(0, 10))

        ttk.Label(f, text='单期最多保留图片数').pack(anchor='w')
        self.v_maximg = tk.StringVar(value=str(self.cfg.get('max_images') or 100))
        ttk.Entry(f, textvariable=self.v_maximg).pack(fill='x', pady=(0, 14))

        btns = ttk.Frame(f)
        btns.pack(fill='x')
        ttk.Button(btns, text='保存设置', command=self._save).pack(side='right')
        ttk.Button(btns, text='取消', command=self.win.destroy).pack(side='right', padx=6)
        ttk.Button(btns, text='仅本次按上面设置运行', command=self._run_once).pack(side='left')

    def _apply(self, cfg: dict) -> dict:
        cfg = dict(cfg)
        cfg['save_images'] = bool(self.v_img.get())
        try:
            cfg['max_images'] = max(0, int(self.v_maximg.get()))
        except ValueError:
            cfg['max_images'] = self.cfg.get('max_images', 100)
        return cfg

    def _save(self):
        cfg = self._apply(self.cfg)
        core.save_config(self.cfg_path, cfg)
        if self.runner:
            self.runner.cfg = cfg
            self.runner._refresh_config_view()
        messagebox.showinfo('已保存', '选项已写入 config.json')
        self.win.destroy()

    def _run_once(self):
        if not self.runner:
            return
        label = None
        raw = self.v_date.get().strip()
        if raw:
            try:
                label = dt.date.fromisoformat(raw)
            except ValueError:
                messagebox.showwarning('日期格式错误', '请填 YYYY-MM-DD，例如 2026-10-09')
                return
        try:
            max_count = max(1, int(self.v_max.get()))
        except ValueError:
            messagebox.showwarning('条数错误', '拉取条数请填数字')
            return
        if self.v_cur.get() and label is None:
            day_start_hour = int(self.cfg.get('day_start_hour') or 12)
            label = (dt.datetime.now() - dt.timedelta(hours=day_start_hour)).date()

        cfg = self._apply(self.cfg)
        core.save_config(self.cfg_path, cfg)
        self.runner.cfg = cfg
        self.runner._refresh_config_view()
        self.win.destroy()
        self.runner._start_task(
            '开始总结',
            lambda: self.runner._run_summary_custom(label, max_count,
                                                    bool(self.v_img.get())))


def main() -> int:
    root = tk.Tk()
    try:
        root.call('tk', 'scaling', 1.2)
    except Exception:
        pass
    DigestApp(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
