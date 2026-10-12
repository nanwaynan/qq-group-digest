@echo off
chcp 936 >nul 2>nul
cd /d "%~dp0"
title QQ 群聊总结器

rem ---- 查找 Python（优先 py 启动器，其次 python 命令）----
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)

rem ---- 没有 Python：提示并打开官网下载页 ----
if not defined PY (
    echo.
    echo   [!] 没有检测到 Python，无法启动。
    echo.
    echo   正在为你打开 Python 官网下载页。
    echo   安装时请务必勾选 "Add python.exe to PATH"，装完再双击本文件即可。
    echo.
    start "" "https://www.python.org/downloads/"
    echo   如果浏览器没有自动打开，请手动访问：
    echo   https://www.python.org/downloads/
    echo.
    echo   按任意键关闭本窗口。
    pause >nul
    exit /b 1
)

rem ---- 优先启动图形界面；缺少 tkinter 时退回命令行 ----
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo   [!] 当前 Python 缺少图形库 tkinter，改用命令行模式。
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
