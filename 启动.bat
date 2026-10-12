@echo off
chcp 65001 >nul
cd /d "%~dp0"
title QQ 群聊总结器

rem ---------- 找 Python：py 启动器 > python 命令 ----------
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)

rem ---------- 没装 Python：弹窗引导下载 ----------
if not defined PY (
    echo.
    echo   [!] 没有检测到 Python，无法启动。
    echo.
    echo   即将为你打开 Python 官网下载页，安装时请务必勾选
    echo   "Add python.exe to PATH"，装完再双击本文件即可。
    echo.
    start "" "https://www.python.org/downloads/"
    echo   正在打开下载页……若浏览器没有自动打开，请手动访问：
    echo   https://www.python.org/downloads/
    echo.
    echo   （按任意键关闭本窗口）
    pause >nul
    exit /b 1
)

rem ---------- 启动图形界面；tkinter 缺失则退回命令行 ----------
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo   [!] 当前 Python 缺少图形库（tkinter），改用命令行模式。
    echo       如需图形界面，请从 python.org 重新安装并勾选 tcl/tk 组件。
    echo.
    %PY% qq_digest.py %*
    pause
    exit /b %errorlevel%
)

%PY% qq_gui.py %*
if errorlevel 1 (
    echo.
    echo   图形界面启动失败，已切换为命令行模式。
    echo.
    %PY% qq_digest.py %*
    pause
)
