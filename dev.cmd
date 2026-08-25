@echo off
setlocal
cd /d "%~dp0"

echo Starting ZHIJIAN AI development environment...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" -Restart -OpenBrowser
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Startup failed with exit code %EXIT_CODE%.
    echo Review the message above and logs under .dev\logs.
    pause
)

exit /b %EXIT_CODE%
