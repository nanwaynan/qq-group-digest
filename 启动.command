#!/bin/bash
# macOS / Linux 启动脚本（双击或在终端 ./启动.command 运行）
cd "$(dirname "$0")" || exit 1

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            PY="$cand"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo
    echo "  [!] 没有检测到 Python 3.8 或更高版本。"
    echo
    echo "  macOS 安装方法（任选其一）："
    echo "    方式一：官网下载安装包  https://www.python.org/downloads/"
    echo "    方式二：有 Homebrew 的话执行  brew install python3"
    echo
    echo "  安装完成后，再次双击本文件即可。"
    echo
    read -r -p "  按回车键打开 Python 官网下载页..."
    if command -v open >/dev/null 2>&1; then
        open "https://www.python.org/downloads/"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "https://www.python.org/downloads/" >/dev/null 2>&1
    fi
    read -r -p "  按回车键关闭..."
    exit 1
fi

# 优先图形界面，缺少 tkinter 时退回命令行
if "$PY" -c 'import tkinter' >/dev/null 2>&1; then
    "$PY" qq_gui.py "$@"
    exit $?
else
    echo "  [!] 当前 Python 缺少图形库 tkinter，改用命令行模式。"
    echo "      如需图形界面：macOS 用 brew install python-tk；"
    echo "      Ubuntu/Debian 用 sudo apt install python3-tk"
    echo
    "$PY" qq_digest.py "$@"
    exit $?
fi
