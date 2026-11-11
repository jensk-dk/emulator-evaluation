@echo off
rem Startup launcher for Windows. See emu --help.
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m emulator %*
) else (
  python -m emulator %*
)
exit /b %errorlevel%
