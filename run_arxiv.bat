@echo off
:: 设置控制台支持 UTF-8 中文显示
chcp 65001
echo ====================================================
echo   ArXiv 论文分析 Agent 启动中...
echo   当前时间: %date% %time%
echo ====================================================

python "daily_paper.py"

if %ERRORLEVEL% equ 0 (
    echo.
    echo [成功] 论文抓取分析已完成，并已执行配置的推送。
) else (
    echo.
    echo [错误] 脚本运行出错，请检查 API Key 或网络连接。
)

echo.
echo 窗口将在 10 秒后自动关闭...
timeout /t 10
