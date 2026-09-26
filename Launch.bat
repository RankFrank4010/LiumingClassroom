@echo off
rem LiumingClassroom 启动器：先检测/安装依赖，再启动主程序
setlocal
cd /d "%~dp0"

echo [LiumingClassroom] 正在检测运行环境...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"

if exist "%~dp0LiumingClassroom.exe" (
    start "" "%~dp0LiumingClassroom.exe"
) else (
    echo 未找到 LiumingClassroom.exe，请确认已正确解压全部文件。
    pause
)

endlocal
